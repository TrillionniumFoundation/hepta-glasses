# Capability revocation exhaustion and persistent suspension

Status: incremental source fix under HG-0087; not whole-product closure.
Owner: capabilities. Implementation: `services/control_plane/capability_suspension.py`
and `services/control_plane/durable_capabilities.py`. Contract:
`contracts/durable-capability-v1.json`. Regression:
`services/control_plane/test_capability_suspension.py`.

## Reproduced failure and required invariant

At predecessor 5cc2c927, fill the revocation inventory at a limit of one with
subject A. Revoking subject B raises `capability_revocation_capacity_exhausted`.
With no operation receipts yet, a valid new B operation can still dispatch and
succeed. The failure is not an unbounded retry or missing OAuth credential: the
ledger has no persistent fallback denial when it cannot record B's tombstone.

After a failed emergency revocation, no new effect may be admitted by a
current-version gateway until an authorized operator has handled the incident.
Existing tombstones must not be evicted, and storing arbitrary extra subjects
must not defeat the configured bound. A local denial never proves cancellation
of a remote effect already admitted before the last authority check.

## State and API

Storage component `durable_capabilities` advances from version 1 to version 2.
Version 2 adds one checked row in `hg_capability_control`, initially
`suspended=0, reason=active`. On revocation capacity exhaustion, the transaction
sets `suspended=1, reason=revocation_capacity`. If obtaining a valid trusted clock
for a new subject tombstone fails, it instead uses `reason=clock_unavailable`.
No time is invented and no private exception detail is stored. The transition
is one-way and the first reason is retained. There is no reset or unsuspend API.

`revoke_subject(subject)` keeps its existing successful return value (`None`)
and capacity error code. For a failed exact-subject revocation, the fallback
suspension commits BEFORE the error is raised, outside the transaction context.
Raising it inside the transaction would roll the suspension back and recreate
the vulnerability. A clock failure similarly commits suspension before raising
`capability_clock_invalid`. Repeating a denied revocation does not grow state.

`suspension_status()` returns a fresh copy of the local suspended flag and reason.
It is diagnostic state, not a signed external receipt or an operation lease.
A capacity error is not a claim that the requested subject tombstone was added:
inspect this control state to see the broader denial. Storage/commit failure
still propagates as an error and cannot be represented as a successful denial.
When storage is unavailable, the service supervisor must close its ingress;
this library cannot guarantee a durable write to unavailable media.

New requests check suspension before reserving operations or consuming leases.
Already-reserved work checks it at worker admission and, for Calendar's checked
adapter, again after grant/TLS preparation at the existing authorization callback.
Separate connections and restarted current-version processes read the same row.
Changing constructor capacity does not clear it. Missing or malformed control
state is rejected, never silently reconstructed in an established database.

Duplicate requests may still return their existing historical receipt without
performing another effect. Pending recovery inventory and authenticated readback
remain available. A successful remote effect that preceded suspension is not
rewritten as failed, and an indeterminate effect is not replayed. These rules
preserve truth about effects while preventing new mutation admission.

## Explicit offline migration, not a rolling upgrade

Normal v2 startup refuses v1 state. `migrate_capability_v1(path)` is a separate
operator-only function; it is not automatically called by service startup and
must not be exposed through unauthenticated input. The path must be an existing
regular local database, and SQLite opens it in read/write-without-create mode.
The helper requires WAL, version 1, all four predecessor tables, no existing
control table, successful SQLite quick-check and no foreign-key violation.

Under one `BEGIN IMMEDIATE` transaction it counts the existing rows for its
report, adds the singleton, advances only this component's marker, and commits.
It does not rewrite operation, lease, subject-revocation or event rows, remove
requests, expand consent, reinterpret unknown effects or reset idempotency. If
any migration write fails, the transaction is rolled back and the connection
is closed. Unknown versions, missing files/tables and a v2 database are rejected.
Calling it on a suspended v2 database cannot turn that database active again.

Before migration, stop/drain ALL old service processes and disconnect external
mutation ingress. A newly started old binary will reject version 2 through its
existing version check, but an old process with an already-open connection is
NOT retroactively stopped by a schema marker. Do not claim that an advisory
boolean or this function proves quiescence. The rollout requires actual operator
control of those processes. Reopen only new binaries after successful migration,
validate retained records and current denial state, and then assess ingress.

A privileged operator can still change rows, restore a stale whole-database
snapshot or delete the database. This component does not implement a trusted
external anti-rollback anchor, replicated recovery log, disk encryption or safe
compaction. Do not downgrade a marker, delete suspension, increase capacity to
resume, or restore an older snapshot as an incident workaround. Suspension and
retained requests require a separately reviewed recovery procedure; no automatic
resume path is provided here.

## Validation and scope

Tests use real local SQLite, separate connections, concurrent final-slot
revocations, write-trigger rollback, a real process exit, and the existing
Calendar adapter preparation callback. They cover successful/repeated exact
revocation, global denial, bounded storage, changed capacity, unavailable clocks,
old receipts, readback, missing control state and explicit migration rejection.
A separate local integration probe creates a genuine v1 database using the
hash-verified predecessor implementation and checks row preservation and old
binary rejection after migration. That probe is not a real deployment drill.

Run the new suite plus existing capability/schema/Calendar/model regressions,
repository/ownership/handoff checks and all seven canonical CI lanes on the same
final commit. No source gate is promoted solely from these targeted tests.
Identity enrollment freshness, OAuth/mobile/service integration, other production
slices, independent review, administrator policy and actual device/provider
qualification remain separate open conditions. The previously blocked identity,
speech, Memory and executor packages are unchanged by this independent fix.

Primary engine references, checked 2026-09-05:
https://www.sqlite.org/lang_transaction.html
https://www.sqlite.org/uri.html
