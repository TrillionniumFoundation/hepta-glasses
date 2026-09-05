# Realtime activation admission, current time and cleanup custody

Status: HG-0087/realtime source increment; aggregate remains OPEN. Owner: cloud.
Recovery budgets and the explicit v2-to-v3 upgrade are specified below.
Implementation: `services/control_plane/durable_realtime.py` and
`services/control_plane/realtime_recovery.py`.
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
| `pending_recovery(limit=100)` | Bounded local inventory, including exhausted pending work; not an automatic background worker |
| `recovery_status(session_id)` | Local lookup/cleanup attempt counters and exhaustion summary; never an independent cleanup receipt |

A ticket deadline authorizes completion of INITIAL activation, including an
uncertain attempt recovered later. It is NOT the maximum lifetime of a session
already activated in time. Such a session stays active until its separate
revocation/generation policy denies it. Production identity-backed session
lifetimes, credential expiry and live revocation consumers remain unfinished.
Do not claim session-lifetime enforcement from this admission fix.

## Reproduced source defects

At predecessor e2085a7b, the implementation accepted `now` from each call and
checked it once before
provider work and did not carry its ticket expiry into the result transaction.
With an actual parent-code SQLite database, a ticket expiring at 1001 and a
provider fixture returning at host time 1002 still produced `state=active`.
An unresolved attempt could likewise be restored long after admission expiry.

That predecessor also reused a full timeout for lookup and cleanup, and for every
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

Storage component `realtime` is now version 3. The four existing tables are
retained; three additional tables hold the recovery policy, one lookup counter
per session, and one revoke counter per known remote cleanup job. Fresh stores
initialize these atomically. Existing v3 stores reject missing tables, missing
policy/counters, noninteger/out-of-range counts and changed budget configuration.
Counters are created with the corresponding session/job transaction, never lazily
recreated at zero when an established record is missing.

Normal startup rejects v2. Use the separate operator-only
`migrate_realtime_v2(path, maximum_readbacks=..., maximum_revoke_attempts=...)`
after stopping/draining all old processes. The migration opens an existing
regular WAL database without create, verifies v2 and its intact tables, runs
SQLite integrity checks, adds counters/policy and advances the marker in one
transaction. It preserves every existing ticket/session/attempt/outbox row and
absolute expiry. An error rolls back the additions and version update. Missing
files, unmarked/unknown/incomplete state and already-upgraded v3 are rejected.

Both migration limits are required: migration deliberately grants a NEW bounded
post-upgrade recovery allowance for legacy work. Historical v2 recovery calls
were not counted; the report says historical usage is unknown, not zero. This
allocation is not a claim of a lifetime traffic cap over pre-v3 history, does
not renew admission, and cannot be repeated on v3 to reset counters. Old binaries
reject v3 on reopening, but already-open old processes are not retroactively
stopped. Quiesce all old processes; mixed-version deployment is not supported.

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
Also run `services.control_plane.test_realtime_recovery_budget` for persistent
budgets, queue fairness, crash reservations and offline migration.
Run full repository ownership/handoff checks and all seven canonical jobs on the
final head before accepting source integration; independent review is separate.

HG-0087/realtime remains OPEN. Missing work includes live provider composition,
authenticated ingress, provider/tenant binding, production session lifetime and
revocation delivery, retention, operator escalation and service-level retry
governance, observability,
real remote cleanup evidence and independently witnessed deployment. No prior
identity/speech/Memory/executor patch is included or retried by this increment.

Primary engine references checked 2026-09-05:
https://www.sqlite.org/lang_transaction.html
https://docs.python.org/3.12/library/time.html#time.monotonic


## Persistent recovery limits, fairness and exhaustion

At parent f22d9e02, an unknown activation was reconciled twelve times across
reopenings and caused twelve provider lookups with no durable attempt bound.
Separately, five cleanup batches of limit one repeatedly selected a failing first
job while the next pending job was never retried. These are local fixture
reproductions, not actual provider incidents.

`maximum_readbacks` and `maximum_revoke_attempts` default to 8, each configurable
from 1 through 32. Values are persisted as a fixed policy: reopening with larger
or smaller values fails rather than replenishing allowances. Every activation
lookup reserves one per-session counter unit in a write transaction BEFORE
provider I/O. Every known remote cleanup reserves one per-job unit likewise.
Separate processes serialize final-slot admission through SQLite. A crash,
worker timeout, exception, unavailable worker slot or failed result write does
not refund that committed reservation. A transaction failure before reservation
commit performs no network work. No reset/eviction API is supplied.

A lookup budget exhausted by earlier calls produces
`realtime_readback_budget_exhausted`, with no new provider call. Any expiry denial
and cleanup intent discovered while checking that session is committed before
the budget error is raised. Unavailable host time likewise cannot prevent
pending admission from becoming locally revoked and eligible for cleanup-only
lookup. Generation and original consumed-ticket deadlines are not refreshed.
Already-active local replay requires no new lookup and consumes no allowance.

A known revoke job with exhausted allowance remains `pending`; `revoke` returns
the existing pending-cleanup error, never success or evidence of deletion.
`drain_revocations` excludes exhausted pending jobs from its runnable selection
and orders runnable jobs by least reservations used, then stable job ID. Thus a
repeatedly failing first job cannot monopolize successive small batches. With
concurrent drains, each actual reservation is rechecked under the write lock;
selection snapshots do not authorize exceeding the limit. A hung call still
uses its current batch time budget and worker permit; fairness is not a realtime
scheduling or service-availability guarantee.

Lookup and known-session revocation use independent budgets. Discovery can
transfer pending responsibility from a lookup job to a known cleanup job without
replenishing the original lookup counter. Repeated local revoke calls and
re-enumeration do not reset the known job counter. Provider revoke must remain
idempotent because a timeout/crash or concurrent permitted attempt can repeat
cleanup; a finite budget is not an exactly-once remote deletion guarantee.

`pending_recovery()` includes exhausted unresolved sessions. `recovery_status`
reports lookup units used/limit, known cleanup attempt counts, and totals of
ALL cleanup jobs, pending jobs and exhausted pending jobs. Separate known/lookup
fields provide the breakdown. It always labels independent evidence false.
Exhaustion requires operator escalation with authentic provider facts, not a
fresh activation, a rewritten expiry, a removed counter or a new empty database.
This library does not install that operator workflow or a background scheduler.

The bound is per stored session/job since creation or the explicit v3 migration;
it is not a deployment-wide cost/rate cap, a guarantee that pending remote work
has stopped, encrypted storage, or an anti-rollback anchor. Trusted operators
can still defeat local state by restoring old snapshots or privileged row edits.
Production provider binding, credential/session authority, live cleanup evidence
and independent review remain open HG-0087 obligations.


## Conflicting results, remote ownership and truthful cleanup status

The current result-custody increment addresses three locally reproduced v3
source failures. A concurrently returned activation and readback could name two
different remote sessions: the loser raised an error while local authority stayed
active and neither remote identity was queued for cleanup. A revoke adapter
returning False was treated as a successful completed job. Finally, lookup-only
cleanup was present in the outbox but omitted from recovery_status pending totals.
These are local source counterexamples, not incidents observed in a live tenant.

Final admission now treats a difference from an already-recorded remote session
or receipt as a terminal local revocation. The same write transaction preserves
cleanup for both owned remote session IDs, without overwriting the historical
identity with the later answer. The exception is raised only after that transaction
commits. Each cleanup retains its original nonrefundable attempt budget. Cleanup
can proceed within the remaining caller budget or through later authorized drains;
no late observation or successful cleanup restores local active authority.

An identical result following a local generation interrupt is not a contradictory
provider observation. It returns a stale-generation error without revoking the
newer active generation. Expiry and caller timeout retain their existing distinct
meanings. A conflicting result remains a reason to deny local authority even when
there is no caller time left for immediate cleanup; the queued responsibility is
still committed. Storage failure cannot be acknowledged as a durable denial, and
the supervisor must close admission on such failures.

A remote ID already present in another local session or its cleanup custody must
not authorize deletion of that other session. The contender is locally revoked
and receives its own unresolved lookup job. Any previously owned remote ID of the
contender is queued normally, but the borrowed ID is not sent to revoke. This is
checked under the same write transaction as admission/queueing. Retained completed
cleanup and historical session identities participate in this check; an ID cannot
be silently reused under another session. Secondary indexes support these lookups
without scanning the complete retained inventories for each normal admission.

This is LOCAL ownership in the database's assumed provider namespace. It does not
supply a persistent tenant/provider configuration pin, authenticate a remote
response, or prove that a trusted adapter correctly attributed an ID. Those
production integration requirements remain open. If legacy state is ambiguous,
do not use that ambiguity as permission to revoke someone else's remote session;
keep unresolved custody and escalate. Privileged database rewriting and old
snapshot restoration remain outside the local trust boundary.

_queue_revoke validates the exact existing job binding rather than swallowing an
unrelated integrity failure. A newly unresolved lookup may become pending again,
but its spent lookup budget is never reset. Known completed cleanup is not
reclassified as a new successful call or supplied with another allowance. Explicit
revoke drains this session's pending known jobs, not only the single primary ID in
sessions. It continues to report pending when any known secondary cleanup remains.
An unknown-only local revoke retains the existing local-denial API behavior; it
is never confirmation of remote cancellation.

The trusted RealtimeProvider.revoke contract is a None return only after the
adapter has verified its successful operation. Any non-None return, including
False, True, numbers, strings and error dictionaries, stays pending and consumes
its reserved attempt. None is still an adapter claim, not an independently
verified provider receipt. A missing or rebound cleanup job cannot be reported
completed after I/O. Completion and attempt reservations remain separate durable
transactions, so a completion-write failure leaves spent budget and pending work.

recovery_status.cleanup now reports jobs, pending and exhausted_pending across
both lookup-only and known-session jobs. known_jobs/known_pending and
lookup_jobs/lookup_pending expose the breakdown. attempts remains the sum of known
revoke attempts; lookup.used reports lookup attempts. Consumers must not compare
total pending only with known-job counts or interpret zero pending as independent
provider evidence. independent_evidence remains false.

Storage stays v3, all row layouts and recovery limits are unchanged, and only
secondary indexes are added. Stop/drain old code before deploying this semantic
upgrade: the unchanged marker cannot fence an old binary on reopening. The
existing offline v2-to-v3 migration remains mandatory for a v2 database and is
not modified by this increment. No live migration, provider exchange, credential,
deployment, hard worker termination or release is performed by these tests.

Regression: services/control_plane/test_realtime_result_custody.py uses real
SQLite connections, public activation/readback races, deterministic final-method
probes, write failures and a real subprocess exit during conflict cleanup. Run it
with all prior realtime tests and the full final-head CI matrix. The known separate
identity verdict-freshness objection and all actual HG-0087 production and
independent acceptance conditions remain open.
