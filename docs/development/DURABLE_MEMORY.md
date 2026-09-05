# Durable Memory encrypted persistence and deletion custody

Status: HG-0087 Memory source increment; aggregate remains **OPEN**. Owner: privacy.
Implementation: `services/skills/durable_memory.py` and
`services/skills/durable_memory_schema.py`.
Regression: `services/skills/test_durable_memory.py`,
`services/skills/test_durable_memory_schema.py`, and
`services/skills/test_durable_memory_component_identity.py`.
Contract: `contracts/durable-memory-v1.json`. Complete-table-loss detection is
specified in `docs/development/MEMORY_COMPONENT_IDENTITY.md`.

## Responsibility and trust boundary

`DurableMemoryStore` is a SQLite custody layer for consent-scoped Memory records. It persists ciphertext, metadata, consent and deletion-propagation tombstones. It does **not** persist plaintext values or cryptographic key material. Actual authenticated encryption and per-subject key custody are supplied by the deployment through the `MemoryCipher` interface.

The cipher must provide a current key identifier for each subject and authenticated `encrypt`/`decrypt` operations bound to subject, key ID and AAD. The repository test cipher is deliberately a fixture and is not a production cryptographic implementation, KMS, HSM or mobile keystore.

The AAD binds memory ID, subject, purpose, data class, creation time and expiry. Metadata tampering therefore fails decryption instead of silently reassigning ciphertext. The stored SHA-256 value digest is an additional corruption check, not a password hash or authentication primitive.

## State and concurrency

SQLite runs WAL with `synchronous=FULL`, `temp_store=MEMORY` and `secure_delete=ON`. Mutating operations use `BEGIN IMMEDIATE` under the process lock. Consent updates, writes, revocations, expirations, key rotation and deletion-tombstone creation therefore commit atomically within this database.

A write requires current consent, an allowed data class, capacity and a current per-subject key ID before ciphertext can be inserted. Narrowing consent deletes disallowed records. Shortening consent re-encrypts retained records because expiry is part of their authenticated metadata. Expired records are removed before normal reads/writes and create durable deletion tombstones.

The reference in-memory `MemoryStore` remains available for development compatibility; there is no automatic migration from its volatile process state. Production callers must deliberately compose the durable store and an approved key provider.

## Current-time admission and delivery

Consent and record freshness are sampled only after the SQLite write lock has been acquired. A request that waited behind another connection cannot use a time captured before that wait. Granting consent also checks its absolute expiry again after any record deletion/re-encryption work; if the consent expired or the operation clock moved backwards, the whole transaction rolls back.

`remember` checks current time after lock acquisition, after external key/encryption work and after the record insert immediately before transaction completion. Expiry or an operation-local clock rollback rolls back the ciphertext row. This closes the reproduced case where a caller sampled time 100, waited behind another database writer until time 201, and inserted under consent that expired at 200.

`search` and `export` recheck time after decryption. Records that expire while key service work is running are purged with the normal deletion tombstone and are not returned. These are best-effort final local checks; scheduler preemption immediately after the final sample is not an atomic clock-and-delivery guarantee. The component does not supply a trusted global clock or whole-database anti-rollback anchor.

Delete, purpose revoke and subject delete sample their deletion timestamp after acquiring the write lock. A clock failure can still prevent creation of an accurately timestamped deletion tombstone; an emergency deletion service with separately persisted last-trusted time is not implemented here.

## Established-schema integrity

A fresh database creates the four authority tables, schema row and the fixed SQLite `application_id` component marker atomically. An established version-1 database must contain the exact schema singleton and all four tables: `memory_schema`, `memory_consents`, `memory_records` and `memory_deletions`. Missing authority tables, a missing marker row, incompatible columns, an unknown version or loss of deletion-event uniqueness fail startup. The constructor closes its connection on failure and never recreates missing authority state as empty.

An intact predecessor database whose application ID is zero adopts the marker only after the complete schema validates, without rewriting custody rows. A conflicting nonzero ID is rejected. The marker survives normal `VACUUM`, so deleting all four Memory tables cannot turn a marked database into a fresh component. `sqlite_sequence` residue also catches complete loss of a legacy pre-marker database unless the whole file/header is deliberately replaced. Derived lookup indexes contain no authority facts and may be rebuilt from intact tables.

The layout version remains 1 because no stored data row or column is added. This is a stricter reader and component-identity contract, not a record migration. Stop all old binaries before rollout: a running predecessor lacks these checks. The marker is not cryptographic or externally monotonic; a privileged writer or stale whole-file restore remains outside the source guarantee. Do not remove the marker, repair lost tables with empty copies, or restore an older snapshot. Production backup integrity and anti-rollback remain open requirements.

## Key rotation

`rotate_subject_key(subject)` obtains the deployment's current key ID inside the write transaction, decrypts records using their recorded older key IDs, and re-encrypts them with the current key while preserving record identity, consent and expiry. Failure rolls back the database transaction. Old keys must remain available to the key provider until all records using them have been rotated or deleted.

The database never stores raw keys. This source does not implement KMS policy, HSM attestation, key escrow, key destruction evidence or compromised-key response.

## Deletion and propagation custody

Local delete, purpose revocation, subject deletion, expiry and consent narrowing remove ciphertext and create `memory_deletions` tombstones in the same transaction. `pending_deletions(after_seq, limit)` is cursor-paginated and survives restart. An external propagation worker may acknowledge a tombstone only after it has authoritative downstream deletion evidence.

`acknowledge_deletion` marks local propagation custody completed; it does **not** itself prove that another device, provider, replica or backup deleted data. The source intentionally exposes `deletion_ack_is_external_fact=true` in `storage_policy()` to prevent local state from being presented as independent deletion evidence.

## Backup and storage boundary

`secure_delete=ON` reduces ordinary SQLite page reuse exposure, but WAL files, filesystem snapshots, host backups, replicas and storage-controller copies remain outside this component's authority. `storage_policy()` therefore declares external backup exclusion as required. Production deployment must enforce and test backup exclusion/retention separately.

Do not copy the SQLite database into general-purpose backups until the approved encrypted-backup and deletion-propagation policy exists. Do not log values, ciphertext, keys or decrypted exports. Subject authentication is still an ingress responsibility outside this library.

## Verification

Run:

```bash
python3 -m unittest services.skills.test_durable_memory \
  services.skills.test_durable_memory_schema \
  services.skills.test_durable_memory_component_identity -v
python3 -m unittest services.skills.test_memory \
  services.skills.test_memory_boundaries -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
```

The deterministic tests cover plaintext absence after checkpoint, restart recovery, authenticated metadata tampering, key rotation, unavailable keys, consent narrowing, expiry, paginated deletion custody, concurrent revoke/write serialization, partial and complete schema loss, component marker adoption/conflict, lock-wait freshness, final write/read expiry, clock rollback and constructor lock release.

These tests use a non-production fixture cipher. They do not establish KMS/HSM strength, filesystem full-disk encryption, backup deletion, multi-device propagation, production privacy review or independent acceptance.

## Remaining HG-0087 Memory work

Memory remains OPEN until the durable store is integrated behind authenticated product ingress with a real per-subject key service, approved backup exclusion/encrypted backup, downstream deletion propagation and reconciliation, retention/export policy, migration from any deployed predecessor, operational recovery and independently witnessed deployment/privacy evidence.
