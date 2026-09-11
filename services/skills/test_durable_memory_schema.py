"""Established Memory authority state must never be reconstructed as empty."""
from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.skills.durable_memory import (
    DurableMemoryConsent,
    DurableMemoryError,
    DurableMemoryStore,
)
from services.skills.test_durable_memory import Cipher


class DurableMemorySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "memory.sqlite")
        self.cipher = Cipher()

    def open(self) -> DurableMemoryStore:
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        self.addCleanup(store.close)
        return store

    def populate(self) -> DurableMemoryStore:
        store = self.open()
        store.grant_consent(DurableMemoryConsent(
            "u", "p", frozenset({"personal"}), 1000))
        record = store.remember(subject="u", purpose="p", data_class="personal",
                                value="fixture", ttl_seconds=50)
        store.delete(subject="u", memory_id=record.memory_id)
        self.assertEqual(len(store.pending_deletions()), 1)
        return store

    def drop(self, table: str) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE " + table)

    def assert_missing_rejected(self, table: str) -> None:
        store = self.populate()
        store.close()
        self.drop(table)
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone())

    def test_missing_deletion_custody_is_not_recreated_empty(self):
        self.assert_missing_rejected("memory_deletions")

    def test_missing_records_are_not_recreated_empty(self):
        self.assert_missing_rejected("memory_records")

    def test_missing_consents_are_not_recreated_empty(self):
        self.assert_missing_rejected("memory_consents")

    def test_missing_schema_marker_is_not_recreated(self):
        self.assert_missing_rejected("memory_schema")

    def test_missing_schema_row_fails_closed(self):
        store = self.populate()
        store.db.execute("DELETE FROM memory_schema")
        store.close()
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM memory_schema").fetchone()[0], 0)

    def test_unknown_schema_version_requires_reviewed_migration(self):
        store = self.open()
        store.db.execute("UPDATE memory_schema SET version=2")
        store.close()
        with self.assertRaisesRegex(ValueError, "schema_migration_required"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)

    def test_malformed_existing_table_is_rejected(self):
        store = self.open()
        store.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("ALTER TABLE memory_records RENAME TO old_records")
            db.execute("CREATE TABLE memory_records(memory_id TEXT PRIMARY KEY, subject TEXT NOT NULL)")
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)

    def test_missing_event_uniqueness_is_rejected(self):
        store = self.open()
        store.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("ALTER TABLE memory_deletions RENAME TO old_deletions")
            db.execute("CREATE TABLE memory_deletions(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL,subject TEXT NOT NULL,memory_id TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL,state TEXT NOT NULL)")
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)

    def test_derived_indexes_may_be_rebuilt_without_losing_rows(self):
        store = self.populate()
        store.close()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP INDEX memory_records_subject")
            db.execute("DROP INDEX memory_deletions_pending")
        reopened = self.open()
        indexes = {row[0] for row in reopened.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("memory_records_subject", indexes)
        self.assertIn("memory_deletions_pending", indexes)
        self.assertEqual(len(reopened.pending_deletions()), 1)

    def test_intact_reopen_preserves_pending_deletion(self):
        store = self.populate()
        event = store.pending_deletions()[0]
        store.close()
        reopened = self.open()
        self.assertEqual(reopened.pending_deletions(), [event])

    def test_failed_constructor_releases_database_lock(self):
        store = self.open()
        store.close()
        self.drop("memory_consents")
        with self.assertRaises(ValueError):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        with closing(sqlite3.connect(self.path, timeout=0.1, isolation_level=None)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("ROLLBACK")

    def test_unrelated_existing_table_does_not_block_fresh_component(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
            db.execute("INSERT INTO unrelated VALUES('retained')")
        store = self.open()
        self.assertEqual(store.db.execute("SELECT value FROM unrelated").fetchone()[0], "retained")

    def test_remember_resamples_clock_after_database_lock(self):
        now = [100]
        first = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        second = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(first.close); self.addCleanup(second.close)
        first.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 200))
        import threading
        begun = threading.Event(); errors = []
        def run():
            try:
                begun.set()
                first.remember(subject="u", purpose="p", data_class="personal",
                               value="late", ttl_seconds=50)
            except DurableMemoryError as error:
                errors.append(error.code)
        with second._tx():
            worker = threading.Thread(target=run); worker.start()
            self.assertTrue(begun.wait(1)); now[0] = 201
        worker.join(2); self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["durable_memory_consent_missing"])
        self.assertEqual(first.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_grant_consent_resamples_clock_after_database_lock(self):
        now = [100]
        first = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        second = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(first.close); self.addCleanup(second.close)
        import threading
        begun = threading.Event(); errors = []
        def run():
            begun.set()
            try:
                first.grant_consent(DurableMemoryConsent(
                    "u", "p", frozenset({"personal"}), 200))
            except DurableMemoryError as error:
                errors.append(error.code)
        with second._tx():
            worker = threading.Thread(target=run); worker.start()
            self.assertTrue(begun.wait(1)); now[0] = 201
        worker.join(2); self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["durable_memory_consent_invalid"])
        self.assertEqual(first.db.execute("SELECT COUNT(*) FROM memory_consents").fetchone()[0], 0)

    def test_expiry_during_encrypt_rolls_back_ciphertext(self):
        now = [100]
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(store.close)
        store.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 1000))
        original = self.cipher.encrypt
        def late(**kwargs):
            value = original(**kwargs); now[0] = 151; return value
        self.cipher.encrypt = late
        with self.assertRaisesRegex(DurableMemoryError, "authority_expired"):
            store.remember(subject="u", purpose="p", data_class="personal",
                           value="late", ttl_seconds=50)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_expiry_after_insert_trigger_rolls_back_record(self):
        now = [100]
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(store.close)
        store.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 1000))
        store.db.create_function("advance_memory_clock", 0,
                                 lambda: (now.__setitem__(0, 151), 0)[1])
        store.db.execute("CREATE TRIGGER advance_after_memory_insert AFTER INSERT ON memory_records BEGIN SELECT advance_memory_clock(); END")
        with self.assertRaisesRegex(DurableMemoryError, "authority_expired"):
            store.remember(subject="u", purpose="p", data_class="personal",
                           value="late", ttl_seconds=50)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_search_never_returns_record_expired_during_decrypt(self):
        now = [100]
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(store.close)
        store.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 1000))
        store.remember(subject="u", purpose="p", data_class="personal",
                       value="short", ttl_seconds=2)
        original = self.cipher.decrypt
        def late(**kwargs):
            value = original(**kwargs); now[0] = 102; return value
        self.cipher.decrypt = late
        self.assertEqual(store.search(subject="u", purpose="p"), [])
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)
        self.assertEqual(store.pending_deletions()[0]["reason"], "expired")

    def test_export_never_returns_record_expired_during_decrypt(self):
        now = [100]
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(store.close)
        store.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 1000))
        store.remember(subject="u", purpose="p", data_class="personal",
                       value="short", ttl_seconds=2)
        original = self.cipher.decrypt
        self.cipher.decrypt = lambda **kwargs: (now.__setitem__(0, 102), original(**kwargs))[1]
        self.assertEqual(store.export(subject="u"), [])
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_clock_rollback_during_encrypt_rolls_back(self):
        now = [100]
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: now[0])
        self.addCleanup(store.close)
        store.grant_consent(DurableMemoryConsent("u", "p", frozenset({"personal"}), 1000))
        original = self.cipher.encrypt
        def rollback(**kwargs):
            value = original(**kwargs); now[0] = 99; return value
        self.cipher.encrypt = rollback
        with self.assertRaisesRegex(DurableMemoryError, "clock_rollback"):
            store.remember(subject="u", purpose="p", data_class="personal",
                           value="x", ttl_seconds=50)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0], 0)

    def test_invalid_unicode_value_is_fixed_error(self):
        store = self.open()
        store.grant_consent(DurableMemoryConsent(
            "u", "p", frozenset({"personal"}), 1000))
        with self.assertRaisesRegex(DurableMemoryError, "value_invalid"):
            store.remember(subject="u", purpose="p", data_class="personal",
                           value="\ud800", ttl_seconds=50)


if __name__ == "__main__":
    unittest.main()
