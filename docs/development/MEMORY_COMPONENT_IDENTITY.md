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

When no Memory table remains, the retained `HMEM` marker always causes startup
rejection and survives a normal `VACUUM`. Legacy `sqlite_sequence` residue is
used only when it is the sole remaining SQLite user-state table. The sequence
table is database-global: an unrelated `AUTOINCREMENT` table may legitimately
create it and must not by itself be interpreted as lost Memory custody. A marked
component therefore cannot become fresh merely by dropping all four tables, and
a shared fresh database may retain unrelated auto-increment data.

## Shared-database and transaction-entry boundary

A pre-marker Memory database that loses every Memory table while unrelated user
tables remain is intrinsically ambiguous: neither `application_id` nor a
Memory-specific table survives. This source does not claim to detect that case.
Use a dedicated operator-owned database for production Memory custody and adopt
the marker before relying on complete-loss detection. Whole-file replacement and
privileged header changes remain outside the source guarantee.

`DurableMemoryStore._Tx` acquires a process lock before `BEGIN IMMEDIATE`. Python
does not call a context manager's `__exit__` when `__enter__` raises, so a busy or
failed SQLite begin must release that lock inside `__enter__`. The implementation
now does so for every `BaseException`; the failed transaction performs no Memory
state mutation and another thread may continue after the storage condition is
handled. This is local lock hygiene, not a distributed availability guarantee.

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

The component-identity tests cover complete table loss with and without `VACUUM`,
row-preserving adoption by an intact pre-marker database and rejection of a
conflicting application identity. The primary Memory suite additionally covers
shared databases with unrelated `AUTOINCREMENT` state and release of the process
lock after `BEGIN IMMEDIATE` failure. They use real SQLite but are not backup,
forensics, KMS, remote deletion or independent deployment evidence.
