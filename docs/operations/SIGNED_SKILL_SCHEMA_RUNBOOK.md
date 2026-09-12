# Signed Skill registry schema incident runbook

Owner: skills. Scope: local schema-integrity admission for the Signed Skill
registry. Design: `docs/development/SIGNED_SKILL_SCHEMA_INTEGRITY.md`.
Contract: `contracts/signed-skill-package-v1.json`. HG-0087/skills remains OPEN.

## Deployment preconditions

Stop and drain every old Signed Skill service process before installing this
repair. Preserve the database, WAL and SHM files together on trusted local
operator-owned storage. Do not use a network filesystem or an untrusted writable
directory. This source cannot fence a predecessor process that already has the
database open.

Run the new binary against a controlled copy first. A normal intact version-1
registry must reopen without changing installed rows, revocations, events,
suspension or `last_time`. The schema version remains 1; no row migration command
is required or supplied.

## Startup failure response

Treat these failures as admission-stopping incidents:

- `skill_unmarked_schema_rejected`: one or more `signed_skill_*` tables exist
  without the component marker;
- `skill_registry_schema_integrity_invalid`: an established registry is missing
  or has malformed authority state; and
- `skill_registry_policy_migration_required`: the configured subject, capability,
  domain or capacity policy differs from the persisted binding.

Keep execution and installation disabled. Copy the database and journals using
the approved forensic procedure, record hashes and inspect all five authority
tables plus `hepta_component_schema`. Never make startup pass by creating an
empty revocation/installed/event/key/policy table, inserting a replacement policy
row, deleting the marker, editing `last_time` or suspension, or restoring an old
snapshot without authoritative anti-rollback evidence.

A missing table is deliberately left missing after rejected startup. That is not
a request to initialize it. Escalate to the storage/recovery owner and reconstruct
facts only from authentic backups and external publisher/consent/revocation
records under a reviewed recovery plan.

## Normal verification

Run:

```bash
python3 -m unittest services.skills.test_signed_registry_schema -v
python3 -m unittest services.skills.test_signed_registry -v
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
```

Then require all seven canonical CI jobs to execute and succeed on the same
unchanged head, download and verify that head's source artifact, and obtain an
eligible independent review. Do not transfer a prior head's CI, artifact or
approval.

## Evidence and recovery boundary

A successful local schema check is not proof that a privileged operator did not
rewrite rows, that a whole database was not rolled back, or that publisher and
package governance is externally witnessed. Backups, remote anti-rollback,
encrypted package storage and independent incident acceptance remain separate
requirements. Keep PR #101 Draft and do not merge, deploy or release on this
source test alone.
