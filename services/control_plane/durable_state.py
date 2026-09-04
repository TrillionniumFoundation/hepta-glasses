"""Small SQLite transaction primitive for trusted-host authority repositories.

Database directories are operator-owned, local storage. This is not a defense
against a hostile kernel or an attacker replacing the configured directory.
"""
from __future__ import annotations

import math
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def identifier(value: object, maximum: int = 256) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value == value.strip()
        and not any(ord(character) < 32 for character in value)
    )


def timestamp(value: object) -> bool:
    return type(value) is int and 0 <= value <= 253402300799


def deadline(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and 0 < value <= 60
    )


class DurableDatabase:
    """Serialize each connection and acquire the DB write lock before admission.

    Separate instances/processes on the same local database are serialized by
    BEGIN IMMEDIATE, not by the process-local RLock. Network calls never run
    inside a database transaction. FULL + WAL are checked, not just requested.
    """

    def __init__(self, path: str) -> None:
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("durable_database_path_required")
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False, timeout=5
        )
        self.db.row_factory = sqlite3.Row
        try:
            mode = self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            if mode != "wal" or self.db.execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise ValueError("durable_database_configuration_unavailable")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS hepta_component_schema("
                "component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def version(self, component: str, expected: int) -> bool:
        """Call inside migration transaction. True means known pre-marker schema."""
        row = self.db.execute(
            "SELECT version FROM hepta_component_schema WHERE component=?",
            (component,),
        ).fetchone()
        if row is not None and row["version"] != expected:
            raise ValueError(f"{component}_schema_migration_required")
        return row is None

    def mark_version(self, component: str, version: int) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO hepta_component_schema VALUES(?,?)",
            (component, version),
        )

    def close(self) -> None:
        with self.lock:
            self.db.close()
