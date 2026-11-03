"""Actual local SQLite/threads/processes; fixture namespaces are not provider proof."""
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from services.control_plane.durable_realtime import DurableRealtimeStore, DurableRealtimeError, RealtimeActivation
from services.control_plane import realtime_provider_binding as scope
from services.control_plane import realtime_recovery as recovery


class Provider:
    def __init__(self, binding='fixture-realtime'):
        self.binding_id = binding
        self.calls = 0
        self.lookups = 0
        self.revokes = []
        self.fail = False
        self.fail_revoke = False
        self.before = lambda: None
        self.result = RealtimeActivation('shared-remote', 'shared-receipt')

    def activate(self, **kwargs):
        self.calls += 1
        self.before()
        if self.fail:
            raise TimeoutError('fixture')
        return self.result

    def reconcile_activation(self, **kwargs):
        self.lookups += 1
        return self.result

    def revoke(self, *, provider_session_id, timeout_seconds):
        self.revokes.append(provider_session_id)
        if self.fail_revoke:
            raise TimeoutError('fixture')


class RealtimeProviderBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'state.sqlite')
        self.now = 1000
        self.p = Provider()
        self.s = self.open()

    def open(self, **changes):
        opts = dict(provider=self.p, provider_binding='fixture-realtime', clock=lambda:self.now)
        opts.update(changes)
        s = DurableRealtimeStore(self.path, **opts)
        self.addCleanup(s.close)
        return s

    def activate(self, sid='a', store=None):
        s = store or self.s
        ticket = s.issue_ticket(subject='subject-' + sid, session_id=sid)
        return s.activate(ticket=ticket, subject='subject-' + sid, session_id=sid)

    def err(self, code, callback):
        with self.assertRaises(DurableRealtimeError) as result:
            callback()
        self.assertEqual(result.exception.code, code)
        return result.exception

    def colliding(self):
        self.activate('a')
        self.err('realtime_provider_identity_conflict', lambda:self.activate('b'))

    def legacy_v3(self):
        with self.s._storage.transaction():
            self.s.db.execute('DROP INDEX ' + scope.OWNERSHIP_INDEX)
            for t in scope.TABLES:
                self.s.db.execute('DROP TABLE ' + t)
            self.s.db.execute("UPDATE hepta_component_schema SET version=3 WHERE component='realtime'")

    def rows(self, table):
        return [tuple(r) for r in self.s.db.execute('SELECT * FROM ' + table)]

    def test_binding_required_and_validated_before_creating_store(self):
        path = str(Path(self.tmp.name)/'absent.db')
        with self.assertRaises(TypeError):
            DurableRealtimeStore(path,provider=self.p,clock=lambda:1000)
        for binding in ('',True,'x'*129,'https://invalid.example','a\nb',None):
            with self.assertRaisesRegex(ValueError,'binding_invalid'):
                DurableRealtimeStore(path,provider=self.p,provider_binding=binding,clock=lambda:1000)
        self.assertFalse(Path(path).exists())

    def test_adapter_configuration_must_match_explicit_namespace(self):
        wrong = Provider('other-tenant')
        self.err('realtime_provider_runtime_binding_mismatch',lambda:self.open(provider=wrong))
        self.assertEqual(wrong.calls,0)

    def test_different_namespace_reopen_rejected_before_wrong_cleanup(self):
        self.activate()
        wrong = Provider('other-tenant')
        with self.assertRaisesRegex(ValueError,'realtime_provider_binding_mismatch'):
            self.open(provider=wrong,provider_binding='other-tenant')
        self.assertEqual(wrong.revokes,[])
        self.assertEqual(self.s.require_generation('a',1)['state'],'active')

    def test_same_namespace_reopen_preserves_state_and_budgets(self):
        self.activate()
        previous = self.rows('realtime_lookup_budget')
        s = self.open(provider=Provider())
        self.assertEqual(s.require_generation('a',1)['state'],'active')
        self.assertEqual(previous,self.rows('realtime_lookup_budget'))
        self.assertEqual(s.provider_binding,'fixture-realtime')

    def test_provider_and_binding_public_attributes_are_read_only(self):
        with self.assertRaises(AttributeError):self.s.provider=Provider('other')
        with self.assertRaises(AttributeError):self.s.provider_binding='other'

    def test_changed_runtime_provider_denies_before_consuming_ticket(self):
        t=self.s.issue_ticket(subject='u',session_id='a');self.p.binding_id='other'
        self.err('realtime_provider_runtime_binding_mismatch',lambda:self.s.activate(ticket=t,subject='u',session_id='a'))
        self.assertEqual(self.p.calls,0)
        self.assertEqual(self.s.db.execute('SELECT state FROM tickets').fetchone()[0],'issued')

    def test_changed_provider_during_exchange_does_not_commit_active(self):
        self.p.before=lambda:setattr(self.p,'binding_id','other')
        self.err('realtime_provider_runtime_binding_mismatch',self.activate)
        self.assertEqual(self.s.db.execute('SELECT state FROM sessions').fetchone()[0],'activating')
        self.assertEqual(self.p.revokes,[])

    def test_changed_namespace_after_lookup_reservation_prevents_network(self):
        self.p.fail=True
        self.err('realtime_activation_indeterminate',self.activate)
        original=self.s._calls.run
        def change(operation,**kwargs):
            self.p.binding_id='other'
            return original(operation,**kwargs)
        with patch.object(self.s._calls,'run',side_effect=change):
            self.err('realtime_provider_runtime_binding_mismatch',lambda:self.s.reconcile('a'))
        self.assertEqual(self.p.lookups,0)
        self.assertEqual(self.s.db.execute('SELECT used FROM realtime_lookup_budget').fetchone()[0],1)

    def test_changed_namespace_after_cleanup_reservation_prevents_network(self):
        self.activate();original=self.s._calls.run
        def change(operation,**kwargs):
            self.p.binding_id='other'
            return original(operation,**kwargs)
        with patch.object(self.s._calls,'run',side_effect=change):
            self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('a'))
        self.assertEqual(self.p.revokes,[])
        self.assertEqual(self.s.db.execute('SELECT state FROM sessions').fetchone()[0],'revoked')
        self.assertEqual(self.s.db.execute('SELECT used FROM realtime_revoke_budget').fetchone()[0],1)

    def test_provider_descriptor_exception_is_not_reflected(self):
        class Broken:
            @property
            def binding_id(self):raise RuntimeError('private-fixture-configuration')
        error=self.err('realtime_provider_runtime_binding_unavailable',lambda:self.open(provider=Broken()))
        self.assertIsNone(error.__cause__)
        self.assertNotIn('private-fixture',str(error))

    def test_scope_row_missing_does_not_reinitialize(self):
        self.s.db.execute('DELETE FROM realtime_provider_scope')
        with self.assertRaisesRegex(ValueError,'realtime_provider_scope_invalid'):self.open()
        with self.assertRaisesRegex(ValueError,'realtime_provider_scope_invalid'):self.activate()
        self.assertEqual(self.rows('realtime_provider_scope'),[])

    def test_scope_change_in_open_database_is_detected(self):
        self.s.db.execute("UPDATE realtime_provider_scope SET binding='other'")
        with self.assertRaisesRegex(ValueError,'realtime_provider_binding_mismatch'):self.activate()
        self.assertEqual(self.p.calls,0)

    def test_missing_ownership_index_is_not_silently_recreated(self):
        self.s.db.execute('DROP INDEX '+scope.OWNERSHIP_INDEX)
        with self.assertRaisesRegex(ValueError,'ownership_index_invalid'):self.open()
        self.assertIsNone(self.s.db.execute('SELECT name FROM sqlite_master WHERE name=?',(scope.OWNERSHIP_INDEX,)).fetchone())

    def test_wrong_partial_index_definition_rejected(self):
        self.s.db.execute('DROP INDEX '+scope.OWNERSHIP_INDEX)
        self.s.db.execute('CREATE UNIQUE INDEX '+scope.OWNERSHIP_INDEX+' ON sessions(provider_session_id) WHERE 0')
        with self.assertRaisesRegex(ValueError,'ownership_index_invalid'):self.open()

    def test_duplicate_remote_id_quarantines_only_conflicting_claimant(self):
        self.colliding()
        self.assertEqual(self.s.require_generation('a',1)['state'],'active')
        self.assertTrue(self.s.recovery_status('b')['quarantined'])
        self.assertEqual(self.s.pending_recovery(),['b'])
        self.assertEqual(self.p.revokes,[])
        self.assertEqual(self.rows('realtime_provider_quarantine')[0][2],'remote_session_owned_elsewhere')

    def test_quarantined_session_cannot_auto_reconcile_revoke_or_reissue(self):
        self.colliding()
        for fn in (lambda:self.s.reconcile('b'),lambda:self.s.revoke('b'),lambda:self.s.require_generation('b',1)):
            self.err('realtime_provider_quarantined',fn)
        self.err('realtime_session_not_new',lambda:self.s.issue_ticket(subject='subject-b',session_id='b'))
        self.assertEqual(self.s.drain_revocations(),0)
        self.assertEqual(self.p.lookups,0)
        self.assertEqual(self.p.revokes,[])
        self.assertEqual(self.s.pending_recovery(),['b'])

    def test_quarantine_is_durable_and_not_cleared_by_late_good_result(self):
        self.colliding();s=self.open()
        attempt=s.db.execute("SELECT attempt_id FROM realtime_attempts WHERE session_id='b'").fetchone()[0]
        self.err('realtime_provider_quarantined',lambda:s._commit_activation('b',attempt,
                 RealtimeActivation('different-remote','different-receipt'),until=time.monotonic()+1,earliest=1000))
        self.assertEqual(len(self.rows('realtime_provider_quarantine')),1)
        self.assertEqual(self.p.revokes,[])

    def test_deleted_quarantine_record_cannot_reopen_as_clean_state(self):
        self.colliding();self.s.db.execute('DELETE FROM realtime_provider_quarantine')
        with self.assertRaisesRegex(ValueError,'quarantine_invalid'):self.open()

    def test_pending_cleanup_ownership_prevents_id_reuse(self):
        self.activate();self.p.fail_revoke=True
        self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('a'))
        self.err('realtime_provider_identity_conflict',lambda:self.activate('b'))
        self.assertEqual(self.p.revokes,['shared-remote'])
        self.assertEqual(self.s.recovery_status('b')['state'],'quarantined')

    def test_outbox_only_owner_prevents_collision_after_expired_result(self):
        self.p.before=lambda:setattr(self,'now',1061)
        self.p.fail_revoke=True
        self.err('realtime_ticket_expired',self.activate)
        self.assertIsNone(self.s.db.execute('SELECT provider_session_id FROM sessions').fetchone()[0])
        self.p.before=lambda:None
        self.err('realtime_provider_identity_conflict',lambda:self.activate('b'))
        self.assertEqual(self.p.revokes,['shared-remote'])

    def test_different_remote_result_for_same_local_session_is_quarantined(self):
        self.activate()
        attempt=self.s.db.execute('SELECT attempt_id FROM realtime_attempts').fetchone()[0]
        self.err('realtime_provider_identity_conflict',lambda:self.s._commit_activation('a',attempt,
                 RealtimeActivation('changed-remote','receipt'),until=time.monotonic()+1,earliest=1000))
        self.assertEqual(self.s.recovery_status('a')['state'],'quarantined')
        self.assertEqual(self.p.revokes,[])

    def test_changed_receipt_cannot_replace_previous_exact_binding(self):
        self.activate();attempt=self.s.db.execute('SELECT attempt_id FROM realtime_attempts').fetchone()[0]
        self.err('realtime_provider_identity_conflict',lambda:self.s._commit_activation('a',attempt,
                 RealtimeActivation('shared-remote','changed-receipt'),until=time.monotonic()+1,earliest=1000))
        self.assertEqual(self.rows('realtime_provider_quarantine')[0][2],'remote_receipt_identity_changed')
        self.assertEqual(self.p.revokes,[])

    def test_same_exact_result_replay_remains_active(self):
        self.activate();attempt=self.s.db.execute('SELECT attempt_id FROM realtime_attempts').fetchone()[0]
        row=self.s._commit_activation('a',attempt,self.p.result,until=time.monotonic()+1,earliest=1000)
        self.assertEqual(row['state'],'active')
        self.assertEqual(self.rows('realtime_provider_quarantine'),[])

    def test_concurrent_remote_id_claims_have_one_owner(self):
        barrier=threading.Barrier(4);results=[]
        stores=[self.open() for _ in range(4)]
        def run(index):
            barrier.wait()
            try:results.append(self.activate(str(index),stores[index])['state'])
            except DurableRealtimeError as e:results.append(e.code)
        threads=[threading.Thread(target=run,args=(i,)) for i in range(4)]
        for t in threads:t.start()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(results.count('active'),1)
        self.assertEqual(results.count('realtime_provider_identity_conflict'),3)
        self.assertEqual(len(self.rows('realtime_provider_quarantine')),3)
        self.assertEqual(self.p.revokes,[])

    def test_failed_quarantine_transaction_is_not_acknowledged(self):
        self.activate()
        self.s.db.execute("CREATE TRIGGER refuse_conflict BEFORE INSERT ON realtime_provider_quarantine BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.activate('b')
        self.assertEqual(self.s.db.execute("SELECT state FROM sessions WHERE session_id='b'").fetchone()[0],'activating')
        self.assertEqual(self.rows('realtime_provider_quarantine'),[])
        self.assertEqual(self.p.revokes,[])

    def test_private_cleanup_enqueue_cannot_take_over_other_session(self):
        self.activate();self.s.issue_ticket(subject='subject-b',session_id='b')
        with self.s._storage.transaction():
            self.err('realtime_provider_cleanup_ownership_conflict',lambda:self.s._queue_revoke('b','shared-remote'))
        self.assertEqual(self.rows('realtime_revoke_outbox'),[])
        with self.s._storage.transaction():
            self.err('realtime_session_unknown',lambda:self.s._queue_revoke('missing','other-remote'))

    def test_quarantine_in_drain_does_not_starve_unrelated_cleanup(self):
        self.p.fail=True
        self.err('realtime_activation_indeterminate',lambda:self.activate('b'))
        self.s.revoke('b')
        self.p.fail=False;self.activate('a')
        self.err('realtime_provider_identity_conflict',lambda:self.s.reconcile('b'))
        self.p.result=RealtimeActivation('other-remote','other-receipt')
        self.activate('c');self.p.fail_revoke=True
        self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('c'))
        self.p.fail_revoke=False
        self.assertEqual(self.s.drain_revocations(limit=1),1)  # b lookup retained, never resolved as success
        self.assertEqual(self.p.revokes,['other-remote','other-remote'])
        self.assertEqual(self.s.pending_recovery(),['b'])

    def test_normal_startup_refuses_v3_without_rewriting_rows(self):
        self.activate();self.legacy_v3();old=self.rows('sessions')
        with self.assertRaisesRegex(ValueError,'realtime_schema_migration_required'):self.open()
        self.assertEqual(old,self.rows('sessions'))

    def test_v3_migration_preserves_all_existing_rows_and_spent_counters(self):
        self.p.fail=True;self.err('realtime_activation_indeterminate',self.activate)
        self.p.result=None;self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('a'))
        self.legacy_v3()
        tables=recovery.LEGACY_TABLES|recovery.BUDGET_TABLES
        old={t:self.rows(t) for t in tables}
        report=scope.migrate_realtime_v3(self.path,provider_binding='fixture-realtime')
        self.assertEqual(old,{t:self.rows(t) for t in tables})
        self.assertEqual(report['recovery_allowance_added'],0)
        self.assertFalse(report['historical_provider_verified'])
        self.assertEqual(self.open().recovery_status('a')['lookup']['used'],1)

    def test_migration_cannot_reset_or_relabel_v4(self):
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            scope.migrate_realtime_v3(self.path,provider_binding='other')
        self.assertEqual(self.rows('realtime_provider_scope'),[(1,'fixture-realtime')])

    def test_migration_failure_rolls_back_scope_index_and_marker(self):
        self.legacy_v3()
        self.s.db.execute("CREATE TRIGGER refuse_version BEFORE UPDATE ON hepta_component_schema BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):scope.migrate_realtime_v3(self.path,provider_binding='fixture-realtime')
        names={r[0] for r in self.s.db.execute('SELECT name FROM sqlite_master')}
        self.assertFalse(scope.TABLES&names)
        self.assertNotIn(scope.OWNERSHIP_INDEX,names)
        self.assertEqual(self.s.db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()[0],3)
        with self.s._storage.transaction():pass

    def test_migration_rejects_ambiguous_legacy_remote_owner(self):
        self.activate();self.s.issue_ticket(subject='subject-b',session_id='b');self.legacy_v3()
        self.s.db.execute("UPDATE sessions SET provider_session_id='shared-remote',provider_receipt_id='receipt-b' WHERE session_id='b'")
        with self.assertRaisesRegex(ValueError,'legacy_ownership_conflict'):
            scope.migrate_realtime_v3(self.path,provider_binding='fixture-realtime')
        self.assertFalse(scope.TABLES&{r[0] for r in self.s.db.execute('SELECT name FROM sqlite_master')})

    def test_migration_rejects_ambiguous_legacy_cleanup_owner(self):
        self.activate();self.s.issue_ticket(subject='subject-b',session_id='b');self.legacy_v3()
        self.s.db.execute("INSERT INTO realtime_revoke_outbox VALUES('provider:shared-remote','b','shared-remote','pending')")
        self.s.db.execute("INSERT INTO realtime_revoke_budget VALUES('provider:shared-remote',1)")
        with self.assertRaisesRegex(ValueError,'legacy_ownership_conflict'):
            scope.migrate_realtime_v3(self.path,provider_binding='fixture-realtime')

    def test_migration_rejects_missing_file_symlink_and_missing_table(self):
        absent=str(Path(self.tmp.name)/'absent.db')
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            scope.migrate_realtime_v3(absent,provider_binding='fixture-realtime')
        self.assertFalse(Path(absent).exists())
        link=Path(self.tmp.name)/'link';link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            scope.migrate_realtime_v3(str(link),provider_binding='fixture-realtime')
        self.legacy_v3();self.s.db.execute('DROP TABLE realtime_lookup_budget')
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            scope.migrate_realtime_v3(self.path,provider_binding='fixture-realtime')

    def test_actual_process_exit_after_conflict_retains_isolation(self):
        self.activate()
        script='''
import os,sys
from services.control_plane.durable_realtime import DurableRealtimeStore,RealtimeActivation,DurableRealtimeError
class P:
 binding_id='fixture-realtime'
 def activate(self,**kw):return RealtimeActivation('shared-remote','shared-receipt')
 def revoke(self,**kw):raise AssertionError('must not revoke')
s=DurableRealtimeStore(sys.argv[1],provider=P(),provider_binding='fixture-realtime',clock=lambda:1000)
t=s.issue_ticket(subject='subject-b',session_id='b')
try:s.activate(ticket=t,subject='subject-b',session_id='b')
except DurableRealtimeError as e:
 assert e.code=='realtime_provider_identity_conflict'
 os._exit(37)
'''
        run=subprocess.run([sys.executable,'-c',script,self.path],capture_output=True,timeout=8)
        self.assertEqual(run.returncode,37,run.stderr.decode())
        reopened=self.open()
        self.assertTrue(reopened.recovery_status('b')['quarantined'])
        self.assertEqual(reopened.require_generation('a',1)['state'],'active')
        self.assertEqual(self.p.revokes,[])


if __name__=='__main__':unittest.main()
