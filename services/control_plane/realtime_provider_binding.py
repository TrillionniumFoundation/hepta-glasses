"""Trusted deployment namespace for Realtime metadata and explicit v3 upgrade.

A binding is non-secret operator configuration, not provider/account proof.
No credentials, automatic migration, relabel, reset or remote calls live here.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from services.control_plane import realtime_recovery as recovery
from services.control_plane.durable_state import identifier

VERSION = 4
TABLES = frozenset({'realtime_provider_scope'})


def checked_binding(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        raise ValueError('realtime_provider_binding_invalid')
    return value


def check_adapter(provider: object, binding: str) -> None:
    """Legacy trusted adapters may omit binding_id, never the host binding.

    Real adapters should expose immutable binding_id covering provider, account,
    project, region and lookup namespace. This check cannot attest credentials.
    """
    checked_binding(binding)
    try:
        declared = getattr(provider, 'binding_id', binding)
    except Exception:
        raise ValueError('realtime_provider_configuration_invalid') from None
    if type(declared) is not str or declared != binding:
        raise ValueError('realtime_provider_binding_mismatch')


def create_scope(db: sqlite3.Connection, binding: str) -> None:
    db.execute('CREATE TABLE realtime_provider_scope('
               'id INTEGER PRIMARY KEY CHECK(id=1),binding TEXT NOT NULL)')
    db.execute('INSERT INTO realtime_provider_scope VALUES(1,?)', (checked_binding(binding),))


def require_scope(db: sqlite3.Connection, binding: str) -> None:
    rows = db.execute('SELECT id,binding FROM realtime_provider_scope').fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError('realtime_provider_scope_invalid')
    if checked_binding(rows[0][1]) != checked_binding(binding):
        raise ValueError('realtime_provider_binding_mismatch')


def validate_legacy_ownership(db: sqlite3.Connection) -> None:
    """Reject ambiguous historical owners, not multiple cleanups for one owner.

    The latest v3 result-custody repair deliberately retains all remote sessions
    observed for one local attempt. Those rows and spent budgets must migrate.
    """
    claims = ('WITH claims AS (SELECT session_id,provider_session_id FROM sessions '
              'WHERE provider_session_id IS NOT NULL UNION ALL '
              'SELECT session_id,provider_session_id FROM realtime_revoke_outbox '
              'WHERE provider_session_id IS NOT NULL) ')
    if db.execute(claims + 'SELECT 1 FROM claims GROUP BY provider_session_id '
                  'HAVING COUNT(DISTINCT session_id)>1 LIMIT 1').fetchone():
        raise ValueError('realtime_provider_legacy_ownership_conflict')
    if db.execute('SELECT 1 FROM realtime_revoke_outbox o LEFT JOIN sessions s USING(session_id) '
                  'WHERE s.session_id IS NULL LIMIT 1').fetchone():
        raise ValueError('realtime_provider_legacy_ownership_invalid')
    for row in db.execute('SELECT session_id,provider_session_id,provider_receipt_id FROM sessions '
                          'WHERE provider_session_id IS NOT NULL'):
        if not all(identifier(value) for value in row):
            raise ValueError('realtime_provider_legacy_ownership_invalid')
    for job, sid, remote in db.execute('SELECT job_id,session_id,provider_session_id FROM realtime_revoke_outbox'):
        if (not identifier(sid) or (remote is not None and not identifier(remote))
                or job != ('provider:' + remote if remote is not None else 'lookup:' + sid)):
            raise ValueError('realtime_provider_legacy_ownership_invalid')


def migrate_realtime_v3(path: str, *, provider_binding: str) -> dict[str, object]:
    """OFFLINE only: stop/drain all old processes and verify tenant out of band.

    Assigns the operator's explicit namespace to historical state without claiming
    to verify its tenant. Preserves all seven v3 tables, deadlines and used budgets.
    Does not change current conflict-cleanup policy or add a quarantine state.
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
            existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
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
            validate_legacy_ownership(db)
            counts = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in sorted(legacy)}
            create_scope(db, binding)
            require_scope(db, binding)
            db.execute("UPDATE hepta_component_schema SET version=? WHERE component='realtime' AND version=3", (VERSION,))
            db.execute('COMMIT')
            return {'from_version': 3, 'to_version': VERSION, 'preserved_rows': counts,
                    'provider_binding': binding, 'historical_provider_verified': False,
                    'recovery_allowance_added': 0, 'independent_evidence': False}
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
    finally:
        db.close()
