# Durable capability operating and recovery runbook

Scope: `DurableCapabilityGateway` source component on trusted local SQLite.
Design: `docs/development/DURABLE_CAPABILITIES.md`.
Contract: `contracts/durable-capability-v1.json`.
HG-0087 remains OPEN; this runbook is not a deployed provider acceptance record.

## Deployment preconditions

Use an operator-owned private directory on local storage, a least-privileged
service account, and encrypted storage controlled outside this component. Keep
SQLite database/WAL/SHM files together under that policy. Validate WAL and FULL
synchronous mode at startup; construction refuses an unsupported configuration.
Set process umask 077 before opening the database. Do not share this directory
with an untrusted user, place it on a network filesystem or expose it directly
through an API. The database primitive is not a hostile-filesystem boundary.

Do not enable this runner in consumer ingress until authenticated identity,
issuer-backed single-use leases, provider OAuth vault access, bounded network
transport and authoritative readback are implemented and qualified. Startup
registration is trusted code, not a plugin-supplied configuration capability.
A provider ID must include its actual tenant/idempotency namespace version.

Choose capacity and readback budgets before service startup. Alert on operation
count, indeterminate count, quarantined conflict count, exhausted readbacks,
worker saturation, database errors and revocation delivery failures. Do not log
arguments, tokens, raw responses or private exception messages. Export aggregate
counters; this library does not install a production metrics service.

## Recovery without duplicate effects

1. Stop new mutation admission for the affected subject or service. Preserve the
   existing SQLite database and journal files; never start recovery with an empty
   database or reset consumed leases.
2. Enumerate `pending(subject, limit=100, after=...)`. Pages sort by operation ID;
   resume with the last returned ID, and rescan from the beginning after a pass
   when admissions could have occurred concurrently.
3. Obtain the exact original request from its authenticated owner or approved
   encrypted vault. The ledger intentionally does not persist raw arguments.
   Do not invent arguments or renew a deadline under the existing key; a binding
   change must fail as an idempotency conflict.
4. Call `reconcile(request)` through authenticated readback-only ingress. Preserve
   the original provider namespace and operation ID. An absent provider record
   remains unknown unless the provider guarantees terminal non-application.
5. Preserve indeterminate results when readback fails or its budget is exhausted.
   Escalate to the provider authority with safe opaque identifiers. Never call
   `execute` under a new key merely to make the uncertainty disappear.

A repeat `execute` returns the stored result without dispatch. Revocation denies
new effects but does not erase an earlier success or prevent necessary authorized
readback. Revocation is not proof that a remote request already admitted was
cancelled. The provider's actual cancellation and reconciliation protocol remains
an integration obligation.

## Quarantine and incidents

`provider_terminal_conflict` means the trusted provider/adapter contract returned
contradictory terminal facts. Stop that provider route, preserve the operation and
all independent provider records, and investigate the discrepancy. Normal
readback cannot clear quarantine. There is no administrator reset API in this
component. A documented, reviewed repair with actual provider facts is required;
never rewrite the terminal ledger directly or fabricate an acceptance receipt.

A worker timeout does not kill its thread or remote effect. Stop admitting work
when the pool is exhausted; use the adapter's independent transport/process
controls. Drain or terminate the isolated service under an incident procedure
before closing the gateway. A new process must reopen the same durable state and
use readback, never automatic effect replay.

## Storage, migration and capacity

Unknown schema versions and unmarked legacy component tables must fail startup.
Take an operator-controlled consistent snapshot only under the deployment's
approved data-protection process; a snapshot is not authority to restore older
anti-replay state. This component has no anti-rollback anchor, replicated log or
safe destructive compaction protocol. Where zero-loss recovery cannot be
established, keep mutation ingress disabled until the consumed-operation and
revocation inventories are authoritatively reconstructed.

Do not restore an older database or prune operation, lease, revocation or event
rows to bypass capacity. Near capacity, stop new work and execute a reviewed
migration preserving those bindings. Subject identifiers are hashed, not
anonymized; retention and backup permissions still apply. Full-payload encrypted
outbox, vault encryption, key rotation and deletion propagation remain separate
HG-0087 work, not properties of this metadata ledger.

## Validation and acceptance

Run the capability suite, handoff drift suite, repository/metadata/authority/
source-ownership validators, all service and adapter tests, and compile checks.
Then run every canonical mobile/native/sanitizer/source-evidence CI lane on the
same final head. Verify the downloaded artifact content and obtain an eligible
independent review. Actual provider-tenant authorization, remote idempotency,
terminal readback, cancellation, failover, backup and deletion drills require
real provider and operator evidence. Synthetic process-exit tests prove local
custody behavior only. Do not merge or publish merely because this runbook exists.
