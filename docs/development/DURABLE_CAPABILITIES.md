# Durable capability intent and readback custody

Status: incremental source implementation under HG-0087; aggregate OPEN.
Owner: capabilities. Primary implementation:
`services/control_plane/durable_capabilities.py`. Contract:
`contracts/durable-capability-v1.json`. Operations:
`docs/operations/DURABLE_CAPABILITY_RUNBOOK.md`.

## Responsibility and API

`DurableCapabilityGateway` adds a concrete SQLite intent ledger to the existing
capability data contracts. It does not replace the reference `CapabilityGateway`,
install a live OAuth adapter, expose an HTTP endpoint, verify client identities,
or enable mobile mutations. Trusted service composition must authenticate the
caller and verify issuer-backed leases before constructing `DecisionLease`.
A dataclass constructed from untrusted JSON is never an authority proof.

| API | Contract |
|---|---|
| `register(spec, provider_id, adapter)` | Startup-only trusted registration; immutable mutating spec, provider namespace and field/risk digest |
| `execute(request, lease=...)` | Atomically reserve intent, consume the single-use lease and write the prepared event before provider I/O; duplicates never dispatch |
| `reconcile(request)` | Query an existing operation with the exact original request/provider binding; never dispatch a mutation |
| `revoke_subject(subject)` | Persist an irreversible local tombstone denying subsequent effect admission |
| `pending(subject, limit=100, after="")` | Return a bounded subject-scoped recovery inventory without arguments or credentials |
| `close()` | Close storage after service-owned workers have drained; not a cancellation primitive |

Adapters implement `execute(request, operation_id)` and
`readback(request, operation_id, external_id)`. The UUID operation ID is generated
and persisted before I/O; the adapter must bind it to the provider's remote
idempotency key and authoritative lookup. Register a different provider ID when
that remote namespace changes. Do not transparently fail over an unresolved
operation to another provider or tenant.

`ProviderObservation` carries operation ID, provider ID, argument digest,
disposition (`applied`, `not_applied`, `unknown`), a terminal flag and an optional
opaque external ID. The trusted adapter must validate the remote response before
constructing it. This object is neither a signature nor independent provider
evidence. A terminal `not_applied` observation means the remote operation cannot
later apply. An absent record or an eventually consistent 404 is only `unknown`.

## State and concurrency

The component uses `DurableDatabase`: a local SQLite WAL database, FULL
synchronous commits, foreign keys and `BEGIN IMMEDIATE`. Separate connections
serialize admission through the database, not just a Python lock. Network calls
are outside database transactions.

Tables contain operation metadata, consumed lease hashes, subject revocation
tombstones and ordered audit events. Admission inserts all three operation/lease/
prepared-event records in one transaction. The intent state `dispatching` means
reserved, not proof that a packet reached the provider. A unique operation key
hashes subject plus idempotency key. Its fingerprint binds request, task, device,
action, argument digest, origin, confirmation, deadline and provider/spec digest.
Changing those fields under an existing key raises `idempotency_conflict`.
Globally unique lease IDs are consumed at most once across connections and
restart. Denials are retained but do not consume a valid lease.

| Stored state | Meaning and permitted continuation |
|---|---|
| `denied` | Admission failed; replay only, no effect |
| `dispatching` | Prepared intent; effect might occur or might already have occurred; duplicates return indeterminate |
| `indeterminate` | No valid terminal observation; bounded readback only |
| `succeeded` | Bound terminal applied observation; replay only |
| `failed` | No dispatch started, authority expired before admission, or bound terminal not-applied observation; replay only |

Immediately before provider execution, admission rechecks current revocation,
request/lease expiration and the monotonic caller budget. Revocation committed
after network admission cannot prove cancellation of an already accepted remote
effect. Historical success is not erased by revocation.

Conflicting bound terminal observations from concurrent work quarantine the
operation as `indeterminate/provider_terminal_conflict`. Ordinary readback then
raises `capability_receipt_conflict`. Already admitted late observations cannot
clear that quarantine. The runner never creates a fresh effect to repair it.

## Failure and recovery

Process exit after reservation leaves durable uncertain custody, including when
I/O had not begun. Retrying `execute` on the same key returns its receipt and does
not call the adapter. Recovery only uses `reconcile` with the exact original
request. It can operate after the original effect deadline or revocation because
it reads rather than mutates; the service must still authenticate and authorize
the recovery caller. The durable readback counter increments before I/O, so a
crash or timeout consumes the attempt budget instead of restoring it.

Provider exceptions, invalid binding, malformed observations and nonterminal
results stay indeterminate. Raw exception text and full provider payloads are
never stored. If a terminal database write fails, the earlier reservation remains
and the caller must treat the outcome as uncertain. Timed-out threads retain a
bounded worker permit until they actually exit; Python thread timeout is not
remote cancellation. Production adapters need socket deadlines, cooperative
cancellation/readback and process or service isolation.

## Configuration and migration

Defaults: 10 seconds provider caller wait, 4 active workers, 4096 operations and
8 readback attempts per operation. Wait must be finite and in (0, 60]; operation
capacity is 1..1000000 and readback capacity is 1..32. The inventory page limit is
1..100. Payload JSON is limited to 65536 UTF-8 bytes, identifiers to 256 characters
and provider/field identifiers to 128. Non-string JSON keys, nonfinite numbers,
invalid clocks, reusable leases and R4 actions fail closed; R3 requires verified
biometric confirmation. Database lock waiting has its separate 5-second timeout;
the provider wait is not a hard end-to-end service latency guarantee.

Schema version is component `durable_capabilities`, version 1. A different version
or preexisting unmarked component tables is rejected. There is no destructive
migration, lease reset, revocation reset or automatic receipt eviction. Capacity
exhaustion rejects new work. Production retention/compaction must retain durable
anti-replay and revocation facts; deleting this database to free space is unsafe.

Storage is trusted operator-owned local disk. Do not deploy this SQLite contract
on a network filesystem or claim multi-region replication. Do not restore stale
snapshots: that can resurrect consumed leases, forgotten effects and revoked
subjects. An externally anchored anti-rollback/recovery service is not implemented
by this component and remains a deployment/source integration requirement.

## Privacy and evidence boundary

Only hashes, provider/operation identifiers, safe reason codes, counters and
sequences are persisted. No arguments, raw transcripts, OAuth credentials or
unfiltered results are written. Opaque external IDs must not embed personal
content. Hashing low-entropy identifiers is not anonymization, and the database
is not encrypted by this component.

This is an intent metadata ledger, not an encrypted full-payload outbox. Recovery
requires the authorized original request from the caller or a separately designed
encrypted payload vault. OAuth lifecycle, key management, encrypted payload
custody, identity ingress, cross-service revocation, live provider receipts and
witnessed deployment recovery remain open. `retry_safe` is always false: no
receipt is permission to create a new effect without a new decision.

## Operations and verification

Run `python3 -m unittest services.control_plane.test_durable_capabilities -v`.
The suite uses real SQLite, separate connections, races, restart and two actual
subprocess exits: after reservation and after a fsynced fixture-effect marker
before receipt commit. Fixtures model provider behavior; they are not live
provider evidence. Check the runbook before operation, backup or recovery.

Machine and human handoff status now agree on the durable identity/realtime/
capability source scope. Handoff checks validate structure and exact status
agreement, not semantic completeness of all engineering dimensions. Source tests,
CI artifacts and documentation cannot grant independent review, deployment or
E5-E7 product qualification.

## Concrete Calendar adapter and final pre-POST revalidation

`services/control_plane/google_calendar.py` implements a narrow owned-calendar
create/get route. See `docs/development/GOOGLE_CALENDAR_CAPABILITY.md`, its
operations runbook and `contracts/google-calendar-capability-v1.json`. The trusted
registration now rejects mismatched adapter-declared provider_id/capability_spec.
An optional execute_authorized hook receives a live gateway callback to recheck
operation state, subject revocation, request/consumed-lease expiry and the caller
budget after credential acquisition/TLS, before the concrete provider mutation.
Legacy adapters retain their old path and do not acquire this guarantee implicitly.

The Calendar adapter rejects direct legacy execute, sends at most one POST, and
uses only GET for uncertain recovery. No 404/409 or mutable private property proves
terminal non-application. It requires an external authenticated OAuth vault, not
client-constructed access grants. Neither the hook nor the concrete transport
implements encrypted payload storage, production identity or independent acceptance.
HG-0087 remains OPEN; successful historical effects are not erased by later revoke.

## Complete-schema admission and Calendar response integrity

An existing `durable_capabilities` version-1 marker is not permission to recreate
missing operation, lease, revocation or event tables. Startup checks all four
required tables before schema creation and rejects an incomplete component as
`capability_schema_integrity_invalid`. Rejected construction closes its connection
and leaves existing records and the marker unchanged. This prevents accidental
loss of a revocation table from being silently treated as an empty authority
store. It does not detect a privileged writer deleting individual rows or
restoring an entire old snapshot; backup anti-rollback remains open.

Regression: `services/control_plane/test_capability_schema_integrity.py`.
The Calendar reader additionally rejects `attendeesOmitted` and open self-
invitation responses, and rejects malformed timezone offset minutes rather than
allowing the datetime parser to normalize them. These checks preserve uncertain
results instead of treating incomplete provider views as exact effects.
