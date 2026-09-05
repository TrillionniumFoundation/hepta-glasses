# Durable Memory encrypted persistence and deletion custody

Status: HG-0087 Memory source increment; aggregate remains **OPEN**. Owner: privacy.
Implementation: `services/skills/durable_memory.py`.
Regression: `services/skills/test_durable_memory.py`.

## Responsibility and trust boundary

`DurableMemoryStore` is a SQLite custody layer for consent-scoped Memory records. It persists ciphertext, metadata, consent and deletion-propagation tombstones. It does **not** persist plaintext values or cryptographic key material. Actual authenticated encryption and per-subject key custody are supplied by the deployment through the `MemoryCipher` interface.

The cipher must provide a current key identifier for each subject and authenticated `encrypt`/`decrypt` operations bound to subject, key ID and AAD. The repository test cipher is deliberately a fixture and is not a production cryptographic implementation, KMS, HSM or mobile keystore.

The AAD binds memory ID, subject, purpose, data class, creation time and expiry. Metadata tampering therefore fails decryption instead of silently reassigning ciphertext. The stored SHA-256 value digest is an additional corruption check, not a password hash or authentication primitive.

## State and concurrency

SQLite runs WAL with `synchronous=FULL`, `temp_store=MEMORY` and `secure_delete=ON`. Mutating operations use `BEGIN IMMEDIATE` under the process lock. Consent updates, writes, revocations, expirations, key rotation and deletion-tombstone creation therefore commit atomically within this database.

A write requires current consent, an allowed data class, capacity and a current per-subject key ID before ciphertext can be inserted. Narrowing consent deletes disallowed records. Shortening consent re-encrypts retained records because expiry is part of their authenticated metadata. Expired records are removed before normal reads/writes and create durable deletion tombstones.

The reference in-memory `MemoryStore` remains available for development compatibility; there is no automatic migration from its volatile process state. Production callers must deliberately compose the durable store and an approved key provider.

## Key rotation

`rotate_subject_key(subject)` obtains the deployment's current key ID, decrypts records using their recorded older key IDs, and re-encrypts them with the current key while preserving record identity, consent and expiry. Failure rolls back the database transaction. Old keys must remain available to the key provider until all records using them have been rotated or deleted.

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
python3 -m unittest services.skills.test_durable_memory -v
python3 -m unittest services.skills.test_memory services.skills.test_memory_boundaries -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
```

The new deterministic tests cover plaintext absence in the SQLite database after checkpoint, restart recovery, authenticated metadata tampering failure, per-subject key rotation, unavailable keys, consent narrowing, expiry, paginated deletion custody and concurrent revoke/write serialization.

These tests use a non-production fixture cipher. They do not establish KMS/HSM strength, filesystem full-disk encryption, backup deletion, multi-device propagation, production privacy review or independent acceptance.

## Remaining HG-0087 Memory work

Memory remains OPEN until the durable store is integrated behind authenticated product ingress with a real per-subject key service, approved backup exclusion/encrypted backup, downstream deletion propagation and reconciliation, retention/export policy, migration from any deployed predecessor, operational recovery and independently witnessed deployment/privacy evidence.
