# Signed Skill registry continuity and migration runbook

Owner: skills. Design:
`docs/development/SIGNED_SKILL_STATE_CONTINUITY.md`. Contract:
`contracts/signed-skill-package-v1.json`. This runbook does not prove that a
production monotonic anchor, valid backup or old-process drain exists.

## First deployment

Use an operator-owned private local directory. Do not use a network filesystem,
publicly writable directory or symlinked database path. The runtime must provide
Linux `O_NOFOLLOW` and `/proc/self/fd`; startup fails instead of falling back to a
pathname-only SQLite connection when those primitives are unavailable.

Start with no `RegistryStateAnchor` only for an intentionally new registry.
Immediately obtain `state_checkpoint()` and store that exact
instance/revision/digest in an authenticated, independently controlled anchor
service. A JSON file beside the database is not independent anti-rollback.

The returned checkpoint deliberately says `external_evidence=false`. Do not
expose anchor construction to package or client input.

## Upgrade an existing five-table registry

This is an offline upgrade, not a rolling migration.

1. Disable package install, resolve, execution and operator-revocation ingress.
2. Stop and independently verify termination of every old service process,
   worker and recovery task that can hold the database. Source cannot attest it.
3. Preserve a consistent forensic copy of the database, WAL and SHM.
4. Run `migrate_signed_skills_v1(path)` exactly once on the actual local database.
5. Compare its preserved row counts with the pre-migration inventory. The report
   correctly leaves `old_processes_stopped_verified` and
   `external_anchor_verified` false and reports object-bound SQLite custody.
6. Open only the new binary, call `state_checkpoint()` and publish that exact
   checkpoint to the external anchor.
7. Re-enable ingress only after exact-head tests, review and deployment checks.

Migration opens the parent directory and final database with held no-follow
descriptors, then opens SQLite through `/proc/self/fd/<file-fd>`. The first
post-connect object/path/ctime check happens before any PRAGMA or migration write.
A path replacement or open-interval A→B→A sequence is a hard failure; it must not
be retried against whichever file happens to occupy the name.

A reopened old binary rejects the new namespaced table. An already-open old
process can still modify legacy tables; the next current operation detects the
stale digest, but the write has already occurred. Do not run old and new versions
concurrently.

If migration fails, keep ingress disabled. Never delete tables, lower markers,
create an empty registry or rerun against an arbitrary copy to make startup pass.
Preserve every involved inode and sidecar when replacement is suspected.

## Normal operation

Supply the most recent authenticated anchor on every open. Publish a new
checkpoint after installs, upgrades, revocations, key changes, suspension and
before/after backup operations. A no-op at unchanged trusted time does not advance
revision.

The registry retains the opened database file descriptor and its parent-directory
descriptor until SQLite closes. Every authority transaction checks the held file,
its parent-relative directory entry and the absolute configured path for one
matching regular non-symlink inode. The SQLite connection never re-resolves the
caller pathname after the no-follow open.

Treat these as admission-stop conditions:

- `skill_registry_state_integrity_invalid`: authority rows and continuity digest
  disagree, or semantic state is malformed;
- `skill_registry_state_instance_mismatch`: an anchored database is absent or a
  different instance is present;
- `skill_registry_state_rollback`: revision is below the retained anchor;
- `skill_registry_state_fork`: the anchored revision has another digest;
- `skill_registry_database_replaced`: held object and configured pathname differ,
  or the initial open interval observed pathname ABA;
- `skill_registry_database_identity_unavailable`: required Linux no-follow/object
  binding primitives are unavailable;
- `skill_registry_storage_integrity_invalid`: SQLite/storage integrity failed;
- `skill_registry_state_migration_required`: legacy layout needs offline upgrade.

Do not fall back to an unanchored or pathname-only open. Log only fixed error
codes and safe opaque identifiers, never manifests, signatures, package contents
or private key data.

## Backup and restore

Quiesce writers and obtain a verified checkpoint. Use a SQLite-consistent backup
that includes committed WAL state. Store backup identity and checkpoint in
separate controlled systems. Test restore on isolated copies.

Before serving restored state, supply the last accepted external anchor. Keep
service unavailable if instance differs, revision regresses or the same revision
has another digest. A higher local revision must still be reconciled with genuine
operator and anchor records; source acceptance alone is not an independent fact.

Never discard a damaged WAL/journal or restore only the main file. Preserve the
incident image. If every install, revocation and event cannot be proved, keep
execution disabled.

## Path replacement and concurrent processes

The held object prevents the constructor from connecting to file A and then
capturing file B as its expected identity. It also prevents migration from being
redirected to a replacement inode. A replacement observed before or during a
transaction causes failure and no success response.

SQLite commit and an arbitrary directory-entry change are not one atomic kernel
operation. Replacement after the final pre-commit check can leave a committed
change in the held detached inode before the post-commit check returns an error.
Preserve both objects and investigate; do not copy the detached result over the
configured path without an anchor-backed recovery decision. On restart, only the
externally retained instance anchor distinguishes a different but internally
valid file.

Multiple current-version processes may share the same local WAL database and
serialize through `BEGIN IMMEDIATE` if they use the same policy and anchor floor.
This is not a multi-host or network-filesystem contract.

## Validation and acceptance

Run:

```bash
python3 -m unittest services.skills.test_signed_registry_schema -v
python3 -m unittest services.skills.test_signed_registry -v
python3 -m unittest services.skills.test_package_transparency -v
python3 -m unittest services.qualification.test_signed_registry_runtime_policy -v
python3 -m unittest services.qualification.test_signed_registry_object_binding -v
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

Then require all seven canonical jobs on one unchanged head, download and inspect
that head's source artifact, and obtain a fresh eligible non-pusher/CODEOWNER
review. Local continuity is not a TPM/KMS anchor, operated transparency,
protected-main adoption or product release evidence. Keep PR #101 Draft until
all broader gates are genuinely satisfied.
