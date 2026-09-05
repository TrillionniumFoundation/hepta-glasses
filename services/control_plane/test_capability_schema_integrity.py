"""Reject incomplete capability state; not a claim of backup anti-rollback."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from services.control_plane.durable_capabilities import DurableCapabilityGateway


class CapabilitySchemaIntegrityTests(unittest.TestCase):
    def missing(self, table):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'state.sqlite')
            gateway = DurableCapabilityGateway(path, clock=lambda: 1000)
            gateway.revoke_subject('fixture-subject')
            gateway.close()
            with sqlite3.connect(path) as db:
                db.execute('DROP TABLE ' + table)
            with self.assertRaisesRegex(ValueError, 'capability_schema_integrity_invalid'):
                DurableCapabilityGateway(path, clock=lambda: 1000)
            with sqlite3.connect(path) as db:
                self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone())
                self.assertEqual(db.execute("SELECT version FROM hepta_component_schema WHERE component='durable_capabilities'").fetchone()[0], 1)

    def test_missing_revocations_not_recreated(self):
        self.missing('hg_capability_revoked')

    def test_missing_leases_not_recreated(self):
        self.missing('hg_capability_leases')

    def test_missing_operations_not_recreated(self):
        self.missing('hg_capability_operations')

    def test_missing_audit_events_not_recreated(self):
        self.missing('hg_capability_events')

    def test_intact_reopen_preserves_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'state.sqlite')
            gateway = DurableCapabilityGateway(path, clock=lambda: 1000)
            gateway.revoke_subject('fixture-subject')
            gateway.close()
            gateway = DurableCapabilityGateway(path, clock=lambda: 1000)
            try:
                self.assertEqual(gateway.store.db.execute('SELECT COUNT(*) FROM hg_capability_revoked').fetchone()[0], 1)
            finally:
                gateway.close()

    def test_failed_open_releases_write_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'state.sqlite')
            gateway = DurableCapabilityGateway(path, clock=lambda: 1000)
            gateway.close()
            with sqlite3.connect(path) as db:
                db.execute('DROP TABLE hg_capability_leases')
            with self.assertRaises(ValueError):
                DurableCapabilityGateway(path, clock=lambda: 1000)
            with sqlite3.connect(path, timeout=0.1) as db:
                db.execute('BEGIN IMMEDIATE')
                db.rollback()


if __name__ == '__main__':
    unittest.main()
