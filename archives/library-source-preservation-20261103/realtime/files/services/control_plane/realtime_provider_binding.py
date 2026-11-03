"""Trusted deployment namespace and local remote-session ownership.

No provider credentials, external verification, remote deletion or reset API.
All write helpers run in the caller's BEGIN IMMEDIATE transaction.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from services.control_plane import realtime_recovery as recovery
from services.control_plane.durable_state import identifier

VERSION = 4
TABLES = frozenset({'realtime_provider_scope', 'realtime_provider_quarantine'})
OWNERSHIP_INDEX = 'realtime_one_remote_session_owner'


def checked_binding(value: object) -> str:
    # An operator-governed NON-SECRET configuration ID, not a token or URL.
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        raise ValueError('realtime_provider_binding_invalid')
    return value


def create_scope(db: sqlite3.Connection, binding: str) -> None:
    checked_binding(binding)
    db.execute('CREATE TABLE realtime_provider_scope('
               'id INTEGER PRIMARY KEY CHECK(id=1),binding TEXT NOT NULL)')
    db.execute('INSERT INTO realtime_provider_scope VALUES(1,?)', (binding,))
    db.execute('CREATE TABLE realtime_provider_quarantine('
               'session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),'
               'claimed_remote_id TEXT NOT NULL,reason TEXT NOT NULL)')
    db.execute('CREATE UNIQUE INDEX ' + OWNERSHIP_INDEX +
               ' ON sessions(provider_session_id) WHERE provider_session_id IS NOT NULL')


def require_scope(db: sqlite3.Connection, binding: str) -> None:
    rows = db.execute('SELECT id,binding FROM realtime_provider_scope').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('realtime_provider_scope_invalid')
    if checked_binding(rows[0][1]) != checked_binding(binding):
        raise ValueError('realtime_provider_binding_mismatch')


def is_quarantined(db: sqlite3.Connection, session_id: str) -> bool:
    return db.execute('SELECT 1 FROM realtime_provider_quarantine WHERE session_id=?',
                      (session_id,)).fetchone() is not None


def ownership_conflict(db: sqlite3.Connection, session_id: str, remote_id: str,
                       receipt_id: str | None = None) -> str | None:
    """Check existing immutable session and cleanup custody before claiming an ID."""
    if db.execute(
        'SELECT 1 FROM sessions WHERE provider_session_id=? AND session_id!=? '
        'UNION ALL SELECT 1 FROM realtime_revoke_outbox '
        'WHERE provider_session_id=? AND session_id!=? LIMIT 1',
        (remote_id, session_id, remote_id, session_id)).fetchone():
        return 'remote_session_owned_elsewhere'
    if db.execute(
        'SELECT 1 FROM sessions WHERE session_id=? AND provider_session_id IS NOT NULL AND provider_session_id!=? '
        'UNION ALL SELECT 1 FROM realtime_revoke_outbox '
        'WHERE session_id=? AND provider_session_id IS NOT NULL AND provider_session_id!=? LIMIT 1',
        (session_id, remote_id, session_id, remote_id)).fetchone():
        return 'local_session_remote_identity_changed'
    if receipt_id is not None and db.execute(
        'SELECT 1 FROM sessions WHERE session_id=? AND provider_session_id=? '
        'AND provider_receipt_id IS NOT NULL AND provider_receipt_id!=?',
        (session_id, remote_id, receipt_id)).fetchone():
        return 'remote_receipt_identity_changed'
    return None


def quarantine(db: sqlite3.Connection, session_id: str, remote_id: str, reason: str) -> None:
    """Keep the first contradiction. Never adopt or automatically revoke its ID."""
    if reason not in {'remote_session_owned_elsewhere', 'local_session_remote_identity_changed',
                      'remote_receipt_identity_changed'}:
        raise ValueError('realtime_provider_quarantine_reason_invalid')
    if not identifier(remote_id):
        raise ValueError('realtime_provider_response_invalid')
    db.execute('INSERT INTO realtime_provider_quarantine VALUES(?,?,?) '
               'ON CONFLICT(session_id) DO NOTHING', (session_id, remote_id, reason))
    db.execute("UPDATE sessions SET state='quarantined',generation=generation+1 "
               "WHERE session_id=? AND state!='quarantined'", (session_id,))


def validate_existing_ownership(db: sqlite3.Connection) -> None:
    """Reject ambiguous historical ownership instead of assigning it arbitrarily."""
    claims = ('WITH claims AS (SELECT session_id,provider_session_id FROM sessions '
              'WHERE provider_session_id IS NOT NULL UNION ALL '
              'SELECT session_id,provider_session_id FROM realtime_revoke_outbox '
              'WHERE provider_session_id IS NOT NULL) ')
    if db.execute(claims + 'SELECT 1 FROM claims GROUP BY provider_session_id '
                  'HAVING COUNT(DISTINCT session_id)>1 LIMIT 1').fetchone():
        raise ValueError('realtime_provider_legacy_ownership_conflict')
    if db.execute(claims + 'SELECT 1 FROM claims GROUP BY session_id '
                  'HAVING COUNT(DISTINCT provider_session_id)>1 LIMIT 1').fetchone():
        raise ValueError('realtime_provider_legacy_ownership_conflict')
    if db.execute('SELECT 1 FROM realtime_revoke_outbox o LEFT JOIN sessions s USING(session_id) '
                  'WHERE s.session_id IS NULL LIMIT 1').fetchone():
        raise ValueError('realtime_provider_legacy_ownership_invalid')
    for row in db.execute('SELECT session_id,provider_session_id,provider_receipt_id FROM sessions '
                          'WHERE provider_session_id IS NOT NULL'):
        if not all(identifier(v) for v in row):
            raise ValueError('realtime_provider_legacy_ownership_invalid')
    for row in db.execute('SELECT job_id,session_id,provider_session_id FROM realtime_revoke_outbox'):
        job, sid, remote = row
        if (not identifier(sid) or (remote is not None and not identifier(remote))
                or job != ('provider:' + remote if remote is not None else 'lookup:' + sid)):
            raise ValueError('realtime_provider_legacy_ownership_invalid')


def validate_scope(db: sqlite3.Connection, binding: str) -> None:
    require_scope(db, binding)
    indices = {row[1]: row for row in db.execute('PRAGMA index_list(sessions)')}
    info = indices.get(OWNERSHIP_INDEX)
    columns = [r[2] for r in db.execute('PRAGMA index_info(' + OWNERSHIP_INDEX + ')')]
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                     (OWNERSHIP_INDEX,)).fetchone()
    expected = ('CREATE UNIQUE INDEX ' + OWNERSHIP_INDEX +
                ' ON sessions(provider_session_id) WHERE provider_session_id IS NOT NULL')
    if (info is None or info[2] != 1 or info[4] != 1 or columns != ['provider_session_id']
            or sql is None or ' '.join(sql[0].split()) != expected):
        raise ValueError('realtime_provider_ownership_index_invalid')
    validate_existing_ownership(db)
    for sid, remote, reason, state in db.execute(
        'SELECT q.session_id,q.claimed_remote_id,q.reason,s.state '
        'FROM realtime_provider_quarantine q LEFT JOIN sessions s USING(session_id)'):
        if (state != 'quarantined' or not identifier(sid) or not identifier(remote)
                or reason not in {'remote_session_owned_elsewhere', 'local_session_remote_identity_changed',
                                  'remote_receipt_identity_changed'}):
            raise ValueError('realtime_provider_quarantine_invalid')
    if db.execute("SELECT 1 FROM sessions s LEFT JOIN realtime_provider_quarantine q USING(session_id) "
                  "WHERE s.state='quarantined' AND q.session_id IS NULL LIMIT 1").fetchone():
        raise ValueError('realtime_provider_quarantine_invalid')


def migrate_realtime_v3(path: str, *, provider_binding: str) -> dict[str, object]:
    """OFFLINE additive migration; actual historical tenant must be checked out of band.

    Stop/drain all old processes first. This assigns the operator's explicit
    namespace to old records; it does not verify credentials or provider facts.
    Existing recovery counters, deadlines and all seven v3 tables stay unchanged.
    """
    binding = checked_binding(provider_binding)
    if type(path) is not str or not path or path == ':memory:':
        raise ValueError('realtime_provider_migration_path_invalid')
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError('realtime_provider_migration_existing_file_required')
    db = sqlite3.connect('file:' + quote(str(source.absolute()), safe='/') + '?mode=rw',
                         uri=True, isolation_level=None, timeout=5)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
            raise ValueError('realtime_provider_migration_wal_required')
        db.execute('BEGIN IMMEDIATE')
        try:
            existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            legacy = recovery.LEGACY_TABLES | recovery.BUDGET_TABLES
            if not legacy | {'hepta_component_schema'} <= existing or TABLES & existing:
                raise ValueError('realtime_provider_migration_schema_invalid')
            row = db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()
            if row is None or type(row[0]) is not int or row[0] != 3:
                raise ValueError('realtime_provider_migration_version_invalid')
            if (db.execute('PRAGMA quick_check').fetchall() != [('ok',)]
                    or db.execute('PRAGMA foreign_key_check').fetchone() is not None):
                raise ValueError('realtime_provider_migration_integrity_invalid')
            recovery.validate_budgets(db, *recovery.limits(db))
            validate_existing_ownership(db)
            counts = {t: db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in sorted(legacy)}
            create_scope(db, binding)
            validate_scope(db, binding)
            db.execute("UPDATE hepta_component_schema SET version=? WHERE component='realtime' AND version=3", (VERSION,))
            db.execute('COMMIT')
            return {'from_version':3,'to_version':VERSION,'preserved_rows':counts,
                    'provider_binding':binding,'historical_provider_verified':False,
                    'recovery_allowance_added':0,'independent_evidence':False}
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
    finally:
        db.close()
