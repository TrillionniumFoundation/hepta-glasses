# Signed Skill registry state continuity and offline migration

Status: incremental HG-0087/skills source hardening; Skills and aggregate
HG-0087 remain **OPEN**. Owner: skills. Implementation:
`services/skills/signed_registry_schema.py` and
`services/skills/signed_registry.py`. Regression:
`services/skills/test_signed_registry_schema.py` and
`services/qualification/test_signed_registry_object_binding.py`. Contract:
`contracts/signed-skill-package-v1.json`. Operations:
`docs/operations/SIGNED_SKILL_STATE_RUNBOOK.md`.

## Responsibility and threat boundary

The existing schema checks reject missing authority tables, but a complete older
copy can still have a valid schema. An already-open predecessor can also modify
the five authority tables after migration, and a configured pathname can be
replaced while the process still holds the original SQLite connection.

This increment adds local continuity custody and an optional host-retained lower
bound. It detects unsynchronised authority-row changes, a different database
instance, a revision below an anchor, a same-revision fork, malformed continuity
state and replacement of the configured pathname while the registry is open.
It also machine-enforces effective-UID ownership and exclusive mode-bit write
custody for the final parent directory and primary database file. It does **not**
terminate an old process, operate a remote monotonic counter, inspect POSIX ACLs
or Linux capabilities, protect against a privileged actor rewriting both
authority and continuity state, or prove that a restored backup is the newest
valid copy.

## Object-bound SQLite open

Path checks performed only after `sqlite3.connect(path)` have a constructor race:
the connection can retain file A while a later path lookup observes replacement
file B. Checking B before every transaction then says nothing about the SQLite
handle still attached to A. The offline migration had the same gap and could be
redirected by pathname substitution or an A→B→A sequence.

The registry now walks the local parent directory with held directory descriptors
and `O_NOFOLLOW`, opens the final database as one regular file object, and retains
both the parent-directory and file descriptors until the SQLite connection is
closed. SQLite is opened through `/proc/self/fd/<held-fd>`, so the connection is
bound to the inspected object rather than resolving the caller pathname again.
The first post-connect device/inode and ctime check runs before any PRAGMA or
schema write. Initial parent-directory ctime is also checked, making a pathname
ABA during the open interval fail closed.

Each transaction checks that the held descriptor, the entry reached through the
held parent-directory descriptor and the absolute configured pathname still name
the same regular non-symlink inode. Descriptor release is coupled to registry
close and constructor failure. This is a Linux trusted-host contract; absence of
`O_NOFOLLOW`, `/proc/self/fd` or an effective-UID API fails closed rather than
falling back to an unbound pathname connection.

### Effective-UID and mode-bit write custody

Object identity alone does not prove that another local account or group cannot
modify the path. Before SQLite performs any PRAGMA or schema write, the final
parent and database file must be owned by the process effective uid. Owner read
and write bits are required; the final parent also requires owner search. Group
and world write bits are rejected. The same properties are re-read from the held
objects and from the named parent-relative/absolute objects around every authority
transaction and during explicit migration. Permission drift therefore returns
`skill_registry_database_permissions_invalid` before authority use.

The implementation does not call `chmod`, change ownership or silently repair an
insecure deployment. Read/execute visibility beyond the required owner bits is a
separate confidentiality policy. POSIX ACL entries, Linux capabilities, mount or
network-filesystem trust and permissions of ancestor directories are not proven
by these mode-bit checks; operators must qualify them independently. A hostile
kernel or privileged root can still defeat this local source boundary.

The held object eliminates permanent constructor/migration misbinding. It does
not make SQLite commit and a concurrently changing directory entry one atomic
cross-kernel operation. A replacement after the last pre-commit check can still
leave a change committed to the held, now-detached inode before the post-commit
check returns an error. Preserve both objects and handle that as a storage
incident; the operation never reports success after observing replacement.

## State and authority digest

The primary record component remains `signed_skills`, version 1. A separate
component marker `signed_skills_state`, version 1, identifies the additive
continuity layer. `signed_skill_state` contains exactly one checked row:

| Field | Meaning |
|---|---|
| `instance_id` | Random 256-bit identifier created once for this database instance |
| `revision` | Positive local revision, increased only when authority bytes change |
| `authority_digest` | Domain-separated streaming SHA-256 over all five authority tables and the event AUTOINCREMENT value |

The digest covers persisted policy, publisher-key bindings, installed manifest
and signature custody, consent expiry, revocations, the complete audit chain and
its sequence. Values have explicit type and length framing and fixed SQL ordering.
The continuity row itself is excluded to avoid recursion.

Every registry operation using the current implementation:

1. verifies that the held object and configured path still identify the same
   regular non-symlink database with effective-UID/exclusive-write custody;
2. obtains `BEGIN IMMEDIATE` and checks both component markers and exact schema;
3. recomputes and compares the authority digest before reading authority;
4. evaluates policy, time, consent, dependency and revocation rules;
5. performs the local mutation; and
6. recomputes the digest and compare-and-updates revision/digest in the same
   transaction before returning success.

A no-op leaves the revision unchanged. If sealing fails, the authority mutation
rolls back. A predecessor write that does not update the continuity row makes the
next current-version operation fail `skill_registry_state_integrity_invalid`.
Established startup and explicit checkpoint verification also run SQLite
`quick_check`, foreign-key checks and semantic validation of policy, keys,
installed records, revocations, event ordering/hash linkage and event sequence.

## Optional host anchor

`RegistryStateAnchor(instance_id, revision, authority_digest)` is a frozen exact
checkpoint supplied by trusted host composition. It is not accepted from package
or client JSON. On startup and each operation:

- a different instance is rejected;
- a database revision below the anchor is rejected as rollback;
- the same revision with a different digest is rejected as a fork; and
- a higher revision under the same instance is accepted as later **local** state.

When an anchor is supplied, a missing or fresh database is never initialized.
`state_checkpoint()` returns immutable local metadata and always reports
`external_evidence=false`. The deployment may retain that checkpoint in a real
TPM/KMS/remote monotonic service and supply it on the next open. Keeping the
checkpoint beside the database does not provide independent anti-rollback.
A higher local revision is not proof of every intermediate state; a privileged
actor could rewrite both data and continuity metadata.

## Explicit offline migration

A five-table predecessor has `signed_skills=1` but no continuity marker. Normal
startup returns `skill_registry_state_migration_required`; it never adds state
implicitly.

`migrate_signed_skills_v1(path)` is operator-only and offline. It uses the same
held no-follow parent/file descriptors, effective-UID/exclusive-write checks and
object-bound SQLite connection as normal startup. It requires an existing regular
local file in WAL mode, the exact legacy marker and exact five-table schema, no
prior continuity marker, SQLite integrity, canonical policy/key/install/
revocation/event semantics and stable object/path identity. Under one
`BEGIN IMMEDIATE` transaction it records row counts, adds the singleton, computes
revision 1, adds the continuity marker and commits. No legacy row, timestamp,
signature, consent expiry, revocation or event is rewritten. Any failure rolls
back both new table and marker. Repeated, partial, unknown-version, symlink,
insecure-permission, replacement and open-interval ABA migrations are rejected.

Stop and drain **every** old process and mutation ingress before migration. A
reopened old binary rejects the additional namespaced table, but a process that
already holds a connection is not terminated by a marker. Tests demonstrate that
such a process can still write and that current code detects the mismatch later.
Detection is not mutual exclusion and does not qualify a mixed-version rollout.

## Backup and recovery

Before backup, quiesce writers, call `state_checkpoint()`, retain the database,
WAL and SHM consistently and publish the checkpoint to the deployment's
independently controlled anchor. Before restored state serves any install,
resolve or execution path, reopen it with that anchor. Keep ingress closed on
instance mismatch, rollback, same-revision fork, digest mismatch, object/path
replacement, permission failure or SQLite integrity failure.

An unanchored, internally consistent old backup may pass local checks. Deleting a
WAL, lowering either marker, resetting revision/digest or creating an empty
registry is not recovery. If installs, revocations and audit history cannot be
reconstructed authoritatively, Skill execution remains disabled.

## Verification and evidence ceiling

The test suite uses real SQLite and covers fresh state, no-op revisions, direct
row tampering, anchored rollback/fork detection, missing-database anchors, live
path replacement, state-seal rollback, explicit migration preservation and
rollback, an already-open legacy writer, missing markers, symlinks and sanitized
clock failures. Dedicated object-binding tests replace the pathname after the
SQLite handle is returned but before constructor identity capture, exercise a
migration A→B→A open-interval ABA, verify no wrong object is initialized or
migrated, confirm held descriptors close with the registry, and reject insecure
parent/file modes, effective-UID mismatch, permission drift and insecure legacy
migration input. Existing Ed25519/package/Transparency tests remain required.

These tests establish deterministic local behavior only. They do not prove
production process quiescence, POSIX ACL/capability or mount policy, a real
TPM/KMS anchor, backup operator correctness, remote replication, hostile-kernel
resistance, operated transparency, arbitrary code isolation or independent
qualification. Exact-head CI, artifact inspection and fresh independent review
remain separate gates.
