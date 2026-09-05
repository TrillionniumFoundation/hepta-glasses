# Realtime activation admission, current time and cleanup custody

Status: HG-0087/realtime source increment; aggregate remains OPEN. Owner: cloud.
Implementation: `services/control_plane/durable_realtime.py`.
API supplement: `contracts/realtime-admission-v1.json`.
Operations: `docs/operations/REALTIME_ADMISSION_RUNBOOK.md`.
The previous realtime custody design still describes subject/generation binding;
this document supersedes its caller-supplied `now` examples and implicit legacy
schema adoption. No speech implementation or consumer effect authority changes.

## Responsibility and API

`DurableRealtimeStore` issues one-use admission tickets, reserves one activation
attempt, records a matching provider result and retains cleanup when admission
has been revoked or has expired. It is a trusted-host library, not a public
identity endpoint, speech provider, TLS adapter or service deployment.

Construction now REQUIRES `clock: Callable[[], int]`. The host must supply a
trusted current Unix-seconds clock, for example a service-owned time source;
it must not be selected by an HTTP body or frozen to the request arrival time.
The per-call `now` argument is removed from `issue_ticket` and `activate`.
Legacy callers fail visibly instead of silently overriding current authority.

| Method | Contract |
|---|---|
| `issue_ticket(subject, session_id)` | Sample host time after the write lock, set an absolute expiry and recheck before returning the committed ticket |
| `activate(ticket, subject, session_id, timeout_seconds=10)` | Consume one ticket and persist its attempt before provider work; recheck current state/expiry after worker scheduling and before final activation |
| `reconcile(session_id, timeout_seconds=5)` | Read back an unresolved attempt; never activate again at the provider. Expired admission becomes cleanup-only |
| `interrupt(session_id, generation)` | Existing generation fencing for an already-active session; not a new activation ticket |
| `require_generation(session_id, generation)` | Check local active generation, not independent user authentication or a device-effect lease |
| `revoke(session_id, timeout_seconds=5)` | Commit local terminal revocation and cleanup intent before trying remote cleanup |
| `drain_revocations(limit=20, timeout_seconds=5)` | Process a bounded page under one shared caller budget; return the number of pending jobs |
| `pending_recovery(limit=100)` | Bounded local inventory, not an automatic background worker |

A ticket deadline authorizes completion of INITIAL activation, including an
uncertain attempt recovered later. It is NOT the maximum lifetime of a session
already activated in time. Such a session stays active until its separate
revocation/generation policy denies it. Production identity-backed session
lifetimes, credential expiry and live revocation consumers remain unfinished.
Do not claim session-lifetime enforcement from this admission fix.

## Reproduced source defects

The parent implementation accepted `now` from each call, checked it once before
provider work and did not carry its ticket expiry into the result transaction.
With an actual parent-code SQLite database, a ticket expiring at 1001 and a
provider fixture returning at host time 1002 still produced `state=active`.
An unresolved attempt could likewise be restored long after admission expiry.

The predecessor also reused a full timeout for lookup and cleanup, and for every
item in a cleanup batch. The new caller budget is a monotonic absolute deadline
shared by successive stages. SQLite lock waiting retains its separate engine
bound; these application checks are not a hard realtime scheduler guarantee.

## State, concurrency and final admission

SQLite WAL/FULL and `BEGIN IMMEDIATE` serialize the ticket/session/attempt
transaction across local connections. Issuance and consumption resample time
after acquiring the write lock. Issuance checks timestamp range, and a ticket
that expires during that transaction is not returned as usable. Consumption
checks again before commit; failure there rolls back the attempt and ticket
consumption because no provider dispatch has occurred.

Provider activation runs outside the write transaction in the existing bounded
worker pool. Immediately before that call, a transaction rechecks session state,
exact attempt ID, subject, generation, the existing consumed-ticket expiry and
the original monotonic caller budget. A queued worker cannot carry an obsolete
check into a new dispatch. The provider receives only the remaining budget,
clamped to the remaining ticket lifetime; it must honor that bound itself.

The result transaction requires exactly one consumed ticket bound to the same
subject/session. It uses the persisted expiry, never the current constructor TTL
or a newly generated recovery deadline. It checks time before recording active
state and again after that update, immediately before transaction exit. Clock
rollback observed within this operation, invalid clock results, ambiguous or
missing consumed-ticket custody, and expiry cannot promote an initial activation.
These checks do not detect a malicious clock or whole-database rollback.

If a valid provider session is found after admission expires, the transaction
records local revocation, advances its generation and queues the known remote
session for cleanup. A previously queued lookup is completed only after custody
has transferred to that known-session job. The error is raised AFTER this
transaction commits; raising inside it would roll back both denial and cleanup.
If remote cleanup cannot complete, the job survives for later operator draining.

Expiry observed before a recovery lookup similarly commits local revocation and
a lookup cleanup job. A provider lookup returning no record remains unknown;
it is not proof of non-execution or successful deletion. Recovery may discover
and clean a remote session, but may never reactivate expired local authority.
Already-revoked sessions stay revoked even when old workers return late.

A caller timeout while the ticket itself is still valid leaves the attempt
indeterminate. A fresh readback can resolve that same attempt within its original
admission lifetime; it cannot submit another activation or extend the ticket.
Only the caller commits a result; a timed-out provider thread cannot later
activate a session by itself. A known result that loses the final caller budget
is not returned as success. Application checks are best-effort last checks, not
atomic clock-and-remote-effect operations under arbitrary scheduler preemption.

## Failure and recovery

| Situation | Durable result | Continuation |
|---|---|---|
| Expired ticket before reservation | No ticket consumption or provider work | No activation under that expired ticket |
| Expiry while reserving | Transaction rolls back; no provider work | Inspect current authority; do not fake time |
| Revoke/expiry after reservation but before dispatch | No new provider call; deny or retain uncertain cleanup | Readback only where remote state is unknown |
| Provider returns after expiry | Revoked locally; known cleanup job committed | Drain cleanup, never restore active |
| Provider timeout before ticket expiry | Indeterminate exact attempt | Readback within the original admission deadline |
| Readback after ticket expiry | Revoked; lookup/known cleanup retained | Cleanup-only, including after restart |
| Cleanup unavailable or caller budget consumed | Pending cleanup persists | Operator retry of idempotent cleanup only |
| Database write/commit failure | No success acknowledgement | Preserve database; inspect recovery inventory |
| Invalid clock during initial result admission | No active authority; remote cleanup retained | Restore trusted clock, preserve denial |

The provider remains trusted code responsible for genuine session identity,
idempotent revocation and authoritative lookup. A fixture response or Python
`RealtimeActivation` object is not a provider signature. This increment does not
add a real provider exchange, isolate arbitrary worker code, encrypt the database,
verify platform attestation or construct independent cancellation evidence.

## Configuration, compatibility and resource limits

Storage layout and marker remain `realtime` version 2. Intact marked v2 databases
reopen WITHOUT row rewriting, and their existing ticket deadlines are preserved.
New startup rejects an incomplete marked schema and rejects unmarked existing
component tables. It does not recreate a missing revoke outbox, fabricate attempt
IDs or automatically reinterpret pre-marker state. Fresh empty databases can be
initialized. Unknown versions fail the existing version check.

This is a source API upgrade, not an automatic schema migration. Update callers
to inject the trusted clock, remove per-call `now`, stop/drain old application
processes, and deploy only the new code. Since the storage marker is unchanged,
it does NOT fence old binaries. Mixed-version operation or binary downgrade can
restore the old unsafe admission path and is not supported by the deployment
contract. There is no claim of production migration or rolling-upgrade safety.

Ticket TTL is 1..300 seconds, default 60; records are limited to 1..1000000,
default 100000; workers are 1..16, default 4. Caller budgets are finite in (0,60]
seconds. Cleanup batch limits remain 1..100. The worker count is per store, not a
global deployment quota. A hung thread retains its permit until actual exit;
process isolation and bounded deployment replicas remain operational obligations.
No plaintext ticket is persisted; provider identifiers and subject metadata still
need access control, retention and operational encryption. Do not log ticket
bytes, credentials, raw audio or transcript payloads.

## Operations, verification and evidence boundary

Run `services.control_plane.test_durable_realtime`, `test_realtime_custody` and
`test_realtime_admission` with unittest. The tests retain all fifteen prior
custody assertions with explicit test-clock injection and add real SQLite,
lock races, final-transaction boundary triggers, process-exit and cleanup tests.
They use inert local providers, not live model/speech services or physical devices.
Run full repository ownership/handoff checks and all seven canonical jobs on the
final head before accepting source integration; independent review is separate.

HG-0087/realtime remains OPEN. Missing work includes live provider composition,
authenticated ingress, provider/tenant binding, production session lifetime and
revocation delivery, retention, bounded operational recovery, observability,
real remote cleanup evidence and independently witnessed deployment. No prior
identity/speech/Memory/executor patch is included or retried by this increment.

Primary engine references checked 2026-09-05:
https://www.sqlite.org/lang_transaction.html
https://docs.python.org/3.12/library/time.html#time.monotonic
