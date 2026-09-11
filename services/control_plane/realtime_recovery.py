"""Persistent, finite realtime recovery allowances; no reset or remote evidence.

All mutating helpers run inside the caller's BEGIN IMMEDIATE transaction.
The explicit v2 migration grants NEW bounded post-upgrade recovery allowances;
prior uncounted provider traffic is unknown and is never claimed to be zero.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

VERSION = 3
LEGACY_TABLES = frozenset({'tickets', 'sessions', 'realtime_attempts', 'realtime_revoke_outbox'})
BUDGET_TABLES = frozenset({'realtime_recovery_policy', 'realtime_lookup_budget', 'realtime_revoke_budget'})


def checked_limits(lookups: int, revokes: int) -> tuple[int, int]:
    if any(type(v) is not int or not 1 <= v <= 32 for v in (lookups, revokes)):
        raise ValueError('realtime_recovery_limits_invalid')
    return lookups, revokes


def limits(db: sqlite3.Connection) -> tuple[int, int]:
    rows = db.execute('SELECT id,lookup_limit,revoke_limit FROM realtime_recovery_policy').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('realtime_recovery_policy_invalid')
    return checked_limits(rows[0][1], rows[0][2])


def create_budgets(db: sqlite3.Connection, lookups: int, revokes: int) -> None:
    """Fresh creation or deliberate offline migration, never routine reopening."""
    checked_limits(lookups, revokes)
    db.execute('CREATE TABLE realtime_recovery_policy('
               'id INTEGER PRIMARY KEY CHECK(id=1),'
               'lookup_limit INTEGER NOT NULL CHECK(lookup_limit BETWEEN 1 AND 32),'
               'revoke_limit INTEGER NOT NULL CHECK(revoke_limit BETWEEN 1 AND 32))')
    db.execute('INSERT INTO realtime_recovery_policy VALUES(1,?,?)', (lookups, revokes))
    db.execute('CREATE TABLE realtime_lookup_budget('
               'session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),'
               'used INTEGER NOT NULL CHECK(used>=0))')
    db.execute('CREATE TABLE realtime_revoke_budget('
               'job_id TEXT PRIMARY KEY REFERENCES realtime_revoke_outbox(job_id),'
               'used INTEGER NOT NULL CHECK(used>=0))')
    db.execute('INSERT INTO realtime_lookup_budget SELECT session_id,0 FROM sessions')
    db.execute('INSERT INTO realtime_revoke_budget SELECT job_id,0 FROM realtime_revoke_outbox '
               'WHERE provider_session_id IS NOT NULL')


def usage(db: sqlite3.Connection, kind: str, identity: str) -> tuple[int, int]:
    if kind not in ('lookup', 'revoke'):
        raise ValueError('realtime_recovery_kind_invalid')
    maximum = limits(db)[0 if kind == 'lookup' else 1]
    table, column = ('realtime_lookup_budget', 'session_id') if kind == 'lookup' else ('realtime_revoke_budget', 'job_id')
    row = db.execute(f'SELECT used FROM {table} WHERE {column}=?', (identity,)).fetchone()
    if row is None or type(row[0]) is not int or not 0 <= row[0] <= maximum:
        raise ValueError('realtime_recovery_counter_invalid')
    return row[0], maximum


def reserve(db: sqlite3.Connection, kind: str, identity: str) -> bool:
    """Reserve BEFORE network work; crashes/timeouts/saturation never refund."""
    used, maximum = usage(db, kind, identity)
    if used == maximum:
        return False
    table, column = ('realtime_lookup_budget', 'session_id') if kind == 'lookup' else ('realtime_revoke_budget', 'job_id')
    updated = db.execute(f'UPDATE {table} SET used=used+1 WHERE {column}=? AND used=?', (identity, used))
    if updated.rowcount != 1:
        raise ValueError('realtime_recovery_counter_conflict')
    return True


def validate_budgets(db: sqlite3.Connection, lookups: int, revokes: int) -> None:
    if limits(db) != checked_limits(lookups, revokes):
        raise ValueError('realtime_recovery_policy_migration_required')
    # Detect missing/extra counter custody rather than recreating a zero counter.
    checks = (
        ('SELECT 1 FROM sessions s LEFT JOIN realtime_lookup_budget b USING(session_id) '
         'WHERE b.session_id IS NULL LIMIT 1', ()),
        ('SELECT 1 FROM realtime_lookup_budget b LEFT JOIN sessions s USING(session_id) '
         'WHERE s.session_id IS NULL OR typeof(b.used)!=\'integer\' OR b.used<0 OR b.used>? LIMIT 1', (lookups,)),
        ('SELECT 1 FROM realtime_revoke_outbox o LEFT JOIN realtime_revoke_budget b USING(job_id) '
         'WHERE o.provider_session_id IS NOT NULL AND b.job_id IS NULL LIMIT 1', ()),
        ('SELECT 1 FROM realtime_revoke_budget b LEFT JOIN realtime_revoke_outbox o USING(job_id) '
         'WHERE o.job_id IS NULL OR o.provider_session_id IS NULL OR typeof(b.used)!=\'integer\' '
         'OR b.used<0 OR b.used>? LIMIT 1', (revokes,)),
    )
    if any(db.execute(sql, args).fetchone() is not None for sql, args in checks):
        raise ValueError('realtime_recovery_counter_invalid')


def eligible_jobs(db: sqlite3.Connection, maximum: int) -> list[sqlite3.Row]:
    lookups, revokes = limits(db)
    # Least-attempted first. Exhausted pending jobs remain visible to operators,
    # but cannot starve runnable work. Missing counters surface as errors on use.
    return db.execute(
        "SELECT o.*, CASE WHEN o.provider_session_id IS NULL THEN l.used ELSE r.used END AS spent "
        "FROM realtime_revoke_outbox o "
        "LEFT JOIN realtime_lookup_budget l ON l.session_id=o.session_id "
        "LEFT JOIN realtime_revoke_budget r ON r.job_id=o.job_id "
        "WHERE o.state='pending' AND (spent IS NULL OR spent<CASE WHEN o.provider_session_id IS NULL THEN ? ELSE ? END) "
        "ORDER BY spent,o.job_id LIMIT ?", (lookups, revokes, maximum)).fetchall()


def migrate_realtime_v2(path: str, *, maximum_readbacks: int,
                        maximum_revoke_attempts: int) -> dict[str, object]:
    """Explicit OFFLINE additive upgrade. Stop/drain all old binaries first.

    These required limits authorize a new bounded post-upgrade allowance for
    each legacy session/job. Historical v2 attempt usage cannot be reconstructed.
    No ticket, session, attempt or outbox row is rewritten, nor expiry extended.
    Re-running on v3 is forbidden. The returned report is local, not a witness.
    """
    lookups, revokes = checked_limits(maximum_readbacks, maximum_revoke_attempts)
    if type(path) is not str or not path or path == ':memory:':
        raise ValueError('realtime_migration_path_invalid')
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError('realtime_migration_existing_file_required')
    db = sqlite3.connect('file:' + quote(str(source.absolute()), safe='/') + '?mode=rw',
                         uri=True, isolation_level=None, timeout=5)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
            raise ValueError('realtime_migration_wal_required')
        db.execute('BEGIN IMMEDIATE')
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not LEGACY_TABLES | {'hepta_component_schema'} <= tables or BUDGET_TABLES & tables:
                raise ValueError('realtime_migration_schema_invalid')
            row = db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()
            if row is None or type(row[0]) is not int or row[0] != 2:
                raise ValueError('realtime_migration_version_invalid')
            if (db.execute('PRAGMA quick_check').fetchall() != [('ok',)]
                    or db.execute('PRAGMA foreign_key_check').fetchone() is not None):
                raise ValueError('realtime_migration_integrity_invalid')
            counts = {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in sorted(LEGACY_TABLES)}
            create_budgets(db, lookups, revokes)
            validate_budgets(db, lookups, revokes)
            db.execute("UPDATE hepta_component_schema SET version=? WHERE component='realtime' AND version=2", (VERSION,))
            db.execute('COMMIT')
            return {'from_version': 2, 'to_version': VERSION, 'preserved_rows': counts,
                    'additional_lookup_allowance': lookups, 'additional_revoke_allowance': revokes,
                    'historical_attempts': 'unknown; v2 did not count', 'independent_evidence': False}
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
    finally:
        db.close()
