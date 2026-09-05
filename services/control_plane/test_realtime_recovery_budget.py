"""Real SQLite/threads/processes. Fixtures never establish external cleanup."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from services.control_plane.bounded_calls import CallOutcome
from services.control_plane.durable_realtime import DurableRealtimeStore, DurableRealtimeError, RealtimeActivation
from services.control_plane.realtime_recovery import (
    BUDGET_TABLES, LEGACY_TABLES, VERSION, migrate_realtime_v2,
)


class Provider:
    def __init__(self):
        self.lookups = self.activations = 0
        self.revokes = []
        self.fail_activate = True
        self.fail_revoke = True
        self.lookup_result = None
        self.on_lookup = lambda: None
        self.on_revoke = lambda: None

    def activate(self, **kw):
        self.activations += 1
        if self.fail_activate:
            raise TimeoutError('fixture unknown activation')
        return RealtimeActivation('p-' + kw['session_id'], 'r-' + kw['session_id'])

    def reconcile_activation(self, **kw):
        self.lookups += 1
        self.on_lookup()
        return self.lookup_result

    def revoke(self, *, provider_session_id, timeout_seconds):
        self.revokes.append(provider_session_id)
        self.on_revoke()
        if self.fail_revoke:
            raise TimeoutError('fixture cleanup unavailable')


class RealtimeRecoveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'r.db')
        self.now = 1000
        self.p = Provider()
        self.s = self.open()

    def open(self, **changes):
        opts = dict(provider=self.p, clock=lambda: self.now, maximum_readbacks=2, maximum_revoke_attempts=2)
        opts.update(changes)
        s = DurableRealtimeStore(self.path, **opts)
        self.addCleanup(s.close)
        return s

    def uncertain(self, sid='s'):
        t = self.s.issue_ticket(subject='u', session_id=sid)
        self.err('realtime_activation_indeterminate', lambda: self.s.activate(ticket=t, subject='u', session_id=sid))
        return t

    def active(self, sid='s'):
        self.p.fail_activate = False
        t = self.s.issue_ticket(subject='u', session_id=sid)
        self.s.activate(ticket=t, subject='u', session_id=sid)

    def pending_known(self, sid='s'):
        self.active(sid)
        self.err('realtime_provider_revoke_pending', lambda: self.s.revoke(sid))

    def err(self, code, callback):
        with self.assertRaises(DurableRealtimeError) as e:
            callback()
        self.assertEqual(e.exception.code, code)

    def rows(self, table):
        return [tuple(row) for row in self.s.db.execute('SELECT * FROM ' + table)]

    def legacy_fixture(self):
        # Counterpart integration test uses the real hash-verified predecessor.
        with self.s._storage.transaction():
            for t in ('realtime_lookup_budget', 'realtime_revoke_budget', 'realtime_recovery_policy'):
                self.s.db.execute('DROP TABLE ' + t)
            self.s.db.execute("UPDATE hepta_component_schema SET version=2 WHERE component='realtime'")

    def test_lookup_budget_persists_across_connections_and_reopen(self):
        self.uncertain()
        for _ in range(2):
            self.err('realtime_activation_indeterminate', lambda: self.open().reconcile('s'))
        for _ in range(3):
            self.err('realtime_readback_budget_exhausted', lambda: self.open().reconcile('s'))
        self.assertEqual(self.p.lookups, 2)
        self.assertEqual(self.p.activations, 1)
        self.assertEqual(self.s.recovery_status('s')['lookup'], {'used':2,'limit':2,'exhausted':True})
        self.assertEqual(self.s.pending_recovery(), ['s'])

    def test_constructor_cannot_reset_or_raise_persisted_budgets(self):
        for opts in ({'maximum_readbacks': 3}, {'maximum_revoke_attempts': 3},
                     {'maximum_readbacks': 1}, {'maximum_revoke_attempts': 1}):
            with self.assertRaisesRegex(ValueError, 'recovery_policy_migration_required'):
                self.open(**opts)

    def test_invalid_limits_rejected_before_open(self):
        for v in (True, 0, 33, -1, 1.5, '2'):
            with self.assertRaisesRegex(ValueError, 'recovery_limits_invalid'):
                self.open(maximum_readbacks=v)
            with self.assertRaisesRegex(ValueError, 'recovery_limits_invalid'):
                self.open(maximum_revoke_attempts=v)

    def test_sessions_have_independent_lookup_allowances(self):
        self.uncertain('a'); self.uncertain('b')
        for _ in range(2): self.err('realtime_activation_indeterminate', lambda:self.s.reconcile('a'))
        self.err('realtime_activation_indeterminate', lambda:self.s.reconcile('b'))
        self.assertEqual(self.s.recovery_status('a')['lookup']['used'], 2)
        self.assertEqual(self.s.recovery_status('b')['lookup']['used'], 1)

    def test_duplicate_ticket_issuance_never_resets_counter(self):
        t = self.s.issue_ticket(subject='u', session_id='s')
        self.s.db.execute("UPDATE realtime_lookup_budget SET used=1 WHERE session_id='s'")
        self.s.issue_ticket(subject='u', session_id='s')
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'], 1)
        self.err('realtime_ticket_replayed', lambda:self.s.activate(ticket=t,subject='u',session_id='s'))

    def test_budget_is_reserved_before_actual_lookup(self):
        self.uncertain()
        observed=[]
        self.p.on_lookup=lambda:observed.append(self.open().recovery_status('s')['lookup']['used'])
        self.err('realtime_activation_indeterminate', lambda:self.s.reconcile('s'))
        self.assertEqual(observed,[1])

    def test_lookup_reservation_failure_prevents_network(self):
        self.uncertain()
        self.s.db.execute("CREATE TRIGGER stop_counter BEFORE UPDATE ON realtime_lookup_budget BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.s.reconcile('s')
        self.assertEqual(self.p.lookups, 0)
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'], 0)

    def test_lookup_pool_saturation_and_timeout_consume_budget(self):
        self.uncertain()
        for state in ('not_started','timeout'):
            with patch.object(self.s._calls,'run',return_value=CallOutcome(state)):
                self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('s'))
        self.err('realtime_readback_budget_exhausted',lambda:self.s.reconcile('s'))
        self.assertEqual(self.p.lookups,0)

    def test_concurrent_lookup_final_slots_are_atomic(self):
        self.uncertain(); barrier=threading.Barrier(6); results=[]; stores=[self.open() for _ in range(6)]
        def run(s):
            barrier.wait()
            try:s.reconcile('s')
            except DurableRealtimeError as e:results.append(e.code)
        threads=[threading.Thread(target=run,args=(s,)) for s in stores]
        for t in threads:t.start()
        for t in threads:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(results.count('realtime_activation_indeterminate'),2)
        self.assertEqual(results.count('realtime_readback_budget_exhausted'),4)
        self.assertEqual(self.p.lookups,2)

    def test_successful_lookup_charges_once_active_replay_is_local(self):
        self.uncertain();self.p.lookup_result=RealtimeActivation('p-s','r-s')
        self.assertEqual(self.s.reconcile('s')['state'],'active')
        self.assertEqual(self.open().reconcile('s')['state'],'active')
        self.assertEqual(self.p.lookups,1)
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'],1)

    def test_expiry_commits_denial_even_when_lookup_budget_exhausted(self):
        self.uncertain()
        for _ in range(2):self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('s'))
        self.now=1060
        self.err('realtime_readback_budget_exhausted',lambda:self.s.reconcile('s'))
        self.assertEqual(self.s.recovery_status('s')['state'],'revoked')
        self.assertEqual(self.s.pending_recovery(),['s'])
        self.assertEqual(self.s.drain_revocations(),1)
        self.assertEqual(self.p.lookups,2)

    def test_clock_failure_on_recovery_preserves_denial_and_permits_cleanup_lookup(self):
        self.uncertain();self.now=True
        self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('s'))
        self.assertEqual(self.s.recovery_status('s')['state'],'revoked')
        self.assertEqual(self.p.lookups,1)

    def test_repeated_revoke_cannot_reset_pending_job_budget(self):
        self.pending_known()
        for _ in range(5):self.err('realtime_provider_revoke_pending',lambda:self.open().revoke('s'))
        self.assertEqual(self.p.revokes,['p-s','p-s'])
        stat=self.s.recovery_status('s')
        self.assertEqual(stat['cleanup']['exhausted_pending'],1)
        self.assertEqual(stat['cleanup']['pending'],1)
        self.assertFalse(stat['independent_evidence'])

    def test_cleanup_reservation_precedes_provider_call(self):
        self.active();observed=[]
        self.p.on_revoke=lambda:observed.append(self.open().recovery_status('s')['cleanup']['attempts'])
        self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('s'))
        self.assertEqual(observed,[1])

    def test_cleanup_reservation_failure_does_not_erase_local_revoke(self):
        self.active()
        self.s.db.execute("CREATE TRIGGER stop_counter BEFORE UPDATE ON realtime_revoke_budget BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.s.revoke('s')
        self.assertEqual(self.s.recovery_status('s')['state'],'revoked')
        self.assertEqual(self.p.revokes,[])
        self.assertEqual(self.s.recovery_status('s')['cleanup']['pending'],1)

    def test_cleanup_crash_after_reservation_does_not_refund(self):
        self.active()
        with patch.object(self.s._calls,'run',side_effect=SystemExit()):
            with self.assertRaises(SystemExit):self.s.revoke('s')
        self.err('realtime_provider_revoke_pending',lambda:self.open().revoke('s'))
        self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('s'))
        self.assertEqual(self.p.revokes,['p-s'])
        self.assertEqual(self.s.recovery_status('s')['cleanup']['attempts'],2)

    def test_concurrent_cleanup_reservations_do_not_exceed_limit(self):
        self.pending_known();barrier=threading.Barrier(5); errors=[]
        stores=[self.open() for _ in range(5)]
        def run(s):
            barrier.wait()
            try:s.revoke('s')
            except DurableRealtimeError as e:errors.append(e.code)
        ts=[threading.Thread(target=run,args=(s,)) for s in stores]
        for t in ts:t.start()
        for t in ts:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(len(errors),5)
        self.assertEqual(self.p.revokes,['p-s','p-s'])

    def test_successful_cleanup_replays_do_not_spend_or_network(self):
        self.active();self.p.fail_revoke=False;self.s.revoke('s')
        self.s.revoke('s');self.open().revoke('s')
        self.assertEqual(self.p.revokes,['p-s'])
        self.assertEqual(self.s.recovery_status('s')['cleanup']['attempts'],1)
        self.assertEqual(self.s.recovery_status('s')['cleanup']['pending'],0)

    def test_failing_first_job_does_not_starve_next_job(self):
        self.pending_known('a');self.pending_known('b')
        self.s.drain_revocations(limit=1)
        self.s.drain_revocations(limit=1)
        self.assertEqual(self.p.revokes,['p-a','p-b','p-a','p-b'])
        self.assertEqual(self.s.drain_revocations(limit=1),2)
        self.assertEqual(self.s.pending_recovery(),['a','b'])

    def test_exhausted_lookup_does_not_starve_known_cleanup(self):
        self.uncertain('a')
        self.s.revoke('a')
        for _ in range(2):self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('a'))
        self.pending_known('b');self.p.fail_revoke=False
        self.assertEqual(self.s.drain_revocations(limit=1),1)
        self.assertEqual(self.s.recovery_status('b')['cleanup']['pending'],0)
        self.assertEqual(self.p.lookups,2)
        self.assertEqual(self.s.pending_recovery(),['a'])

    def test_lookup_to_known_cleanup_has_separate_budgets(self):
        self.uncertain();self.s.revoke('s');self.p.lookup_result=RealtimeActivation('p-s','r-s')
        self.err('realtime_session_revoked_or_stale',lambda:self.s.reconcile('s'))
        report=self.s.recovery_status('s')
        self.assertEqual(report['lookup']['used'],1)
        self.assertEqual(report['cleanup']['attempts'],1)
        self.assertEqual(report['cleanup']['pending'],1)

    def test_counter_creation_failure_rolls_back_new_session(self):
        self.s.db.execute("CREATE TRIGGER stop_new BEFORE INSERT ON realtime_lookup_budget BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.s.issue_ticket(subject='u',session_id='s')
        self.assertEqual(self.rows('sessions'),[])
        self.assertEqual(self.rows('tickets'),[])

    def test_pending_job_counter_creation_is_atomic(self):
        self.active()
        self.s.db.execute("CREATE TRIGGER stop_new BEFORE INSERT ON realtime_revoke_budget BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.s.revoke('s')
        self.assertEqual(self.rows('realtime_revoke_outbox'),[])
        self.assertEqual(self.p.revokes,[])
        # Transaction failure is not acknowledgement of a successful local denial.
        self.assertEqual(self.s.recovery_status('s')['state'],'active')

    def test_missing_lookup_counter_never_recreated(self):
        self.uncertain();self.s.db.execute('DELETE FROM realtime_lookup_budget')
        with self.assertRaisesRegex(ValueError,'recovery_counter_invalid'):self.open()
        with self.assertRaisesRegex(ValueError,'recovery_counter_invalid'):self.s.reconcile('s')
        self.assertEqual(self.p.lookups,0)
        self.assertEqual(self.rows('realtime_lookup_budget'),[])

    def test_missing_cleanup_counter_never_recreated_or_hidden(self):
        self.pending_known();self.s.db.execute('DELETE FROM realtime_revoke_budget')
        for fn in (self.open,lambda:self.s.revoke('s'),lambda:self.s.recovery_status('s'),lambda:self.s.drain_revocations()):
            with self.assertRaisesRegex(ValueError,'recovery_counter_invalid'):fn()
        self.assertEqual(self.p.revokes,['p-s'])

    def test_missing_budget_tables_or_policy_row_fail_startup(self):
        for table in BUDGET_TABLES:
            with self.subTest(table=table),tempfile.TemporaryDirectory() as d:
                path=d+'/r.db';s=DurableRealtimeStore(path,provider=self.p,clock=lambda:1000);s.close()
                with closing(sqlite3.connect(path)) as db,db:db.execute('DROP TABLE '+table)
                with self.assertRaisesRegex(ValueError,'schema_integrity_invalid'):
                    DurableRealtimeStore(path,provider=self.p,clock=lambda:1000)
        self.s.db.execute('DELETE FROM realtime_recovery_policy')
        with self.assertRaisesRegex(ValueError,'recovery_policy_invalid'):self.open()

    def test_invalid_persisted_counter_type_or_over_limit_is_rejected(self):
        self.uncertain()
        for value in (1.5,3):
            self.s.db.execute('UPDATE realtime_lookup_budget SET used=?',(value,))
            with self.assertRaisesRegex(ValueError,'recovery_counter_invalid'):self.open()
        self.assertEqual(self.p.lookups,0)

    def test_v2_requires_explicit_migration(self):
        self.uncertain();self.legacy_fixture()
        with self.assertRaisesRegex(ValueError,'realtime_schema_migration_required'):self.open()
        self.assertFalse(BUDGET_TABLES & {r[0] for r in self.s.db.execute("SELECT name FROM sqlite_master")})

    def test_offline_migration_preserves_old_rows_and_discloses_new_allowance(self):
        self.uncertain();self.s.revoke('s');self.legacy_fixture()
        old={t:self.rows(t) for t in LEGACY_TABLES}
        report=migrate_realtime_v2(self.path,maximum_readbacks=2,maximum_revoke_attempts=2)
        self.assertEqual(old,{t:self.rows(t) for t in LEGACY_TABLES})
        self.assertEqual(report['to_version'],VERSION)
        self.assertIn('unknown',report['historical_attempts'])
        self.assertEqual(report['additional_lookup_allowance'],2)
        self.err('realtime_activation_indeterminate',lambda:self.open().reconcile('s'))
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'],1)

    def test_migration_cannot_reset_exhausted_v3(self):
        self.uncertain()
        for _ in range(2):self.err('realtime_activation_indeterminate',lambda:self.s.reconcile('s'))
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            migrate_realtime_v2(self.path,maximum_readbacks=2,maximum_revoke_attempts=2)
        self.err('realtime_readback_budget_exhausted',lambda:self.s.reconcile('s'))

    def test_failed_migration_rolls_back_tables_and_version(self):
        self.legacy_fixture()
        self.s.db.execute("CREATE TRIGGER stop_version BEFORE UPDATE ON hepta_component_schema BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):migrate_realtime_v2(self.path,maximum_readbacks=2,maximum_revoke_attempts=2)
        self.assertFalse(BUDGET_TABLES & {r[0] for r in self.s.db.execute("SELECT name FROM sqlite_master")})
        self.assertEqual(self.s.db.execute("SELECT version FROM hepta_component_schema WHERE component='realtime'").fetchone()[0],2)
        with self.s._storage.transaction():pass  # failed migration released the lock

    def test_migration_rejects_missing_file_symlink_and_incomplete_state(self):
        missing=str(Path(self.tmp.name)/'missing.db')
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            migrate_realtime_v2(missing,maximum_readbacks=2,maximum_revoke_attempts=2)
        self.assertFalse(Path(missing).exists())
        link=Path(self.tmp.name)/'link';link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'existing_file_required'):
            migrate_realtime_v2(str(link),maximum_readbacks=2,maximum_revoke_attempts=2)
        self.legacy_fixture();self.s.db.execute('DROP TABLE realtime_revoke_outbox')
        with self.assertRaisesRegex(ValueError,'migration_schema_invalid'):
            migrate_realtime_v2(self.path,maximum_readbacks=2,maximum_revoke_attempts=2)

    def test_actual_process_exit_after_lookup_reservation_keeps_charge(self):
        self.uncertain()
        script='''
import os,sys
from services.control_plane.durable_realtime import DurableRealtimeStore
class P:
 def reconcile_activation(self,**kw):os._exit(31)
s=DurableRealtimeStore(sys.argv[1],provider=P(),clock=lambda:1000,maximum_readbacks=2,maximum_revoke_attempts=2)
s.reconcile('s')
'''
        run=subprocess.run([sys.executable,'-c',script,self.path],capture_output=True,timeout=8)
        self.assertEqual(run.returncode,31,run.stderr.decode())
        self.err('realtime_activation_indeterminate',lambda:self.open().reconcile('s'))
        self.err('realtime_readback_budget_exhausted',lambda:self.s.reconcile('s'))
        self.assertEqual(self.p.lookups,1)
        self.assertEqual(self.s.recovery_status('s')['lookup']['used'],2)

    def test_actual_process_exit_after_cleanup_reservation_keeps_pending(self):
        self.active()
        script='''
import os,sys
from services.control_plane.durable_realtime import DurableRealtimeStore
class P:
 def revoke(self,**kw):os._exit(32)
s=DurableRealtimeStore(sys.argv[1],provider=P(),clock=lambda:1000,maximum_readbacks=2,maximum_revoke_attempts=2)
s.revoke('s')
'''
        run=subprocess.run([sys.executable,'-c',script,self.path],capture_output=True,timeout=8)
        self.assertEqual(run.returncode,32,run.stderr.decode())
        self.err('realtime_provider_revoke_pending',lambda:self.open().revoke('s'))
        self.err('realtime_provider_revoke_pending',lambda:self.s.revoke('s'))
        self.assertEqual(self.p.revokes,['p-s'])
        self.assertEqual(self.s.recovery_status('s')['cleanup']['exhausted_pending'],1)


if __name__=='__main__':unittest.main()
