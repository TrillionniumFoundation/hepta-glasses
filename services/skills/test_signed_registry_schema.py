"""Fail-closed schema regressions; no package verification or production keys."""
from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.skills.signed_package import PublisherKey, SPKI_PREFIX, SignedSkillError
from services.skills.signed_registry import SignedSkillRegistry
from services.skills.signed_registry_schema import REQUIRED_TABLES


class SignedRegistrySchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.keys = {
            "publisher-v1": PublisherKey(
                "publisher", SPKI_PREFIX + b"k" * 32, 900, 2000
            )
        }

    def path(self, name: str = "registry.sqlite") -> str:
        return str(Path(self.temp.name) / name)

    def open(self, path: str | None = None, **changes) -> SignedSkillRegistry:
        options = dict(
            subject="user",
            keys=self.keys,
            allowed_capabilities=frozenset({"display.text"}),
            allowed_domains=frozenset({"service.example"}),
            clock=lambda: 1000,
        )
        options.update(changes)
        return SignedSkillRegistry(path or self.path(), **options)

    def initialize(self, path: str | None = None) -> str:
        path = path or self.path()
        registry = self.open(path)
        registry.close()
        return path

    def error(self, code: str, callback) -> None:
        with self.assertRaises(SignedSkillError) as result:
            callback()
        self.assertEqual(result.exception.code, code)

    @staticmethod
    def tables(path: str) -> set[str]:
        with closing(sqlite3.connect(path)) as db:
            return {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}

    def test_fresh_database_initializes_and_intact_database_reopens(self):
        path = self.path()
        first = self.open(path)
        try:
            self.assertTrue(REQUIRED_TABLES <= self.tables(path))
            self.assertEqual(first.storage.db.execute(
                "SELECT COUNT(*) FROM signed_skill_keys"
            ).fetchone()[0], 1)
        finally:
            first.close()
        second = self.open(path)
        try:
            self.assertEqual(second.storage.db.execute(
                "SELECT suspended FROM signed_skill_policy WHERE id=1"
            ).fetchone()[0], 0)
        finally:
            second.close()

    def test_each_missing_authority_table_is_rejected_not_recreated(self):
        for table in sorted(REQUIRED_TABLES):
            with self.subTest(table=table):
                path = self.initialize(self.path(table + ".sqlite"))
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("DROP TABLE " + table)
                self.error(
                    "skill_registry_schema_integrity_invalid",
                    lambda p=path: self.open(p),
                )
                self.assertNotIn(table, self.tables(path))

    def test_all_authority_tables_missing_with_marker_are_not_recreated(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            for table in REQUIRED_TABLES:
                db.execute("DROP TABLE " + table)
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))
        self.assertFalse(REQUIRED_TABLES & self.tables(path))
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute(
                "SELECT version FROM hepta_component_schema WHERE component='signed_skills'"
            ).fetchone()[0], 1)

    def test_unknown_unmarked_component_table_blocks_fresh_initialization(self):
        path = self.path()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE signed_skill_legacy(value TEXT)")
        self.error("skill_unmarked_schema_rejected", lambda: self.open(path))
        self.assertEqual(self.tables(path) & REQUIRED_TABLES, set())

    def test_unknown_extra_component_table_blocks_established_reopen(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE signed_skill_unreviewed(value TEXT)")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))
        self.assertIn("signed_skill_unreviewed", self.tables(path))

    def test_removed_component_marker_with_tables_is_unmarked_state(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DELETE FROM hepta_component_schema WHERE component='signed_skills'")
        self.error("skill_unmarked_schema_rejected", lambda: self.open(path))
        self.assertEqual(REQUIRED_TABLES & self.tables(path), REQUIRED_TABLES)

    def test_missing_policy_singleton_is_not_reinserted(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DELETE FROM signed_skill_policy")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM signed_skill_policy"
            ).fetchone()[0], 0)

    def test_multiple_policy_rows_are_rejected(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            row = db.execute(
                "SELECT policy,last_time,suspended FROM signed_skill_policy"
            ).fetchone()
            db.execute("ALTER TABLE signed_skill_policy RENAME TO old_policy")
            db.execute(
                "CREATE TABLE signed_skill_policy(id INTEGER PRIMARY KEY,policy BLOB NOT NULL,"
                "last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)"
            )
            db.execute("INSERT INTO signed_skill_policy VALUES(1,?,?,?)", row)
            db.execute("INSERT INTO signed_skill_policy VALUES(2,?,?,?)", row)
            db.execute("DROP TABLE old_policy")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))

    def test_policy_singleton_constraint_is_required(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            row = db.execute(
                "SELECT id,policy,last_time,suspended FROM signed_skill_policy"
            ).fetchone()
            db.execute("ALTER TABLE signed_skill_policy RENAME TO old_policy")
            db.execute(
                "CREATE TABLE signed_skill_policy(id INTEGER PRIMARY KEY,policy BLOB NOT NULL,"
                "last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)"
            )
            db.execute("INSERT INTO signed_skill_policy VALUES(?,?,?,?)", row)
            db.execute("DROP TABLE old_policy")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))

    def test_invalid_policy_state_is_rejected(self):
        for column, value in (("suspended", 2), ("last_time", "bad")):
            with self.subTest(column=column):
                path = self.initialize(self.path(column + ".sqlite"))
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(f"UPDATE signed_skill_policy SET {column}=?", (value,))
                self.error("skill_registry_schema_integrity_invalid", lambda p=path: self.open(p))

    def test_policy_configuration_drift_keeps_existing_error_contract(self):
        path = self.initialize()
        self.error(
            "skill_registry_policy_migration_required",
            lambda: self.open(path, allowed_domains=frozenset()),
        )

    def test_key_fingerprint_unique_constraint_is_required(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            rows = db.execute("SELECT id,fingerprint,binding FROM signed_skill_keys").fetchall()
            db.execute("ALTER TABLE signed_skill_keys RENAME TO old_keys")
            db.execute(
                "CREATE TABLE signed_skill_keys(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,"
                "binding BLOB NOT NULL)"
            )
            db.executemany("INSERT INTO signed_skill_keys VALUES(?,?,?)", rows)
            db.execute("DROP TABLE old_keys")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))

    def test_event_autoincrement_custody_is_required(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("ALTER TABLE signed_skill_events RENAME TO old_events")
            db.execute(
                "CREATE TABLE signed_skill_events(sequence INTEGER PRIMARY KEY,event TEXT NOT NULL,"
                "target TEXT NOT NULL,digest TEXT NOT NULL,observed_at INTEGER NOT NULL,"
                "previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)"
            )
            db.execute("DROP TABLE old_events")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))

    def test_changed_columns_are_rejected(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("ALTER TABLE signed_skill_installed ADD COLUMN unexpected TEXT")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))

    def test_suspension_and_last_time_survive_reopen(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "UPDATE signed_skill_policy SET last_time=1234,suspended=1 WHERE id=1"
            )
        registry = self.open(path)
        try:
            row = registry.storage.db.execute(
                "SELECT last_time,suspended FROM signed_skill_policy WHERE id=1"
            ).fetchone()
            self.assertEqual(tuple(row), (1234, 1))
            self.assertEqual(registry.verify_local_audit()["events"], 0)
        finally:
            registry.close()

    def test_failed_constructor_releases_database_write_lock(self):
        path = self.initialize()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DROP TABLE signed_skill_revocations")
        self.error("skill_registry_schema_integrity_invalid", lambda: self.open(path))
        with closing(sqlite3.connect(path, isolation_level=None, timeout=0.1)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("ROLLBACK")

    def test_invalid_fresh_clock_creates_no_authority_tables(self):
        path = self.path()
        self.error("skill_clock_invalid", lambda: self.open(path, clock=lambda: True))
        self.assertFalse(REQUIRED_TABLES & self.tables(path))


if __name__ == "__main__":
    unittest.main()
