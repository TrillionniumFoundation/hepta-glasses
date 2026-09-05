# Signed Skill registry schema integrity

Status: incremental source repair under HG-0087/skills; the Skills slice and
aggregate HG-0087 remain **OPEN**. Owner: skills. Implementation:
`services/skills/signed_registry_schema.py` and
`services/skills/signed_registry.py`. Regression:
`services/skills/test_signed_registry_schema.py`. Package/admission design:
`docs/development/SIGNED_SKILLS.md`.

## Problem and required invariant

The predecessor opened every Signed Skill table with `CREATE TABLE IF NOT EXISTS`
and initialized the policy singleton with `INSERT OR IGNORE`, even when the
`signed_skills` component version marker already existed. If an established
registry lost its installed, revocation, key, policy or audit table, startup
could replace the missing authority with an empty table. Losing the revocation
or installed table could therefore be misread as a clean registry rather than a
storage-integrity failure.

An established registry must never infer that absent authority means no prior
installation, no revocation, no audit history or a fresh policy. Initialization
is permitted only when both the component marker and all component tables are
absent. Once marked, every authority table and the policy singleton are required.

## Fresh versus established state

`DurableDatabase.version("signed_skills", 1)` determines only whether the
component marker is present. `ensure_signed_skill_schema` then applies one of two
paths inside the same `BEGIN IMMEDIATE` transaction:

| State | Result |
|---|---|
| No marker and no Signed Skill authority table | Create the five tables and one policy row, then the caller pins keys and marks version 1 |
| No marker but any `signed_skill_*` table exists | Reject `skill_unmarked_schema_rejected`; no implicit adoption |
| Marker version 1 and every required table/policy invariant holds | Reopen without replacing facts |
| Marker version 1 but any required table, singleton, column or constraint is missing/malformed, or an unknown `signed_skill_*` table exists | Reject `skill_registry_schema_integrity_invalid`; no table or row is recreated |
| Marker with an unknown version | Existing `signed_skills_schema_migration_required` failure |
| Complete schema but subject/capability/domain/capacity policy differs | Existing `skill_registry_policy_migration_required` failure |

The required authority tables are:

- `signed_skill_policy`: one row with `id=1`, exact persisted policy, valid
  `last_time`, and suspended value 0 or 1;
- `signed_skill_keys`: exact key binding columns and a non-partial unique
  fingerprint constraint;
- `signed_skill_installed`: exact signed document, signature, digest, consent
  expiry and event-sequence custody;
- `signed_skill_revocations`: exact composite `(kind,target)` primary key; and
- `signed_skill_events`: exact hash-chain columns and an `AUTOINCREMENT` sequence.

The policy table's `CHECK(id=1)` and the event sequence's `AUTOINCREMENT` are
verified in addition to column metadata. Secondary indexes not representing
these authority constraints are not created or repaired by this helper.

## Transaction and failure behavior

Fresh schema, initial policy, pinned key bindings and the component marker are
committed in one write transaction. Any key/policy/configuration failure rolls
all fresh component writes back. For an established registry, validation runs
before any key insertion or operational access. A missing table remains missing
after rejected startup, making the incident visible to operators and preserving
the possibility of forensic recovery.

Constructor failure closes the SQLite connection. Tests verify that a separate
connection can subsequently acquire `BEGIN IMMEDIATE`; schema rejection must not
leave a process-local or database write lock behind.

Suspension and `last_time` are durable facts. Reopening accepts a valid suspended
policy row and does not set it back to active. Ordinary operations retain their
existing clock-rollback and suspension checks. This repair does not add an
unsuspend, un-revoke, destructive reset or row-reconstruction API.

## Compatibility and migration

The component version remains **1** because this repair does not change any
column or persisted data representation. Databases produced by the preceding
version use the same five table definitions and reopen after validation. This is
stricter startup behavior, not an automatic data migration.

Stop and drain old processes before deploying the repaired binary. A process
already running the predecessor can still recreate a table after an operator or
storage failure; a source update cannot retroactively fence it. Do not respond to
a startup failure by deleting the component marker, creating an empty table,
copying a policy row, changing the version or restoring an unverified old
snapshot. Recover the actual authoritative database through a separately
reviewed, evidence-preserving procedure.

The helper detects missing tables, malformed local schema and policy singleton
loss in the database it opens. It does **not** prevent privileged row deletion,
whole-file replacement, stale snapshot rollback, hostile kernel/storage behavior
or a coordinated rewrite of both schema and data. Production custody still needs
operator-owned local storage, backup integrity and an external anti-rollback
strategy.

## Verification and evidence boundary

The dedicated tests use real SQLite and cover all five missing tables, complete
loss with the marker retained, marker removal with tables retained, unknown
namespaced tables in fresh/established state, missing and multiple policy rows,
invalid policy state, policy drift, removed fingerprint uniqueness, removed
event AUTOINCREMENT, changed columns, suspension/time persistence, invalid fresh
clock rollback and write-lock release after failed construction.

Run this suite with the existing real Ed25519/package registry suite and the full
repository matrix. These tests establish local source behavior only. They do not
supply external publisher governance, witnessed transparency, encrypted package
custody, arbitrary-code isolation, provider/device evidence, independent review
or product release authority.
