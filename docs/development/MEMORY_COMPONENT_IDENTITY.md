# Durable Memory component identity and complete-table-loss detection

Status: incremental HG-0087/Memory source hardening; Memory and aggregate remain
OPEN. Owner: privacy. Implementation:
`services/skills/durable_memory_schema.py`. Regression:
`services/skills/test_durable_memory_component_identity.py`. The primary design
remains `docs/development/DURABLE_MEMORY.md` and the machine contract is
`contracts/durable-memory-v1.json`.

## Problem

Checking only whether any required table exists detects partial schema loss, but
cannot by itself distinguish a genuinely fresh database from an established
Memory database whose four authority tables were all removed. The predecessor
could therefore recreate empty consent, record and deletion tables after complete
loss. A subsequent SQLite `VACUUM` can remove the otherwise useful
`sqlite_sequence` residue.

This is a local custody failure, not a claim that a privileged attacker is the
supported threat boundary. The consequence is nevertheless fail-open recovery:
pending deletion propagation, consent and record custody can disappear while a
new empty component is accepted.

## Persistent identity

Fresh Memory initialization sets SQLite `PRAGMA application_id` to the fixed
32-bit value `0x484D454D` (ASCII `HMEM`) in the same initialization transaction as
the four authority tables and schema row. The value contains no key material,
subject identifier or authorization. It is a component identity marker only.

An intact predecessor version-1 database with `application_id=0` may adopt the
marker only after every required table, schema singleton, column layout and the
deletion-event uniqueness constraint pass validation. Existing rows are not
rewritten. A different nonzero application ID is rejected rather than overwritten.
This prevents the Memory component from silently taking over a database already
claimed by another application.

When no Memory table remains, either the retained `HMEM` marker or legacy
`sqlite_sequence` residue causes startup rejection. `application_id` survives a
normal `VACUUM`, so a marked component cannot become fresh merely by dropping all
four tables and vacuuming the file. The constructor closes its connection on the
failure and does not recreate authority state.

## Limits and operations

This marker is not cryptographic, externally witnessed or monotonic. A privileged
writer can change the database header, replace the whole file or restore an older
snapshot. Those operations remain outside this source guarantee and require
operator-owned storage, encrypted backup controls and an external anti-rollback
or authoritative recovery design.

Stop old processes before rollout. A predecessor process already holding the
database does not know this rule and can still recreate missing tables. Validate
`application_id`, all four tables, the schema row and pending deletion count after
upgrade before re-enabling authenticated ingress. Never clear the marker or
replace missing tables with empty copies as incident recovery.

The four dedicated tests cover complete table loss with and without `VACUUM`,
row-preserving adoption by an intact pre-marker database and rejection of a
conflicting application identity. They use real SQLite but are not backup,
forensics, KMS, remote deletion or independent deployment evidence.
