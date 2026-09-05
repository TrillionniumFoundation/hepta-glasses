"""Persistent component identity rejects complete Memory authority-table loss."""
from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.skills.durable_memory import (
    DurableMemoryConsent,
    DurableMemoryStore,
)
from services.skills.test_durable_memory import Cipher


class DurableMemoryComponentIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "memory.sqlite")
        self.cipher = Cipher()

    def populated(self) -> None:
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        store.grant_consent(DurableMemoryConsent(
            "u", "p", frozenset({"personal"}), 1000))
        record = store.remember(subject="u", purpose="p", data_class="personal",
                                value="fixture", ttl_seconds=50)
        store.delete(subject="u", memory_id=record.memory_id)
        store.close()

    def drop_all(self, *, vacuum: bool = False) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            for table in ("memory_deletions", "memory_records",
                          "memory_consents", "memory_schema"):
                db.execute("DROP TABLE " + table)
            if vacuum:
                db.execute("VACUUM")

    def test_full_table_loss_is_not_treated_as_fresh(self):
        self.populated()
        self.drop_all()
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)

    def test_vacuum_after_full_loss_does_not_remove_component_identity(self):
        self.populated()
        self.drop_all(vacuum=True)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertNotEqual(db.execute("PRAGMA application_id").fetchone()[0], 0)
        with self.assertRaisesRegex(ValueError, "schema_integrity_invalid"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)

    def test_intact_pre_marker_database_adopts_identity_without_row_loss(self):
        self.populated()
        with closing(sqlite3.connect(self.path)) as db, db:
            event = tuple(db.execute("SELECT * FROM memory_deletions").fetchone())
            db.execute("PRAGMA application_id=0")
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        self.addCleanup(store.close)
        self.assertNotEqual(store.db.execute("PRAGMA application_id").fetchone()[0], 0)
        self.assertEqual(tuple(store.db.execute(
            "SELECT * FROM memory_deletions").fetchone()), event)

    def test_conflicting_application_identity_is_rejected(self):
        store = DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)
        store.db.execute("PRAGMA application_id=7")
        store.close()
        with self.assertRaisesRegex(ValueError, "application_id_conflict"):
            DurableMemoryStore(self.path, cipher=self.cipher, clock=lambda: 100)


if __name__ == "__main__":
    unittest.main()
