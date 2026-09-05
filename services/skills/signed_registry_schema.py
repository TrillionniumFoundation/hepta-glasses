"""Fail-closed schema initialization for durable signed-Skill authority state."""
from __future__ import annotations

import sqlite3

from services.control_plane.durable_state import timestamp
from services.skills.signed_package import fail

REQUIRED_TABLES = frozenset({
    "signed_skill_policy",
    "signed_skill_keys",
    "signed_skill_installed",
    "signed_skill_revocations",
    "signed_skill_events",
})

CREATE_STATEMENTS = (
    "CREATE TABLE signed_skill_policy(id INTEGER PRIMARY KEY CHECK(id=1),policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
    "CREATE TABLE signed_skill_keys(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,binding BLOB NOT NULL)",
    "CREATE TABLE signed_skill_installed(id TEXT PRIMARY KEY,document BLOB NOT NULL,signature BLOB NOT NULL,digest TEXT NOT NULL,consent_expires_at INTEGER NOT NULL,event_sequence INTEGER NOT NULL)",
    "CREATE TABLE signed_skill_revocations(kind TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(kind,target))",
    "CREATE TABLE signed_skill_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,target TEXT NOT NULL,digest TEXT NOT NULL,observed_at INTEGER NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)",
)

EXPECTED_COLUMNS = {
    "signed_skill_policy": (("id", "INTEGER", 0, 1), ("policy", "BLOB", 1, 0),
                            ("last_time", "INTEGER", 1, 0), ("suspended", "INTEGER", 1, 0)),
    "signed_skill_keys": (("id", "TEXT", 0, 1), ("fingerprint", "TEXT", 1, 0),
                          ("binding", "BLOB", 1, 0)),
    "signed_skill_installed": (("id", "TEXT", 0, 1), ("document", "BLOB", 1, 0),
        ("signature", "BLOB", 1, 0), ("digest", "TEXT", 1, 0),
        ("consent_expires_at", "INTEGER", 1, 0), ("event_sequence", "INTEGER", 1, 0)),
    "signed_skill_revocations": (("kind", "TEXT", 1, 1), ("target", "TEXT", 1, 2)),
    "signed_skill_events": (("sequence", "INTEGER", 0, 1), ("event", "TEXT", 1, 0),
        ("target", "TEXT", 1, 0), ("digest", "TEXT", 1, 0),
        ("observed_at", "INTEGER", 1, 0), ("previous_hash", "TEXT", 1, 0),
        ("event_hash", "TEXT", 1, 0)),
}


def _columns(db: sqlite3.Connection, table: str) -> tuple[tuple[str, str, int, int], ...]:
    return tuple((row[1], str(row[2]).upper(), row[3], row[5])
                 for row in db.execute(f"PRAGMA table_info({table})"))


def _unique_fingerprint(db: sqlite3.Connection) -> bool:
    for row in db.execute("PRAGMA index_list(signed_skill_keys)"):
        if row[2] != 1 or (len(row) > 4 and row[4] != 0):
            continue
        columns = tuple(item[2] for item in db.execute(f"PRAGMA index_info({row[1]})"))
        if columns == ("fingerprint",):
            return True
    return False


def ensure_signed_skill_schema(db: sqlite3.Connection, *, fresh: bool,
                               policy: bytes, now: int | None = None) -> None:
    """Initialize a truly fresh component or validate every established table."""
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    owned = {table for table in tables if table.startswith("signed_skill_")}
    present = tables & REQUIRED_TABLES
    if fresh:
        if owned:
            fail("skill_unmarked_schema_rejected")
        if now is None or not timestamp(now):
            fail("skill_clock_invalid")
        for statement in CREATE_STATEMENTS:
            db.execute(statement)
        db.execute("INSERT INTO signed_skill_policy VALUES(1,?,?,0)", (policy, now))
        return

    if present != REQUIRED_TABLES or owned != REQUIRED_TABLES:
        fail("skill_registry_schema_integrity_invalid")
    try:
        if (any(_columns(db, table) != columns
                for table, columns in EXPECTED_COLUMNS.items())
                or not _unique_fingerprint(db)):
            fail("skill_registry_schema_integrity_invalid")
        event_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='signed_skill_events'"
        ).fetchone()
        policy_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='signed_skill_policy'"
        ).fetchone()
        normalized_policy = "" if policy_sql is None else "".join(str(policy_sql[0]).upper().split())
        if (event_sql is None or "AUTOINCREMENT" not in str(event_sql[0]).upper()
                or "CHECK(ID=1)" not in normalized_policy):
            fail("skill_registry_schema_integrity_invalid")
        rows = db.execute(
            "SELECT id,policy,last_time,suspended FROM signed_skill_policy"
        ).fetchall()
    except sqlite3.DatabaseError:
        fail("skill_registry_schema_integrity_invalid")
    try:
        if (len(rows) != 1 or rows[0]["id"] != 1
                or not timestamp(rows[0]["last_time"])
                or type(rows[0]["suspended"]) is not int
                or rows[0]["suspended"] not in (0, 1)):
            fail("skill_registry_schema_integrity_invalid")
        stored_policy = bytes(rows[0]["policy"])
    except (TypeError, ValueError, IndexError, KeyError):
        fail("skill_registry_schema_integrity_invalid")
    if stored_policy != policy:
        fail("skill_registry_policy_migration_required")
