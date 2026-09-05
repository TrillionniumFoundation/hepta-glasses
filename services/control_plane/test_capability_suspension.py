"""Real SQLite, transaction, restart and race regressions; no provider effects."""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.capabilities import (
    CapabilityError, CapabilityRequest, CapabilitySpec, DecisionLease,
    RiskTier, TrustClass, canonical_digest,
)
from services.control_plane.capability_suspension import (
    CONTROL_TABLE, LEGACY_TABLES, VERSION, migrate_capability_v1,
)
from services.control_plane.durable_capabilities import DurableCapabilityGateway
from services.control_plane.durable_state import DurableDatabase
from services.control_plane.test_durable_capabilities import Adapter


class CapabilitySuspensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'capabilities.sqlite')
        self.now = 1000
        self.gateway, self.adapter = self.open()
        self.request = CapabilityRequest('request', 'task', 'user', 'device', 'reminder.create',
            {'title': 'inert fixture'}, 'key', 1100, TrustClass.USER)

    def open(self, **changes):
        arguments = dict(clock=lambda: self.now, maximum_operations=1)
        arguments.update(changes)
        gateway = DurableCapabilityGateway(self.path, **arguments)
        self.addCleanup(gateway.close)
        adapter = Adapter()
        gateway.register(CapabilitySpec('reminder.create', RiskTier.R2, True, frozenset({'title'})),
                         provider_id='reminder-v1', adapter=adapter)
        return gateway, adapter

    def execute(self, gateway=None, **changes):
        request = dataclasses.replace(self.request, **changes)
        lease = DecisionLease('lease-' + request.idempotency_key, request.subject, request.device_id,
            request.task_id, request.name, canonical_digest(dict(request.arguments)), 1100, False)
        return (gateway or self.gateway).execute(request, lease=lease)

    def fill_and_suspend(self, gateway=None):
        gateway = gateway or self.gateway
        gateway.revoke_subject('first-user')
        self.error('capability_revocation_capacity_exhausted', lambda: gateway.revoke_subject('user'))
        return gateway.suspension_status()

    def rows(self, table):
        with self.gateway.store.transaction() as db:
            return [tuple(r) for r in db.execute('SELECT * FROM ' + table)]

    def error(self, code, callback):
        with self.assertRaises(CapabilityError) as result:
            callback()
        self.assertEqual(result.exception.code, code)

    def legacy_fixture(self):
        # Retain the exact v1 four-table schema; remove only the v2 addition to
        # model an existing v1 database. A separate integration probe uses the
        # hash-verified previous implementation to create a real predecessor.
        with self.gateway.store.transaction() as db:
            db.execute('DROP TABLE ' + CONTROL_TABLE)
            db.execute("UPDATE hepta_component_schema SET version=1 WHERE component='durable_capabilities'")

    def test_full_revocation_inventory_blocks_previously_unrevoked_subject(self):
        receipt = self.fill_and_suspend()
        self.assertEqual(receipt, {'suspended': True, 'reason': 'revocation_capacity'})
        self.error('capability_dispatch_suspended', self.execute)
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(len(self.rows('hg_capability_revoked')), 1)
        self.assertEqual(len(self.rows('hg_capability_operations')), 0)

    def test_normal_and_duplicate_subject_revocation_are_explicit(self):
        first = self.gateway.revoke_subject('user')
        self.assertIsNone(first)
        self.assertEqual(first, self.gateway.revoke_subject('user'))
        self.assertFalse(self.gateway.suspension_status()['suspended'])
        self.assertEqual(self.execute().status, 'denied')

    def test_repeated_suspension_never_grows_state_or_changes_reason(self):
        self.fill_and_suspend()
        original = self.rows(CONTROL_TABLE)
        for index in range(20):
            self.error('capability_revocation_capacity_exhausted',
                       lambda: self.gateway.revoke_subject('later-' + str(index)))
        self.assertEqual(original, self.rows(CONTROL_TABLE))
        self.assertEqual(len(self.rows(CONTROL_TABLE)), 1)
        self.assertEqual(len(self.rows('hg_capability_revoked')), 1)

    def test_suspension_survives_new_connection_with_larger_capacity(self):
        self.fill_and_suspend()
        other, adapter = self.open(maximum_operations=100)
        self.error('capability_dispatch_suspended', lambda: self.execute(other))
        self.assertEqual(adapter.calls, 0)
        self.assertTrue(other.suspension_status()['suspended'])

    def test_concurrent_last_slot_revocations_commit_global_denial(self):
        other, _ = self.open()
        barrier, results, errors = threading.Barrier(2), [], []
        def worker(gateway, subject):
            try:
                barrier.wait()
                try:
                    gateway.revoke_subject(subject)
                    results.append('subject')
                except CapabilityError as error:
                    if error.code != 'capability_revocation_capacity_exhausted':
                        raise
                    results.append('gateway')
            except BaseException as error:
                errors.append(error)
        threads = [threading.Thread(target=worker, args=(self.gateway, 'first-user')),
                   threading.Thread(target=worker, args=(other, 'user'))]
        for thread in threads: thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ['gateway', 'subject'])
        self.error('capability_dispatch_suspended', self.execute)
        self.assertEqual(len(self.rows('hg_capability_revoked')), 1)

    def test_suspension_between_reservation_and_worker_blocks_dispatch(self):
        original = self.gateway._calls.run
        def interrupt(operation, **kwargs):
            self.fill_and_suspend()
            return original(operation, **kwargs)
        with patch.object(self.gateway._calls, 'run', side_effect=interrupt):
            receipt = self.execute()
        self.assertEqual(receipt.status, 'failed')
        self.assertEqual(self.adapter.calls, 0)
        self.assertTrue(self.execute().replayed)

    def test_suspension_during_adapter_preparation_fences_authorized_callback(self):
        called = []
        def execute_authorized(request, operation_id, *, authorize):
            self.fill_and_suspend()
            authorize()
            called.append(True)
            return self.adapter.execute(request, operation_id)
        self.adapter.execute_authorized = execute_authorized
        receipt = self.execute()
        self.assertEqual(receipt.status, 'indeterminate')
        self.assertEqual(called, [])
        self.assertEqual(self.adapter.calls, 0)

    def test_already_admitted_effect_is_not_falsified_by_later_suspension(self):
        original = self.adapter.execute
        def execute_then_suspend(request, operation_id):
            result = original(request, operation_id)
            self.fill_and_suspend()
            return result
        with patch.object(self.adapter, 'execute', side_effect=execute_then_suspend):
            receipt = self.execute()
        self.assertEqual(receipt.status, 'succeeded')
        self.assertEqual(self.execute().result, receipt.result)
        self.assertEqual(self.adapter.calls, 1)

    def test_existing_uncertainty_allows_readback_but_never_redispatch(self):
        self.adapter.failure = True
        self.assertEqual(self.execute().status, 'indeterminate')
        self.adapter.failure = False
        self.fill_and_suspend()
        self.assertEqual(self.execute().status, 'indeterminate')
        self.assertEqual(self.gateway.reconcile(self.request).status, 'succeeded')
        self.assertEqual((self.adapter.calls, self.adapter.reads), (1, 1))

    def test_full_operation_storage_does_not_prevent_suspension(self):
        self.execute()
        receipt = self.fill_and_suspend()
        self.assertTrue(receipt['suspended'])
        self.error('capability_dispatch_suspended', lambda: self.execute(idempotency_key='new'))
        self.assertEqual(len(self.rows('hg_capability_operations')), 1)

    def test_invalid_clock_still_allows_conservative_global_denial(self):
        self.now = True
        self.error('capability_clock_invalid', lambda: self.gateway.revoke_subject('user'))
        self.assertEqual(self.gateway.suspension_status(), {'suspended': True, 'reason': 'clock_unavailable'})
        self.error('capability_dispatch_suspended', self.execute)
        self.assertEqual(self.rows('hg_capability_revoked'), [])

    def test_clock_exception_text_is_not_stored_or_returned(self):
        def broken_clock():
            raise RuntimeError('private-clock-error-marker')
        self.gateway.clock = broken_clock
        self.error('capability_clock_invalid', lambda: self.gateway.revoke_subject('user'))
        receipt = self.gateway.suspension_status()
        self.assertEqual(receipt['reason'], 'clock_unavailable')
        self.assertNotIn('private-clock-error-marker', json.dumps(receipt))
        for path in Path(self.temp.name).glob('capabilities.sqlite*'):
            self.assertNotIn(b'private-clock-error-marker', path.read_bytes())

    def test_suspension_write_failure_is_not_acknowledged(self):
        self.gateway.revoke_subject('first-user')
        with self.gateway.store.transaction() as db:
            db.execute("CREATE TRIGGER refuse_control BEFORE UPDATE ON hg_capability_control BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.gateway.revoke_subject('user')
        self.assertFalse(self.gateway.suspension_status()['suspended'])
        self.assertEqual(len(self.rows('hg_capability_revoked')), 1)

    def test_missing_control_row_fails_without_reinitialization(self):
        with self.gateway.store.transaction() as db:
            db.execute('DELETE FROM ' + CONTROL_TABLE)
        with self.assertRaisesRegex(ValueError, 'capability_control_integrity_invalid'):
            self.open()
        with self.assertRaisesRegex(ValueError, 'capability_control_integrity_invalid'):
            self.execute()
        self.assertEqual(self.rows(CONTROL_TABLE), [])

    def test_missing_control_table_fails_startup(self):
        with self.gateway.store.transaction() as db:
            db.execute('DROP TABLE ' + CONTROL_TABLE)
        with self.assertRaisesRegex(ValueError, 'capability_schema_integrity_invalid'):
            self.open()
        with self.gateway.store.transaction() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (CONTROL_TABLE,)).fetchone())

    def test_normal_startup_never_implicitly_migrates_v1(self):
        self.legacy_fixture()
        with self.assertRaisesRegex(ValueError, 'schema_migration_required'):
            self.open()
        with self.gateway.store.transaction() as db:
            self.assertEqual(db.execute("SELECT version FROM hepta_component_schema WHERE component='durable_capabilities'").fetchone()[0], 1)
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (CONTROL_TABLE,)).fetchone())

    def test_explicit_migration_preserves_every_existing_row(self):
        self.execute()
        self.gateway.revoke_subject('first-user')
        self.legacy_fixture()
        before = {t: self.rows(t) for t in LEGACY_TABLES}
        report = migrate_capability_v1(self.path)
        self.assertEqual(report['to_version'], VERSION)
        self.assertEqual(before, {t: self.rows(t) for t in LEGACY_TABLES})
        other, adapter = self.open()
        self.assertTrue(self.execute(other).replayed)
        self.assertEqual(adapter.calls, 0)
        self.error('capability_revocation_capacity_exhausted', lambda: other.revoke_subject('user'))
        self.assertTrue(other.suspension_status()['suspended'])

    def test_migration_failure_rolls_back_new_table_and_version(self):
        self.legacy_fixture()
        with self.gateway.store.transaction() as db:
            db.execute("CREATE TRIGGER refuse_version BEFORE UPDATE ON hepta_component_schema BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            migrate_capability_v1(self.path)
        with self.gateway.store.transaction() as db:
            self.assertEqual(db.execute("SELECT version FROM hepta_component_schema WHERE component='durable_capabilities'").fetchone()[0], 1)
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (CONTROL_TABLE,)).fetchone())

    def test_migration_rejects_missing_legacy_table(self):
        self.legacy_fixture()
        with self.gateway.store.transaction() as db:
            db.execute('DROP TABLE hg_capability_revoked')
        with self.assertRaisesRegex(ValueError, 'capability_migration_schema_invalid'):
            migrate_capability_v1(self.path)

    def test_migration_never_creates_a_missing_database(self):
        path = str(Path(self.temp.name) / 'missing.sqlite')
        with self.assertRaisesRegex(ValueError, 'existing_file_required'):
            migrate_capability_v1(path)
        self.assertFalse(Path(path).exists())

    def test_migration_rejects_symlink_database(self):
        link = Path(self.temp.name) / 'linked.sqlite'
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, 'existing_file_required'):
            migrate_capability_v1(str(link))

    def test_migration_cannot_reset_an_already_suspended_v2_database(self):
        self.fill_and_suspend()
        with self.assertRaisesRegex(ValueError, 'capability_migration_schema_invalid'):
            migrate_capability_v1(self.path)
        self.assertTrue(self.gateway.suspension_status()['suspended'])

    def test_migration_rejects_unknown_version_without_creating_control(self):
        self.legacy_fixture()
        with self.gateway.store.transaction() as db:
            db.execute("UPDATE hepta_component_schema SET version=99 WHERE component='durable_capabilities'")
        with self.assertRaisesRegex(ValueError, 'capability_migration_version_invalid'):
            migrate_capability_v1(self.path)
        with self.gateway.store.transaction() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (CONTROL_TABLE,)).fetchone())

    def test_old_binary_version_gate_rejects_migrated_v2(self):
        self.legacy_fixture()
        migrate_capability_v1(self.path)
        store = DurableDatabase(self.path)
        try:
            with store.transaction(), self.assertRaisesRegex(ValueError, 'schema_migration_required'):
                store.version('durable_capabilities', 1)
        finally:
            store.close()

    def test_actual_process_exit_after_suspension_preserves_denial(self):
        script = """
import os,sys
from services.control_plane.durable_capabilities import DurableCapabilityGateway
g=DurableCapabilityGateway(sys.argv[1],clock=lambda:1000,maximum_operations=1)
g.revoke_subject('first-user')
try:
 g.revoke_subject('user')
except Exception as e:
 assert e.code == 'capability_revocation_capacity_exhausted'
os._exit(23)
"""
        result = subprocess.run([sys.executable, '-c', script, self.path], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        other, adapter = self.open()
        self.error('capability_dispatch_suspended', lambda: self.execute(other))
        self.assertEqual(adapter.calls, 0)


if __name__ == '__main__':
    unittest.main()
