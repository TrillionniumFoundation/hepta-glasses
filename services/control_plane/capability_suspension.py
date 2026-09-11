"""Persistent emergency denial and explicit offline v1-to-v2 migration.

This is local safety state, not remote cancellation or backup anti-rollback.
Migration requires all old service processes stopped; a boolean cannot prove it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

COMPONENT = "durable_capabilities"
VERSION = 2
CONTROL_TABLE = "hg_capability_control"
LEGACY_TABLES = frozenset({
    "hg_capability_operations", "hg_capability_leases",
    "hg_capability_revoked", "hg_capability_events",
})
_REASONS = frozenset({"revocation_capacity", "clock_unavailable"})
_CREATE = (
    "CREATE TABLE hg_capability_control ("
    "id INTEGER PRIMARY KEY CHECK(id=1), "
    "suspended INTEGER NOT NULL CHECK(suspended IN (0,1)), "
    "reason TEXT NOT NULL CHECK("
    "(suspended=0 AND reason='active') OR "
    "(suspended=1 AND reason IN ('revocation_capacity','clock_unavailable'))))"
)


def create_control(db: sqlite3.Connection) -> None:
    """Call once inside a fresh initialization or explicit migration transaction."""
    db.execute(_CREATE)
    db.execute("INSERT INTO hg_capability_control VALUES(1,0,'active')")


def control_status(db: sqlite3.Connection) -> dict[str, object]:
    """Check the singleton on every admission; never reconstruct missing state."""
    rows = db.execute("SELECT id,suspended,reason FROM hg_capability_control").fetchall()
    if (len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int
            or rows[0][1] not in (0, 1)
            or (rows[0][1] == 0 and rows[0][2] != "active")
            or (rows[0][1] == 1 and rows[0][2] not in _REASONS)):
        raise ValueError("capability_control_integrity_invalid")
    return {"suspended": bool(rows[0][1]), "reason": rows[0][2]}


def suspend(db: sqlite3.Connection, reason: str) -> dict[str, object]:
    """One durable monotonic transition; preserve its first reason without a clock."""
    if reason not in _REASONS:
        raise ValueError("capability_suspension_reason_invalid")
    state = control_status(db)
    if not state["suspended"]:
        db.execute("UPDATE hg_capability_control SET suspended=1,reason=? WHERE id=1 AND suspended=0", (reason,))
    return control_status(db)


def migrate_capability_v1(path: str) -> dict[str, object]:
    """Offline, additive migration of an existing intact v1 database, no reset.

    Stop/drain every old binary before calling, including already-open clients.
    New code refuses v1 at normal startup. Old code refuses v2 on reopening, but
    migration cannot terminate an old process that is still running. Do not use
    this as a rolling upgrade. Never restore a stale snapshot after migration.
    """
    if type(path) is not str or not path or path == ":memory:":
        raise ValueError("capability_migration_path_invalid")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("capability_migration_existing_file_required")
    # mode=rw cannot create an empty replacement if the file disappears.
    uri = "file:" + quote(str(source.absolute()), safe="/") + "?mode=rw"
    db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            raise ValueError("capability_migration_wal_required")
        db.execute("BEGIN IMMEDIATE")
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not LEGACY_TABLES | {"hepta_component_schema"} <= tables or CONTROL_TABLE in tables:
                raise ValueError("capability_migration_schema_invalid")
            row = db.execute("SELECT version FROM hepta_component_schema WHERE component=?", (COMPONENT,)).fetchone()
            if row is None or type(row[0]) is not int or row[0] != 1:
                raise ValueError("capability_migration_version_invalid")
            if (db.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                    or db.execute("PRAGMA foreign_key_check").fetchone() is not None):
                raise ValueError("capability_migration_integrity_invalid")
            counts = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in sorted(LEGACY_TABLES)}
            create_control(db)
            db.execute("UPDATE hepta_component_schema SET version=? WHERE component=? AND version=1", (VERSION, COMPONENT))
            db.execute("COMMIT")
            return {"from_version": 1, "to_version": VERSION, "preserved_rows": counts,
                    "remote_cancellation_confirmed": False}
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
    finally:
        db.close()
