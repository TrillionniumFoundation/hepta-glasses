"""Real SQLite namespace/migration tests; no credentials or provider evidence."""
from __future__ import annotations

from contextlib import closing
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.durable_realtime import DurableRealtimeStore, DurableRealtimeError, RealtimeActivation
from services.control_plane.realtime_provider_binding import migrate_realtime_v3, VERSION
from services.control_plane import realtime_recovery as recovery


class Provider:
    def __init__(self, binding='fixture-a'):
        self.binding_id = binding
        self.activations = self.lookups = 0
        self.revokes = []
        self.before = lambda: None
        self.before_lookup = lambda: None
        self.before_revoke = lambda: None
        self.result = RealtimeActivation('remote-a', 'receipt-a')
        self.fail_revoke = False

    def activate(self, **kwargs):
        self.activations += 1
        self.before()
        return self.result

    def reconcile_activation(self, **kwargs):
        self.lookups += 1
        self.before_lookup()
        return self.result

    def revoke(self, *, provider_session_id, timeout_seconds):
        self.revokes.append(provider_session_id)
        self.before_revoke()
        if self.fail_revoke:
            raise TimeoutError('fixture only')


class RealtimeProviderBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'r.db')
        self.p = Provider()
        self.s = self.open()

    def open(self, **changes):
        options = dict(provider=self.p, provider_binding='fixture-a', clock=lambda:1000)
        options.update(changes)
        store = DurableRealtimeStore(self.path, **options)
        self.addCleanup(store.close)
        return store

    def activate(self, sid='s'):
        ticket = self.s.issue_ticket(subject='user', session_id=sid)
        return self.s.activate(ticket=ticket, subject='user', session_id=sid)

    def uncertain(self):
        self.p.result = None
        with self.assertRaises(DurableRealtimeError):
            self.activate()
        self.p.result = RealtimeActivation('remote-a', 'receipt-a')

    def rows(self):
        return {table: [tuple(row) for row in self.s.db.execute('SELECT * FROM ' + table)]
                for table in sorted(recovery.LEGACY_TABLES | recovery.BUDGET_TABLES)}

    def legacy(self):
        # A separate delivered probe creates genuine v3 using the exact parent
        # implementation. These fixtures retain its seven table layouts/values.
        with self.s._storage.transaction():
            self.s.db.execute('DROP TABLE realtime_provider_scope')
            self.s.db.execute("UPDATE hepta_component_schema SET version=3 WHERE component='realtime'")

    def test_binding_required_without_implicit_default(self):
        with self.assertRaises(TypeError):
            DurableRealtimeStore(self.path, provider=self.p, clock=lambda:1000)

    def test_correct_binding_survives_restart(self):
        self.activate()
        other = self.open(provider=Provider())
        self.assertEqual(other.provider_binding, 'fixture-a')
        self.assertEqual(other.require_generation('s', 1)['state'], 'active')
        self.assertEqual(self.s.db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()[0], VERSION)

    def test_wrong_namespace_reopen_cannot_cancel_an_existing_session(self):
        self.activate()
        b = Provider('fixture-b')
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.open(provider=b, provider_binding='fixture-b')
        self.assertEqual(self.rows(), before)
        self.assertEqual(b.revokes, [])

    def test_declared_adapter_must_match_host_binding_before_database_open(self):
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.open(provider=Provider('fixture-b'))
        self.assertEqual(self.rows(), before)

    def test_legacy_adapter_without_binding_id_needs_explicit_trusted_binding(self):
        del self.p.binding_id
        other = self.open()
        self.assertIs(other.provider, self.p)
        self.activate()
        self.assertEqual(self.p.activations, 1)

    def test_binding_value_type_size_and_url_rejected(self):
        for binding in ('', True, None, [], 'a/b', 'a b', 'a\nb', 'x'*129):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValueError, 'provider_binding_invalid'):
                self.open(provider_binding=binding)

    def test_adapter_binding_none_is_not_implicit_legacy(self):
        self.p.binding_id = None
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.open()

    def test_adapter_binding_failure_is_sanitized(self):
        class Bad:
            @property
            def binding_id(self):
                raise RuntimeError('fixture-private-binding-text')
        with self.assertRaisesRegex(ValueError, '^realtime_provider_configuration_invalid$') as error:
            self.open(provider=Bad())
        self.assertTrue(error.exception.__suppress_context__)
        for path in Path(self.tmp.name).glob('r.db*'):
            self.assertNotIn(b'fixture-private-binding-text', path.read_bytes())

    def test_public_binding_and_provider_are_readonly(self):
        with self.assertRaises(AttributeError):
            self.s.provider = Provider('fixture-b')
        with self.assertRaises(AttributeError):
            self.s.provider_binding = 'fixture-b'

    def test_provider_drift_blocks_new_ticket_without_writes(self):
        self.p.binding_id = 'fixture-b'
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.issue_ticket(subject='user', session_id='s')
        self.assertEqual(self.rows(), before)

    def test_provider_drift_after_scheduling_never_dispatches(self):
        ticket = self.s.issue_ticket(subject='user', session_id='s')
        original = self.s._calls.run
        def drift(operation, **kwargs):
            self.p.binding_id = 'fixture-b'
            return original(operation, **kwargs)
        with patch.object(self.s._calls, 'run', side_effect=drift):
            with self.assertRaisesRegex(DurableRealtimeError, 'activation_indeterminate'):
                self.s.activate(ticket=ticket, subject='user', session_id='s')
        self.assertEqual(self.p.activations, 0)
        self.assertEqual(self.s.pending_recovery(), ['s'])

    def test_provider_drift_during_activation_cannot_commit_success(self):
        self.p.before = lambda: setattr(self.p, 'binding_id', 'fixture-b')
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.activate()
        self.assertEqual(self.s.db.execute('SELECT state FROM sessions').fetchone()[0], 'activating')
        self.assertEqual(self.s.pending_recovery(), ['s'])

    def test_provider_drift_at_final_active_update_rolls_back(self):
        self.s.db.create_function('binding_drift', 0, lambda:(setattr(self.p,'binding_id','fixture-b'),0)[1])
        self.s.db.execute("CREATE TRIGGER change_binding AFTER UPDATE ON sessions WHEN NEW.state='active' BEGIN SELECT binding_drift(); END")
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.activate()
        self.assertEqual(self.s.db.execute('SELECT state FROM sessions').fetchone()[0], 'activating')

    def test_provider_drift_blocks_readback_but_keeps_spent_budget(self):
        self.uncertain()
        self.p.binding_id = 'fixture-b'
        with self.assertRaisesRegex(DurableRealtimeError, 'activation_indeterminate'):
            self.s.reconcile('s')
        self.assertEqual(self.p.lookups, 0)
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'], 1)

    def test_provider_drift_during_readback_never_promotes_result(self):
        self.uncertain()
        self.p.before_lookup = lambda:setattr(self.p,'binding_id','fixture-b')
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.reconcile('s')
        self.assertEqual(self.s.recovery_status('s')['state'], 'indeterminate')

    def test_local_revoke_commits_despite_adapter_drift_no_wrong_remote_call(self):
        self.activate()
        self.p.binding_id = 'fixture-b'
        with self.assertRaisesRegex(DurableRealtimeError, 'provider_revoke_pending'):
            self.s.revoke('s')
        report = self.s.recovery_status('s')
        self.assertEqual(report['state'], 'revoked')
        self.assertEqual(report['cleanup']['pending'], 1)
        self.assertEqual(self.p.revokes, [])

    def test_cleanup_drift_after_reservation_never_calls_wrong_namespace(self):
        self.activate()
        original = self.s._calls.run
        def drift(operation, **kwargs):
            self.p.binding_id = 'fixture-b'
            return original(operation, **kwargs)
        with patch.object(self.s._calls, 'run', side_effect=drift):
            with self.assertRaisesRegex(DurableRealtimeError, 'provider_revoke_pending'):
                self.s.revoke('s')
        self.assertEqual(self.p.revokes, [])
        self.assertEqual(self.s.recovery_status('s')['cleanup']['attempts'], 1)

    def test_cleanup_drift_during_revoke_cannot_acknowledge(self):
        self.activate()
        self.p.before_revoke = lambda:setattr(self.p,'binding_id','fixture-b')
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.revoke('s')
        self.assertEqual(self.s.recovery_status('s')['cleanup']['pending'], 1)
        self.assertEqual(self.s.recovery_status('s')['state'], 'revoked')

    def test_valid_owner_namespace_can_resume_readback_only(self):
        self.uncertain()
        self.p.binding_id = 'fixture-b'
        with self.assertRaises(DurableRealtimeError):
            self.s.reconcile('s')
        self.p.binding_id = 'fixture-a'
        self.assertEqual(self.open().reconcile('s')['state'], 'active')
        self.assertEqual(self.p.activations, 1)
        self.assertEqual(self.p.lookups, 1)

    def test_current_generation_denied_on_runtime_adapter_drift(self):
        self.activate()
        self.p.binding_id = 'fixture-b'
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.require_generation('s', 1)

    def test_missing_scope_table_rejected_without_recreation(self):
        self.s.db.execute('DROP TABLE realtime_provider_scope')
        with self.assertRaisesRegex(ValueError, 'schema_integrity_invalid'):
            self.open()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM sqlite_master WHERE name='realtime_provider_scope'").fetchone())

    def test_missing_scope_row_rejected_without_refill(self):
        self.s.db.execute('DELETE FROM realtime_provider_scope')
        with self.assertRaisesRegex(ValueError, 'provider_scope_invalid'):
            self.open()
        with self.assertRaisesRegex(ValueError, 'provider_scope_invalid'):
            self.s.issue_ticket(subject='user',session_id='s')
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM realtime_provider_scope').fetchone()[0], 0)

    def test_changed_stored_scope_blocks_authority_read_and_network(self):
        self.activate()
        self.s.db.execute("UPDATE realtime_provider_scope SET binding='fixture-b'")
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.require_generation('s',1)
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.drain_revocations()
        self.assertEqual(self.p.revokes, [])

    def test_removed_schema_marker_fails_current_and_reopen(self):
        self.activate()
        self.s.db.execute("DELETE FROM hepta_component_schema WHERE component='realtime'")
        with self.assertRaisesRegex(ValueError, 'provider_scope_invalid'):
            self.s.pending_recovery()
        with self.assertRaisesRegex(ValueError, 'unmarked_schema_rejected'):
            self.open()

    def test_scope_only_unmarked_store_not_treated_as_empty(self):
        path = str(Path(self.tmp.name) / 'incomplete.db')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE realtime_provider_scope(id INTEGER,binding TEXT)')
            db.execute("INSERT INTO realtime_provider_scope VALUES(1,'fixture-a')")
        with self.assertRaisesRegex(ValueError, 'unmarked_schema_rejected'):
            DurableRealtimeStore(path,provider=self.p,provider_binding='fixture-a',clock=lambda:1000)

    def test_v3_is_never_auto_adopted(self):
        self.activate()
        self.legacy()
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'schema_migration_required'):
            self.open()
        self.assertEqual(self.rows(), before)

    def test_migration_keeps_all_legacy_rows_and_used_allowances(self):
        self.uncertain()
        self.s.reconcile('s')
        self.p.fail_revoke = True
        with self.assertRaises(DurableRealtimeError):
            self.s.revoke('s')
        self.legacy()
        before = self.rows()
        report = migrate_realtime_v3(self.path, provider_binding='fixture-a')
        self.assertEqual(report['recovery_allowance_added'], 0)
        self.assertIs(report['historical_provider_verified'], False)
        self.assertEqual(self.rows(), before)
        other = self.open()
        self.assertEqual(other.recovery_status('s')['lookup']['used'], 1)
        self.assertEqual(other.recovery_status('s')['cleanup']['attempts'], 1)

    def test_migration_preserves_multiple_owned_conflict_cleanups(self):
        self.activate()
        attempt = self.s.db.execute('SELECT attempt_id FROM realtime_attempts').fetchone()[0]
        self.p.fail_revoke = True
        with self.assertRaisesRegex(DurableRealtimeError, 'provider_identity_conflict'):
            self.s._commit_activation('s',attempt,RealtimeActivation('remote-b','receipt-b'),until=time.monotonic()+2,earliest=1000)
        self.legacy()
        before = self.rows()
        migrate_realtime_v3(self.path,provider_binding='fixture-a')
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.open().recovery_status('s')['cleanup']['known_pending'], 2)

    def test_migration_rejects_cross_session_historical_duplicate(self):
        self.activate()
        self.p.result = RealtimeActivation('remote-b','receipt-b')
        self.activate('other')
        self.s.db.execute("UPDATE sessions SET provider_session_id='remote-a' WHERE session_id='other'")
        self.legacy()
        with self.assertRaisesRegex(ValueError,'legacy_ownership_conflict'):
            migrate_realtime_v3(self.path,provider_binding='fixture-a')
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM sqlite_master WHERE name='realtime_provider_scope'").fetchone())

    def test_migration_cannot_relabel_existing_v4(self):
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            migrate_realtime_v3(self.path,provider_binding='fixture-b')
        self.assertEqual(self.s.provider_binding,'fixture-a')

    def test_migration_requires_existing_regular_file(self):
        path = str(Path(self.tmp.name)/'missing.db')
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            migrate_realtime_v3(path,provider_binding='fixture-a')
        self.assertFalse(Path(path).exists())
        link = Path(self.tmp.name)/'link'; link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            migrate_realtime_v3(str(link),provider_binding='fixture-a')

    def test_migration_rejects_missing_budget_and_unknown_version(self):
        self.uncertain(); self.legacy()
        self.s.db.execute('DELETE FROM realtime_lookup_budget')
        with self.assertRaisesRegex(ValueError,'recovery_counter_invalid'):
            migrate_realtime_v3(self.path,provider_binding='fixture-a')
        self.s.db.execute("UPDATE hepta_component_schema SET version=999 WHERE component='realtime'")
        with self.assertRaisesRegex(ValueError,'migration_version_invalid'):
            migrate_realtime_v3(self.path,provider_binding='fixture-a')

    def test_migration_rejects_incomplete_v3(self):
        self.legacy(); self.s.db.execute('DROP TABLE realtime_revoke_outbox')
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            migrate_realtime_v3(self.path,provider_binding='fixture-a')

    def test_migration_failure_rolls_back_scope_version_and_releases_lock(self):
        self.legacy()
        self.s.db.execute("CREATE TRIGGER stop_version BEFORE UPDATE ON hepta_component_schema BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            migrate_realtime_v3(self.path,provider_binding='fixture-a')
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM sqlite_master WHERE name='realtime_provider_scope'").fetchone())
        self.assertEqual(self.s.db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()[0],3)
        with self.s._storage.transaction():pass

    def test_actual_process_exit_after_migration_keeps_binding(self):
        self.activate(); self.legacy()
        code = """
import os,sys
from services.control_plane.realtime_provider_binding import migrate_realtime_v3
migrate_realtime_v3(sys.argv[1],provider_binding='fixture-a')
os._exit(41)
"""
        run = subprocess.run([sys.executable,'-c',code,self.path],capture_output=True,timeout=8)
        self.assertEqual(run.returncode,41,run.stderr.decode())
        self.assertEqual(self.open().require_generation('s',1)['state'],'active')
        with self.assertRaisesRegex(ValueError,'provider_binding_mismatch'):
            self.open(provider=Provider('fixture-b'),provider_binding='fixture-b')

    def test_active_reconcile_does_not_return_authority_on_adapter_drift(self):
        self.activate()
        self.p.binding_id = 'fixture-b'
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.reconcile('s')
        self.assertEqual(self.p.lookups, 0)

    def test_interrupt_does_not_return_new_generation_on_adapter_drift(self):
        self.activate()
        self.p.binding_id = 'fixture-b'
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.s.interrupt('s',generation=1)
        self.assertEqual(self.s.db.execute('SELECT generation FROM sessions').fetchone()[0], 1)

    def test_stored_scope_drift_in_final_transaction_rolls_back_active(self):
        self.s.db.execute("CREATE TRIGGER scope_drift AFTER UPDATE ON sessions WHEN NEW.state='active' "
                          "BEGIN UPDATE realtime_provider_scope SET binding='fixture-b'; END")
        with self.assertRaisesRegex(ValueError, 'provider_binding_mismatch'):
            self.activate()
        self.assertEqual(self.s.db.execute('SELECT state FROM sessions').fetchone()[0], 'activating')
        self.assertEqual(self.s.db.execute('SELECT binding FROM realtime_provider_scope').fetchone()[0], 'fixture-a')


if __name__ == '__main__':
    unittest.main()
