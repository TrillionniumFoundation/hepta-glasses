# Durable model gateway and foreground Responses adapter

Status: incremental HG-0087/model source candidate; aggregate and slice OPEN.
Owner: ai-platform. Primary source: `services/model_gateway/production.py` and
`services/model_gateway/responses_provider.py`. Contract:
`contracts/durable-model-gateway-v2.json`. Operations:
`docs/operations/DURABLE_MODEL_GATEWAY_RUNBOOK.md`.

## Responsibility and API

The v2 gateway records a request before a provider exchange, serializes quota and
idempotency across local connections, rejects stale/revoked delivery, and only
allows bounded readback after uncertainty. It stores metadata, not questions,
context, answers, credentials or raw provider identifiers. This is not an
identity service, encrypted vault, tool executor or final effect authority.

`ProductionModelGateway(path, provider=..., provider_binding=..., clock=...)`
requires an explicit trusted integer-second host clock and a non-secret provider
configuration binding. A concrete provider exposing `binding_id` must match it.
The caller authenticates subject/session, establishes actual data-processing
consent and supplies its absolute expiry. No client JSON field proves consent.
There is deliberately no automatic HTTP ingress wiring: `app.py` remains a
separate deterministic development endpoint and consumer mutation authority is
unchanged. The separate identity enrollment-freshness repair is documented in
`docs/development/IDENTITY_ENROLLMENT_FRESHNESS.md`; independent acceptance and
production identity integration remain open.

| Method | Semantics |
|---|---|
| `execute(subject, session_id, idempotency_key, question, context, expires_at, timeout_seconds)` | Atomically reserve a first dispatch, or reserve readback only for an existing unresolved request; return text and metadata only after final authority checks |
| `cancel(subject, idempotency_key)` | Durable local delivery denial; unknown request IDs can be tombstoned before a racing admission |
| `revoke_session(session_id, subject=...)` | Subject-scoped terminal session denial; no remote cancellation claim |
| `status(subject, idempotency_key)` | Immutable metadata snapshot, never a cached answer or future delivery permission |
| `recoverable(subject, limit=100)` | Bounded metadata inventory of prepared/indeterminate requests; no automatic external work |

The result's `provider_request_id` and `provider_receipt_id` fields retain their
legacy names for metadata consumers but contain SHA-256 hashes, not raw provider
IDs or externally signed receipts. The answer digest is also a hash. Metadata
including hashes can still be identifying or susceptible to dictionary attacks;
it needs access control and operational encryption. A receipt is not evidence
that the model answer is correct or that an independent authority accepted it.

## State and concurrency

Schema component `model_gateway`, version 2, uses the existing `DurableDatabase`
primitive (SQLite WAL, FULL synchronous mode, `BEGIN IMMEDIATE`). A process-local
lock is insufficient for quota correctness: quota count, subject-scoped unique
key reservation and its event now share one database transaction. A reservation
consumes daily request quota even if later delivery fails. There are no refunds
or row eviction that could reopen a completed idempotency key. This is an attempt
quota, not a dollar cap or an exact input-token/billing quota.

The fingerprint binds subject, session, question/context bytes, provider policy
and the absolute authority expiry. A stable remote correlation key additionally
binds the idempotency key. Same-key argument/provider/session/expiry changes are
conflicts. Different subjects have different keys even when their local strings
coincide. The provider receives a defensive JSON snapshot, not the caller's
mutable context object. Canonicalization does not remove the need for host data
minimization, authenticated consent and prompt-injection defenses at consumers.

The initial row is `prepared` with a unique claim token and bounded claim lease.
Only the caller commits a result; provider workers never mutate request state.
A duplicate live claim returns in-progress rather than running a second request.
After timeout, error or an expired abandoned claim, a later operation can only
call `reconcile` and consumes a persisted readback budget. A new claim fences all
older callers. A process exit after reservation but before a response does not
permit resubmission, even when the host cannot determine whether the POST began.

A worker rechecks the claim, current clock and denial state after scheduling and
lock waiting, immediately before leaving local admission for the provider call.
The final result transaction rechecks the claim, subject/session/request denial,
persisted absolute expiry and monotonic caller deadline. It checks time again
before commit. Expiry while waiting or committing rolls back both the result
state and its success event. Clock rollback after committed observed time denies
new admission; this does not protect against restoring a whole old database.

Local cancellation marks unresolved rows `cancelled`; revocation after an earlier
commit preserves that historical commit but sets `delivery_revoked` in status and
blocks further `execute`. A denial that wins before the final commit prevents a
late answer from being returned. A revocation committed after a successful final
transaction cannot retract bytes already returned. The host must recheck identity
and separate effect authority at each downstream effect; model output is data.

## Concrete provider exchange and algorithm boundary

`ResponsesProvider(model, deployment_id, credential, maximum_output_tokens=1024)`
implements one real HTTPS POST to `api.openai.com:443/v1/responses` using Python's
HTTP/TLS primitives and system certificate/hostname verification. The credential
is obtained from a trusted callable only in the worker; no source/env credential
fallback, caller endpoint, proxy, redirect or HTTP retry is provided. The fixed
API options are foreground, non-streaming, `store=false`, `tools=[]` and
`tool_choice=none`. Question/context are plain user-message data, never merged
into request options. The model identifier must match the response exactly; use
an operator-qualified pinned model ID rather than assuming aliases are stable.

The adapter bounds and validates headers, response bytes, JSON, completed status,
model/retention configuration, output shape and usage arithmetic. Only completed
assistant `output_text` is returned. Tool-call or unknown output items fail the
request; reasoning items are not forwarded, persisted or granted authority.
The configured output-token maximum and returned usage are checked, but transport
uncertainty can still incur a remote charge. Provider billing must be controlled
and observed separately. Response/vault/transport errors are reduced to fixed
codes without raw exception chaining, body logging or error-body reflection.

`X-Client-Request-Id` is correlation, not an idempotency or lookup contract. In
this foreground, nonstored profile, `reconcile` returns unknown without issuing
another HTTP request. Thus a lost answer stays indeterminate; the adapter does
not fabricate recovery or silently submit another generation. The gateway's
readback mechanism is implemented and tested with a contract fixture, but this
specific provider profile cannot recover an answer from its correlation key.

Local cancellation does not terminate a remote foreground request. The documented Responses cancellation
endpoint applies to background responses, which this profile does not create.
Both gateway denial methods explicitly report
`remote_cancellation_confirmed=false`. No remote job termination, charge reversal
or provider deletion receipt is inferred from a local cancellation or timeout.

`store=false` requests disabling response-object storage; it does not independently
establish Zero Data Retention, abuse-monitoring exclusions, regional processing,
cache policy or deletion of provider infrastructure records. Production tenancy,
retention settings, model access and contract acceptance require real evidence.

## Failure and recovery

| Observation | Persisted outcome | Allowed next step |
|---|---|---|
| Input/consent/policy validation fails | No new dispatch reservation | Correct inputs through the authenticated host path |
| Reservation/event transaction aborts | Neither reservation nor event commits | Retry only after checking current authority |
| Provider fails, hangs or caller times out | Prepared/indeterminate metadata retained | Bounded readback only; never replay the POST |
| Process exits after reservation | Prepared row remains | Wait for its claim lease, then readback under the same unextended authority |
| Cancel/revoke during generation/readback | Terminal local denial wins | Keep denial; investigate remote state separately |
| Expiry or clock drift at result commit | No answer/success event is committed | Do not extend stored consent or reclassify old output as current |
| Returned request binding is wrong | No answer admitted | Investigate provider composition; no silent failover |
| Database failure | No success is returned | Restore trusted storage without discarding old requests/denials |

The default worker pool is four per gateway object. Timed-out work retains its
permit until the actual worker exits. It is not a global distributed rate limit
or process sandbox: constructing many gateway objects creates more pools. Deploy
bounded replicas with independent provider-side limits. Socket operations and
body loops use remaining deadlines, but DNS/system calls, slow headers and a
noncooperative credential/provider implementation can outlive the caller. Hard
worker termination and resource isolation remain deployment requirements.

## Configuration and migration

Defaults/ceilings: 1,000 daily requests per subject (configurable up to 10,000),
8,000 question characters, 32 KiB encoded context, depth 8, 2,048 JSON nodes,
256 members per context collection, 64 KiB delivered answer, 256 KiB HTTP response,
300-second maximum authority lifetime, 60-second maximum caller timeout,
4 workers (up to 16), 3 readbacks (up to 8), and 4,096 lifetime request rows
(up to 10,000). Combined cancellation/session tombstones have the same lifetime
row budget. A denial beyond capacity suspends all admission instead of evicting
a denial. Repeated suspension does not grow the event table. No unsuspend/delete
API is provided. Emergency denial uses the last committed clock observation even
when current clock acquisition fails.

The API intentionally requires new `clock`, `provider_binding` and `expires_at`
inputs; a caller-supplied `now` no longer selects the quota day or freshness.
`ProviderResult` must bind the exact request key. Migrate callers explicitly.
Unversioned predecessor `requests`/`revoked_sessions` tables are rejected even if
empty. A known v2 marker with missing component tables or missing policy is also
rejected. No policy-changing reopen, reset, automatic migration, dropped-table
recreation or stale snapshot restore is supported. Review migration separately
and retain all request identities, unknown effects, scope, expiry and denials.

## Operations and verification

Run the four `services.model_gateway` custody/provider suites and the full
repository seven-lane matrix on the final unchanged commit. The added regression
cases use real SQLite, independent connections, actual subprocess exits and
controlled provider/wire fixtures. They do not call the live API or use real
credentials. Full-import/mobile/native verification must come from full-repository
CI when an affected-path local workspace is used.

Keep service accounts, database paths, tenant/model mappings and credential vaults
operator-owned. No prompts, answers, headers, provider error bodies or credentials
belong in logs. Export fixed error codes and protected aggregate counters; do not
claim this library provides a production observability pipeline. Restrict access
to metadata and audit events; use reviewed retention/backup/anti-rollback policy.
The local event table is diagnostic, not an externally witnessed log.

## Platform and evidence

The gateway requires trusted local SQLite storage; the concrete adapter requires
Python HTTP/TLS and system trust roots. It is not a multi-region database, signed
mobile enrollment flow, platform attestation verifier or provider qualification.
HG-0087/model remains OPEN for authenticated ingress/mobile/session integration,
real provider tenancy and retention/billing/abuse qualification, remote cancellation
and authoritative recovery, service isolation, encrypted metadata custody,
production observability and independent acceptance. Other slices and all
external/product gates remain unchanged. Keep PR #101 Draft, no self-approval,
merge, deployment, release or protection bypass.

### Primary implementation references (checked 2026-09-05)

- OpenAI API reference, create a model response:
  https://developers.openai.com/api/reference/resources/responses/methods/create/
- Request IDs and authentication:
  https://developers.openai.com/api/reference/overview/
- Cancellation is limited to background responses:
  https://developers.openai.com/api/reference/resources/responses/methods/cancel/
- Data controls and retention:
  https://developers.openai.com/api/docs/guides/your-data
- Conversation state and response-object storage:
  https://developers.openai.com/api/docs/guides/conversation-state

The source contract narrows the supported profile; documentation is not evidence
of a live tenant test or a provider's agreement to this application's guarantees.


## Final pre-send admission after credentials and TLS

The 4a1e0867 source was reproduced with its real gateway, SQLite and transport
control flow and inert local connection fixtures: cancelling during credential
resolution or TLS setup still issued one POST before the final result gate
rejected delivery. Expiry during credential resolution behaved similarly. This
is the distinction between withholding an answer and preventing prompt egress;
no live user data or provider request was involved in the reproduction.

The gateway now passes a trusted `authorize()` callback to an optional
`generate_authorized` adapter method. The callback reopens a write transaction,
checks the original request key/claim and nonterminal state, subject/session or
request denial, absolute authority expiry, original monotonic caller deadline
and unchanged provider binding. The existing transaction checks time again on
exit. It does not issue a new grant, extend expiry or refund an attempt.

`ResponsesProvider.generate_authorized` requires a callable and invokes it after
credential lookup and TLS connection establishment, immediately before sending
HTTP request bytes. It then recalculates the socket timeout from the SAME
remaining transport budget; database waiting cannot refresh that budget. No
network call runs inside the authorization transaction. On denial or validation
failure, connection cleanup runs and no POST is made. The gateway retains its
existing cancelled or indeterminate metadata and no-auto-replay behavior. Failed
storage is not permission to send. Prompt/context/credential values are not put
in the metadata ledger or error text.

The gateway's public `provider` and `provider_binding` properties are readonly.
An adapter exposing a changed binding ID fails before a new reservation, at the
pre-send callback, and before result admission. The executing provider object is
captured for the whole operation; a result cannot silently switch adapters.
Binding is operator configuration, NOT proof of the credential's actual account.
Private Python mutation, malicious adapter code and untrusted processes are not
contained by readonly properties. That requires isolation and actual tenancy
verification, still outside this component.

Compatibility: constructor/execute arguments and storage version2 are unchanged;
no data migration or counter reset occurs. Existing simple trusted provider
adapters retain the old pre-call behavior if they have no checked method. They
do NOT gain a final post-credential check merely by being registered. A malformed
checked method is rejected. The bare `ResponsesProvider.generate` transport API
is retained for trusted direct users/wire tests; only the gateway's checked path
has this additional live admission guarantee. It is not public authenticated
consent and must not be exposed as authorization from client JSON.

Stop/drain old workers when rolling out this code fix; the unchanged database
marker cannot fence old binaries. A cancellation AFTER the last check cannot
atomically retract bytes from a subsequent socket send under arbitrary scheduler
delay. Likewise a cancellation after sending suppresses delivery but does not
prove remote termination, deletion, or refunded cost. Do not turn this local
race repair into a claim of atomic cross-system revocation or production privacy
qualification. Existing store=false and no-tools/retry/redirect policy is unchanged.

Run `services.model_gateway.test_model_send_admission` together with all three
existing model suites. Regressions exercise real SQLite, cross-connection revoke,
expiry/claim/configuration changes, transaction-exit boundaries, conservative
recovery and local socketpair HTTP emission/parsing. Socketpair tests are not TLS
or live tenancy tests. The fixed-file source declaration changes only the hash
of the reviewed transport bytes; no marker slot, scan root or exception expands.

Technical reference: Python 3.13 http.client documentation (connect/request and
connection cleanup), checked 2026-09-05:
https://docs.python.org/3.13/library/http.client.html
