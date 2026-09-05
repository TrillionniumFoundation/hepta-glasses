"""Fail-closed SQLite schema initialization for durable Memory custody.

Missing authority tables in an established database are never reconstructed as
empty. Secondary indexes are derived and may be rebuilt without changing facts.
"""
from __future__ import annotations

import sqlite3

VERSION = 1
REQUIRED_TABLES = frozenset({
    "memory_schema", "memory_consents", "memory_records", "memory_deletions",
})

_CREATE_TABLES = (
    "CREATE TABLE memory_schema(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL)",
    "CREATE TABLE memory_consents(subject TEXT NOT NULL,purpose TEXT NOT NULL,classes TEXT NOT NULL,expires_at INTEGER NOT NULL,PRIMARY KEY(subject,purpose))",
    "CREATE TABLE memory_records(memory_id TEXT PRIMARY KEY,subject TEXT NOT NULL,purpose TEXT NOT NULL,data_class TEXT NOT NULL,ciphertext BLOB NOT NULL,value_digest TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,key_id TEXT NOT NULL)",
    "CREATE TABLE memory_deletions(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,subject TEXT NOT NULL,memory_id TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','completed')))",
)
_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS memory_records_subject ON memory_records(subject,purpose,memory_id)",
    "CREATE INDEX IF NOT EXISTS memory_deletions_pending ON memory_deletions(state,seq)",
)
_EXPECTED_COLUMNS = {
    "memory_schema": (
        ("id", "INTEGER", 0, 1), ("version", "INTEGER", 1, 0),
    ),
    "memory_consents": (
        ("subject", "TEXT", 1, 1), ("purpose", "TEXT", 1, 2),
        ("classes", "TEXT", 1, 0), ("expires_at", "INTEGER", 1, 0),
    ),
    "memory_records": (
        ("memory_id", "TEXT", 0, 1), ("subject", "TEXT", 1, 0),
        ("purpose", "TEXT", 1, 0), ("data_class", "TEXT", 1, 0),
        ("ciphertext", "BLOB", 1, 0), ("value_digest", "TEXT", 1, 0),
        ("created_at", "INTEGER", 1, 0), ("expires_at", "INTEGER", 1, 0),
        ("key_id", "TEXT", 1, 0),
    ),
    "memory_deletions": (
        ("seq", "INTEGER", 0, 1), ("event_id", "TEXT", 1, 0),
        ("subject", "TEXT", 1, 0), ("memory_id", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0), ("created_at", "INTEGER", 1, 0),
        ("state", "TEXT", 1, 0),
    ),
}


def _columns(db: sqlite3.Connection, table: str) -> tuple[tuple[str, str, int, int], ...]:
    return tuple((row[1], str(row[2]).upper(), row[3], row[5])
                 for row in db.execute(f"PRAGMA table_info({table})"))


def _has_unique_event_id(db: sqlite3.Connection) -> bool:
    for row in db.execute("PRAGMA index_list(memory_deletions)"):
        if row[2] != 1:
            continue
        columns = tuple(item[2] for item in db.execute(f"PRAGMA index_info({row[1]})"))
        if columns == ("event_id",):
            return True
    return False


def ensure_memory_schema(db: sqlite3.Connection, *, version: int = VERSION) -> None:
    """Create a fresh component or validate every established authority table."""
    if type(version) is not int or version != VERSION:
        raise ValueError("durable_memory_schema_migration_required")
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    present = tables & REQUIRED_TABLES
    if not present:
        for statement in _CREATE_TABLES:
            db.execute(statement)
        db.execute("INSERT INTO memory_schema VALUES(1,?)", (version,))
    else:
        if present != REQUIRED_TABLES:
            raise ValueError("durable_memory_schema_integrity_invalid")
        try:
            rows = db.execute("SELECT id,version FROM memory_schema").fetchall()
        except sqlite3.DatabaseError:
            raise ValueError("durable_memory_schema_integrity_invalid") from None
        if (len(rows) != 1 or rows[0][0] != 1 or type(rows[0][1]) is not int):
            raise ValueError("durable_memory_schema_integrity_invalid")
        if rows[0][1] != version:
            raise ValueError("durable_memory_schema_migration_required")
        if (any(_columns(db, table) != expected
                for table, expected in _EXPECTED_COLUMNS.items())
                or not _has_unique_event_id(db)):
            raise ValueError("durable_memory_schema_integrity_invalid")
    for statement in _CREATE_INDEXES:
        db.execute(statement)
