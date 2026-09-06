# Authenticated production model ingress

Status: HG-0087/model source integration. The durable model gateway and its
fixed-endpoint provider adapter are now reachable through an authenticated,
framework-neutral ingress. Live identity/provider deployment, retention,
billing, remote cancellation/recovery, encrypted metadata and independent
acceptance remain external. Aggregate HG-0087 remains OPEN.

Implementation:

- `services/model_gateway/model_ingress.py`
- `services/model_gateway/production.py`
- `services/model_gateway/responses_provider.py`
- `lib/runtime/authenticated_service_tokens.dart`
- `lib/runtime/model_gateway.dart`

Tests:

- `services/model_gateway/test_model_ingress.py`
- `services/model_gateway/test_production.py`
- `services/model_gateway/test_model_boundaries.py`
- `services/model_gateway/test_model_send_admission.py`
- `test/runtime/authenticated_service_tokens_test.dart`
- `test/runtime/model_gateway_test.dart`

## Authority boundary

`AuthenticatedModelIngress` receives a bounded raw Authorization header and JSON
body from a trusted HTTP adapter. Its identity verifier returns a server-owned
principal containing subject, session ID, audience, scopes and absolute consent
expiry. The client cannot provide or override any of those fields.

Required audience is `hepta-model-gateway`; required scope is
`model.generate`. A malformed principal, missing/invalid bearer, wrong audience
or scope, identity exception or expired authority is denied without forwarding
identity error details. The durable backend remains responsible for its trusted
host-clock expiry rechecks before provider dispatch and result delivery.

The client body contains exactly:

```json
{
  "question": "bounded user text",
  "task_id": "stable idempotency identity",
  "context": {}
}
```

Unknown or duplicate fields, invalid UTF-8/JSON, nonfinite values, invalid task
IDs, empty/oversized questions and oversized/deep context fail before backend
work. `subject`, `session_id`, `expires_at`, provider selection, scopes and consent
flags are not legal body members.

## Durable backend binding

Ingress calls `ProductionModelGateway.execute` with:

```text
subject          <- verified principal
session_id       <- verified principal
idempotency_key  <- bounded task_id
question/context <- validated client data
expires_at       <- verified principal consent expiry
timeout_seconds  <- trusted service configuration
```

The production gateway atomically reserves subject quota and exact request
fingerprint before dispatch. Same key with changed question, context, session,
provider binding or expiry remains an idempotency conflict. Timeout or process
exit after reservation permits bounded readback only; ingress does not resubmit
the POST or convert unknown completion into retry-safe failure.

The response exposes only a bounded answer string. Provider IDs, receipts, usage,
raw errors and internal recovery metadata stay server-side. A result object must
provide a bounded `answer` (or the legacy compatible `text`) field. Unknown result
shapes fail closed.

## Mobile runtime tokens

Product builds use separate dynamic providers for model, speech and mutation
authority. The account/session component installs them only after current login,
device verification and scope issuance, and resets them on logout, session/device
revoke or attestation loss. The registry stores providers, not copied bearer
bytes. Revoking the speech token cannot silently substitute the model token.

Compiled development model or speech tokens are forbidden in product mode.
Configured product endpoints must be HTTPS. With no runtime token, the existing
mobile gateways return typed unavailable/unauthenticated failures rather than
falling back to a provider key or deterministic answer.

## Failure semantics

| Observation | Result |
|---|---|
| Missing/invalid bearer | 401; no backend call |
| Principal malformed | 401; no backend call |
| Audience/scope mismatch | 403; no backend call |
| Request shape/content invalid | 400/413; no identity or provider work where possible |
| Idempotency conflict/revoke | Stable bounded 409 |
| Quota/capacity denial | Stable bounded 429 |
| Backend/provider/storage exception | Sanitized 503 |
| Unknown result shape/oversize | Sanitized 503; no answer delivery |
| Client cancellation | Local delivery denial; remote termination is not inferred |

Only whitelisted stable backend error codes cross the ingress boundary. Raw
exception text, prompts, contexts, credentials and provider error bodies are not
reflected.

## Configuration, migration and operations

The request is bounded to 64 KiB, question to 8,000 characters, context to 32 KiB
canonical JSON and depth eight, and delivered answer to 64 KiB. Service timeout
must be finite and at most 60 seconds. These ingress bounds do not replace the
stricter durable gateway/provider bounds.

Operate the durable gateway database on trusted local storage with its recorded
provider/policy identity. Stop old binaries before schema or policy migration.
Never delete prepared/indeterminate rows, cancellation/session tombstones or
quota state to make a task retryable. A stale database restore can resurrect
authority and is prohibited until an independently anchored backup design exists.

Log only safe identifiers, state/reason codes, timings, byte counts and aggregate
usage. Do not log Authorization headers, questions, context, answers, provider
error bodies or raw provider identifiers.

## Verification and evidence ceiling

The ingress regression suite proves exact request shape, server-owned
subject/session/consent, scope/audience denial, duplicate/nonfinite JSON rejection,
context/answer bounds, exception sanitization and direct signature compatibility
with `ProductionModelGateway.execute`. Full exact-head repository CI must also
pass.

Source integration does not prove a live model tenant, KMS/attestation-backed
identity, real retention/training/residency settings, billing/abuse controls,
remote cancellation, authoritative recovery, encrypted storage, production
observability, independent review or product release. Those remain external and
provider-owned gates.
