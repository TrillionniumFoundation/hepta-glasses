# HG-0087 implementation and handoff

Status: OPEN, partial source candidate. This document supplements the active
`2026-09-03_BLOCKER_EXECUTION_PLAN.md`; it does not supersede its requirements.
The initial patch implemented realtime custody repairs; a subsequent identity
increment is described in `DURABLE_IDENTITY.md` and its dedicated runbook. The speech gateway
is unchanged: its proposed repair was not published after the remote write was
blocked by the platform safety check. No source, CI or product closure is inferred.
`docs/HG0087_IMPLEMENTATION_STATUS.json` is the seven-slice implementation index.

## 1. Responsibilities and interfaces

`services/control_plane/durable_state.py` provides a local SQLite transaction
primitive. The authenticated server selects the database, owns the clock and
calls `DurableRealtimeStore`; model arguments must never construct this service.
This patch does not implement HTTP authentication, KMS, platform attestation or
mobile lease issuance. The reference `realtime.py` remains a separate component.

`services/control_plane/durable_realtime.py` owns ticket digests, immutable
subject/session binding, one activation attempt per session, generation checks,
recoverable preparation and a durable provider-cleanup outbox. The provider is an
injected `RealtimeProvider` with `activate`, `reconcile_activation` and `revoke`.
It must supply bounded network operations, stable provider identities and
idempotent revocation. A concrete production adapter is still required.

| API | Inputs | Result / failure contract |
|---|---|---|
| `issue_ticket` | subject, session_id, trusted epoch seconds | New opaque ticket; different subject or non-new session rejected |
| `activate` | exact ticket, subject, session_id, trusted time, deadline | Active SQLite row only after a fenced terminal commit |
| `reconcile` | session_id, deadline | Provider lookup, never activation replay; unresolved lookup raises indeterminate |
| `interrupt` | session_id, current generation | Atomically increments generation for an active session |
| `require_generation` | session_id, generation | Rejects inactive, stale and boolean generations |
| `revoke` | session_id, deadline | Commits terminal local revocation before provider cleanup |
| `pending_recovery` | bounded limit | Sorted identifiers requiring lookup or cleanup |
| `drain_revocations` | bounded batch and per-call deadline | Number of pending outbox rows after a bounded pass |

Existing SQLite row fields remain compatible. New callers must treat
`realtime_activation_indeterminate` as uncertain external completion, not a
retryable activation. `realtime_provider_revoke_pending` means local authority
is already revoked but external cleanup has not been proven.

## 2. State and concurrency

```text
new -> activating -> active
          |           |
          v           v
     indeterminate -> revoked
          |
          +-- authoritative lookup -> active (only while exact authority survives)
```

Any known session can be revoked. Revoked is terminal; there is no transition back
to active. New activity after revocation requires a new authorized session ID.
One live session ID has exactly one subject. New ticket issuance supersedes prior
unspent tickets without resetting session state or permitting another activation.

Every activation captures `(subject, session_id, generation, attempt_id)`. The
consumed ticket, attempt and activating state are committed in one
`BEGIN IMMEDIATE` transaction before a provider call. After the call, completion
checks the captured identity and current state in another transaction. A late
result after revocation becomes cleanup work, never restored authority.

The per-connection RLock prevents concurrent use of one SQLite connection. SQLite
write transactions serialize independent connections/processes on the same
local database. Provider calls never hold the database transaction. This is not
a multi-region replicated service or a network-filesystem database contract.

## 3. Failure, restart and reconciliation

| Window | Durable state | Required next action |
|---|---|---|
| Rejection before preparation | No consumed authority | Correct the invalid request; no remote effect was dispatched |
| Crash after preparation | activating + consumed ticket + attempt | Query provider; never call activate again |
| Timeout or provider exception | indeterminate + consumed ticket | Same authoritative lookup |
| Provider success, terminal DB failure | activating remains recoverable | Repair storage and query provider |
| Revoke while activation is in flight | revoked + lookup cleanup job | Resolve provider identity, then perform idempotent revoke |
| Provider revoke failure | revoked + pending provider cleanup | Retry cleanup without resetting local state |
| Provider lookup returns None | Still uncertain | Keep pending; None is not proof of non-execution |

`pending_recovery()` includes both activating and indeterminate sessions and
pending revoke jobs. Startup operators must scan these identifiers. No database
row automatically becomes successful merely because a process restarted.

A late provider result that can identify a revoked session is queued before
cleanup. If that cleanup fails or the process stops, its outbox row remains.
An unknown lookup cannot be cleared by editing a status string.

## 4. Configuration and limits

| Constructor field | Default | Requirement |
|---|---:|---|
| path | required | Operator-owned local persistent storage, not :memory: |
| provider | required | Authenticated production adapter; no embedded secrets |
| ticket_ttl_seconds | 60 | Integer 1 through 300 |
| maximum_records | 100000 | Positive limit; exhaustion rejects admission |
| maximum_workers | 4 | Finite worker permits per instance |
| operation timeout_seconds | 10 activation / 5 lookup or revoke | Finite positive number, at most 60 seconds |

The shared primitive checks WAL and FULL synchronous mode, enables foreign keys
and uses a five-second SQLite lock wait. Its directory is an operator-trusted
boundary; it is not protection against a hostile kernel or path replacement.
Use restrictive storage permissions and exclude authority databases from stale
mobile/cloud restore paths.

`BoundedCalls` limits caller wait and concurrent workers. It cannot kill arbitrary
Python provider code. A timed-out worker retains its permit until exit. Adapters
must additionally bound sockets and provide isolation. A drain batch has a
per-call deadline, not one total batch deadline; schedule accordingly.

## 5. Migration and compatibility

The schema marker is per component in `hepta_component_schema`, version 2.
Unknown versions fail with `schema_migration_required`; operators must not lower
the marker to force startup. For the known pre-marker realtime schema, opening
invalidates unspent old tickets and creates attempt identities for unresolved
activating/indeterminate rows. Existing active sessions are retained.

Take a consistent SQLite backup including WAL contents before migration, with
writers quiesced. Never restore a snapshot predating revocation into an active
service. Rolling back application code must not roll back authority state.
This patch does not migrate speech databases and does not change speech API calls.

## 6. Verification and operations

```bash
python3 -m unittest services.control_plane.test_durable_realtime services.control_plane.test_realtime_custody -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
```

The new suite covers independent database connections, late success/error after
revoke, subject collision, real subprocess termination after preparation,
terminal-transaction failure, persistent cleanup, bounded timeout, single use,
reissue, generation, malformed response, capacity and schema mismatch. Providers
are deterministic local fakes: these tests are E2 only.

The existing full seven-job CI remains mandatory for every published head. The
runbook is `docs/operations/HG0087_PRODUCTION_RUNTIME_RUNBOOK.md`. The module
registry maps source, tests, this guide and the composed contract. Path coverage
is not a claim that all production modules are implemented or semantically
complete.

## 7. Remaining vertical slices

Identity now has durable stores and the broker client described in section 9;
real KMS/HSM/platform-verifier services, recovery and authenticated mobile
authority integration remain unfinished. Model exchange
still needs real provider routing, cancellation, quotas, receipts and retention.
Realtime still needs an authenticated service and a concrete provider adapter.
Capabilities still need OAuth integration, durable outbox and provider readback.
Speech still needs its uncommitted correctness repairs, provider integration and
Android PCM-to-ASR. Skills still need asymmetric publisher roots, sandbox and
egress enforcement. Memory still needs encrypted persistence and deletion custody.
Each slice remains OPEN in the implementation index; the aggregate HG-0087 stays
OPEN. Mere interfaces, mocks or configured-off adapters cannot close the aggregate.

## 8. Platform and evidence boundary

This is a Python trusted-host implementation. It does not enable Android/iOS voice
or change the mobile fail-closed authority composition. External provider,
physical G1, KMS/HSM, attestation, firmware, independent assurance, signing, pilot,
rollback and store evidence remain separately issued. Administrative protection
and independent latest-head review remain mandatory. No implementing identity
self-approves, self-merges or uses a bypass.

## 9. Durable identity increment

`services/control_plane/durable_identity.py` and `identity_authority.py` now add
persistent authority state, atomic challenges, prepared signing records, current
revocation checks, actual Ed25519 verification and a bounded HTTPS broker client.
See `DURABLE_IDENTITY.md`, `../operations/IDENTITY_AUTHORITY_RUNBOOK.md` and
`contracts/identity-authority-v1.json` for exact behavior and prerequisites.
This supersedes the earlier blanket description of identity as in-memory only,
but not the remaining real KMS/platform-verifier, account recovery, mobile
integration or deployment requirements. HG-0087 stays OPEN.
