"""Real SQLite and concurrency regressions; inert provider, no remote evidence."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.control_plane.durable_realtime import (
    DurableRealtimeError, DurableRealtimeStore, RealtimeActivation,
)


class Provider:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.result = RealtimeActivation('remote-a', 'receipt-a')
        self.lookup_result = RealtimeActivation('remote-b', 'receipt-b')
        self.fail_revoke = True
        self.revoke_result = None
        self.revokes = []
        self.activations = 0
        self.lookups = 0
        self.on_revoke = lambda remote: None

    def activate(self, **kwargs):
        self.activations += 1
        self.entered.set()
        if not self.release.wait(3):
            raise TimeoutError('fixture barrier')
        return self.result

    def reconcile_activation(self, **kwargs):
        self.lookups += 1
        return self.lookup_result

    def revoke(self, *, provider_session_id, timeout_seconds):
        self.revokes.append(provider_session_id)
        self.on_revoke(provider_session_id)
        if self.fail_revoke:
            raise TimeoutError('fixture cleanup unavailable')
        return self.revoke_result


class RealtimeResultCustodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'r.db')
        self.provider = Provider()
        self.stores = []
        self.addCleanup(self.close_all)
        self.store = self.open()

    def close_all(self):
        self.provider.release.set()
        for store in self.stores:
            store.close()

    def open(self):
        store = DurableRealtimeStore(self.path, provider=self.provider, clock=lambda:1000)
        self.stores.append(store)
        return store

    def error(self, code, operation):
        with self.assertRaises(DurableRealtimeError) as error:
            operation()
        self.assertEqual(error.exception.code, code)

    def activate(self, sid='s', store=None):
        store = store or self.store
        ticket = store.issue_ticket(subject='fixture-user', session_id=sid)
        return store.activate(ticket=ticket, subject='fixture-user', session_id=sid)

    def jobs(self, sid='s'):
        return [dict(row) for row in self.store.db.execute(
            'SELECT * FROM realtime_revoke_outbox WHERE session_id=? ORDER BY job_id', (sid,))]

    def session(self, sid='s'):
        return dict(self.store.db.execute('SELECT * FROM sessions WHERE session_id=?',(sid,)).fetchone())

    def late(self, result, sid='s', until=None):
        # Invoke the real final-admission method against a real persisted attempt;
        # no modified copy of its control flow is used by this boundary probe.
        attempt = self.store.db.execute('SELECT attempt_id FROM realtime_attempts WHERE session_id=?',(sid,)).fetchone()[0]
        return self.store._commit_activation(sid, attempt, result,
            until=time.monotonic()+2 if until is None else until, earliest=1000)

    def race(self, after_readback=None):
        self.provider.release.clear()
        ticket = self.store.issue_ticket(subject='fixture-user',session_id='s')
        values, errors = [], []
        def activate():
            try:
                values.append(self.store.activate(ticket=ticket,subject='fixture-user',session_id='s'))
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=activate)
        thread.start()
        try:
            self.assertTrue(self.provider.entered.wait(2))
            self.open().reconcile('s')
            if after_readback:
                after_readback()
        finally:
            self.provider.release.set()
            thread.join(4)
        self.assertFalse(thread.is_alive())
        return values, errors

    def conflict(self):
        self.activate()
        self.error('realtime_provider_identity_conflict', lambda:self.late(self.provider.lookup_result))

    def test_different_concurrent_results_commit_denial_and_both_cleanups(self):
        values, errors = self.race()
        self.assertEqual(values, [])
        self.assertEqual([str(e) for e in errors], ['realtime_provider_identity_conflict'])
        self.assertEqual(self.session()['state'], 'revoked')
        self.assertEqual({j['provider_session_id'] for j in self.jobs()}, {'remote-a','remote-b'})
        self.assertTrue(all(j['state']=='pending' for j in self.jobs()))
        self.error('realtime_session_not_active', lambda:self.store.require_generation('s',2))
        self.assertEqual(self.provider.activations, 1)

    def test_receipt_conflict_for_same_remote_is_terminal_with_one_cleanup(self):
        self.provider.lookup_result=RealtimeActivation('remote-a','changed-receipt')
        _, errors=self.race()
        self.assertEqual([str(e) for e in errors],['realtime_provider_identity_conflict'])
        self.assertEqual(self.session()['state'],'revoked')
        self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.provider.revokes,['remote-a'])

    def test_identical_concurrent_results_do_not_revoke_valid_session(self):
        self.provider.lookup_result=self.provider.result
        values, errors=self.race()
        self.assertEqual(errors,[])
        self.assertEqual(values[0]['state'],'active')
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.provider.revokes,[])

    def test_identical_late_result_after_interrupt_preserves_new_generation(self):
        self.provider.lookup_result=self.provider.result
        _, errors=self.race(lambda:self.open().interrupt('s',generation=1))
        self.assertEqual([str(e) for e in errors],['realtime_session_revoked_or_stale'])
        self.assertEqual(self.store.require_generation('s',2)['state'],'active')
        self.assertEqual(self.provider.revokes,[])

    def test_different_late_result_after_interrupt_still_denies_conflict(self):
        _, errors=self.race(lambda:self.open().interrupt('s',generation=1))
        self.assertEqual([str(e) for e in errors],['realtime_provider_identity_conflict'])
        self.assertEqual(self.session()['generation'],3)
        self.assertEqual(self.session()['state'],'revoked')
        self.assertEqual(len(self.jobs()),2)

    def test_conflict_cleanup_is_visible_before_any_provider_revoke(self):
        self.activate();observed=[]
        def inspect(remote):
            other=self.open()
            observed.append((other.recovery_status('s')['state'],
                             other.recovery_status('s')['cleanup']['pending']))
        self.provider.on_revoke=inspect
        self.error('realtime_provider_identity_conflict',lambda:self.late(self.provider.lookup_result))
        self.assertEqual(observed,[('revoked',2),('revoked',2)])

    def test_conflict_survives_reopen_and_successful_cleanup_cannot_reactivate(self):
        self.conflict();other=self.open()
        self.assertEqual(other.recovery_status('s')['cleanup']['pending'],2)
        self.provider.fail_revoke=False
        self.assertEqual(other.drain_revocations(),0)
        self.error('realtime_session_not_active',lambda:other.require_generation('s',2))
        self.error('realtime_session_not_new',lambda:other.issue_ticket(subject='fixture-user',session_id='s'))
        self.assertEqual(other.recovery_status('s')['state'],'revoked')

    def test_conflict_with_exhausted_caller_budget_retains_all_pending_work(self):
        self.activate()
        self.error('realtime_provider_identity_conflict',lambda:self.late(self.provider.lookup_result,until=0))
        self.assertEqual(self.session()['state'],'revoked')
        self.assertEqual(len(self.jobs()),2)
        self.assertEqual(self.provider.revokes,[])
        self.assertEqual(self.store.recovery_status('s')['cleanup']['attempts'],0)

    def test_conflict_storage_failure_rolls_back_and_never_calls_remote(self):
        self.activate()
        self.store.db.execute("CREATE TRIGGER stop_new BEFORE INSERT ON realtime_revoke_outbox "
            "WHEN NEW.provider_session_id='remote-b' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.late(self.provider.lookup_result)
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.provider.revokes,[])
        # Failed durable denial is NOT represented as success; supervisor must
        # stop ingress on storage failure. Original committed state remains.
        self.assertEqual(self.session()['state'],'active')

    def test_alternate_result_cannot_overwrite_known_indeterminate_identity(self):
        self.activate()
        self.store.db.execute("UPDATE sessions SET state='indeterminate' WHERE session_id='s'")
        self.error('realtime_provider_identity_conflict',lambda:self.store.reconcile('s'))
        self.assertEqual(self.session()['provider_session_id'],'remote-a')
        self.assertEqual(self.session()['state'],'revoked')
        self.assertEqual(len(self.jobs()),2)

    def test_remote_id_owned_by_other_active_session_is_not_cancelled(self):
        self.activate('owner')
        self.error('realtime_provider_owner_conflict',lambda:self.activate('contender'))
        self.assertEqual(self.session('owner')['state'],'active')
        self.assertEqual(self.session('contender')['state'],'revoked')
        self.assertEqual(self.jobs('contender')[0]['job_id'],'lookup:contender')
        self.assertEqual(self.provider.revokes,[])

    def test_other_session_completed_cleanup_is_not_reused_as_new_success(self):
        self.activate('owner');self.provider.fail_revoke=False;self.store.revoke('owner')
        self.error('realtime_provider_owner_conflict',lambda:self.activate('contender'))
        self.assertEqual(self.jobs('owner')[0]['state'],'completed')
        self.assertEqual(self.jobs('contender')[0]['state'],'pending')
        self.assertEqual(self.provider.revokes,['remote-a'])
        self.assertEqual(self.store.recovery_status('contender')['cleanup']['pending'],1)

    def test_cross_session_owner_conflict_preserves_existing_owned_cleanup(self):
        self.activate('owner')
        self.provider.result=RealtimeActivation('remote-b','receipt-b');self.activate('contender')
        self.error('realtime_provider_owner_conflict',lambda:self.late(
            RealtimeActivation('remote-a','receipt-a'),sid='contender'))
        self.assertEqual(self.session('owner')['state'],'active')
        self.assertEqual({j['job_id'] for j in self.jobs('contender')},
                         {'provider:remote-b','lookup:contender'})
        self.assertEqual(self.provider.revokes,['remote-b'])

    def test_simultaneous_sessions_cannot_both_claim_one_remote_id(self):
        barrier=threading.Barrier(2);values=[];errors=[]
        def activate(sid):
            other=self.open();barrier.wait()
            try:values.append(self.activate(sid,other))
            except BaseException as e:errors.append(e)
        threads=[threading.Thread(target=activate,args=(sid,)) for sid in ('a','b')]
        for t in threads:t.start()
        for t in threads:t.join(4);self.assertFalse(t.is_alive())
        self.assertEqual(len(values),1)
        self.assertEqual([str(e) for e in errors],['realtime_provider_owner_conflict'])
        self.assertEqual(self.provider.revokes,[])

    def test_pending_lookup_is_counted_before_and_after_budget_exhaustion(self):
        self.provider.result=None
        self.error('realtime_provider_response_invalid',lambda:self.activate())
        self.store.revoke('s');self.provider.lookup_result=None
        summary=self.store.recovery_status('s')['cleanup']
        self.assertEqual(summary['pending'],1)
        self.assertEqual(summary['known_pending'],0)
        self.assertEqual(summary['lookup_pending'],1)
        for _ in range(8):self.error('realtime_activation_indeterminate',lambda:self.store.reconcile('s'))
        summary=self.store.recovery_status('s')['cleanup']
        self.assertEqual(summary['pending'],1)
        self.assertEqual(summary['exhausted_pending'],1)
        self.assertEqual(self.store.pending_recovery(),['s'])

    def test_mixed_lookup_and_known_pending_summary_is_not_zero(self):
        self.activate('owner')
        self.provider.result=RealtimeActivation('remote-b','receipt-b');self.activate('contender')
        self.error('realtime_provider_owner_conflict',lambda:self.late(
            RealtimeActivation('remote-a','receipt-a'),sid='contender'))
        summary=self.store.recovery_status('contender')['cleanup']
        self.assertEqual(summary['jobs'],2)
        self.assertEqual(summary['pending'],2)
        self.assertEqual((summary['known_pending'],summary['lookup_pending']),(1,1))

    def test_non_none_revoke_return_is_never_completed(self):
        self.provider.fail_revoke=False
        for i,value in enumerate((False,True,0,1,'',{'error':'fixture'},[])):
            sid='s'+str(i)
            self.provider.result=RealtimeActivation('p'+str(i),'r'+str(i))
            self.activate(sid);self.provider.revoke_result=value
            self.error('realtime_provider_revoke_pending',lambda:self.store.revoke(sid))
            self.assertEqual(self.jobs(sid)[0]['state'],'pending')
            self.assertEqual(self.store.recovery_status(sid)['cleanup']['attempts'],1)

    def test_only_contract_none_return_acknowledges_adapter_cleanup(self):
        self.activate();self.provider.fail_revoke=False
        self.store.revoke('s')
        self.assertEqual(self.jobs()[0]['state'],'completed')
        self.assertFalse(self.store.recovery_status('s')['independent_evidence'])

    def test_repeated_revoke_processes_secondary_known_session(self):
        self.conflict();self.provider.fail_revoke=False
        self.store.revoke('s')
        self.assertEqual(self.store.recovery_status('s')['cleanup']['known_pending'],0)
        self.assertEqual(self.provider.revokes.count('remote-a'),2)
        self.assertEqual(self.provider.revokes.count('remote-b'),2)

    def test_completed_primary_cannot_hide_pending_secondary(self):
        self.conflict()
        self.provider.fail_revoke=False
        self.assertTrue(self.store._drain_known('provider:remote-a',1))
        self.provider.fail_revoke=True
        self.error('realtime_provider_revoke_pending',lambda:self.store.revoke('s'))
        self.assertEqual([j['provider_session_id'] for j in self.jobs() if j['state']=='pending'],['remote-b'])

    def test_no_cleanup_job_is_not_a_successful_cleanup(self):
        with self.assertRaisesRegex(ValueError,'realtime_cleanup_job_missing'):
            self.store._drain_known('provider:missing',1)
        self.assertEqual(self.provider.revokes,[])

    def test_failed_completion_commit_keeps_spent_budget_and_pending_job(self):
        self.activate();self.provider.fail_revoke=False
        self.store.db.execute("CREATE TRIGGER stop_done BEFORE UPDATE ON realtime_revoke_outbox "
            "WHEN NEW.state='completed' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.revoke('s')
        self.assertEqual(self.jobs()[0]['state'],'pending')
        self.assertEqual(self.store.recovery_status('s')['cleanup']['attempts'],1)
        self.assertEqual(self.session()['state'],'revoked')

    def test_rewritten_job_during_remote_call_cannot_be_acknowledged(self):
        self.activate();self.provider.fail_revoke=False
        def change(remote):
            other=self.open()
            other.db.execute("UPDATE realtime_revoke_outbox SET provider_session_id='changed' WHERE job_id='provider:remote-a'")
        self.provider.on_revoke=change
        with self.assertRaisesRegex(ValueError,'realtime_cleanup_binding_invalid'):self.store.revoke('s')
        self.assertEqual(self.jobs()[0]['state'],'pending')

    def test_requeued_unknown_lookup_does_not_refresh_allowance(self):
        self.provider.result=None
        self.error('realtime_provider_response_invalid',lambda:self.activate())
        self.store.revoke('s')
        self.store.db.execute("UPDATE realtime_lookup_budget SET used=8 WHERE session_id='s'")
        self.store.db.execute("UPDATE realtime_revoke_outbox SET state='completed' WHERE job_id='lookup:s'")
        with self.store._storage.transaction():self.store._queue_revoke('s',None)
        self.assertEqual(self.store.recovery_status('s')['lookup']['used'],8)
        self.assertEqual(self.store.recovery_status('s')['cleanup']['exhausted_pending'],1)

    def test_legacy_cross_session_duplicate_does_not_authorize_remote_revoke(self):
        self.activate('owner')
        self.provider.result=RealtimeActivation('remote-b','receipt-b');self.activate('other')
        # Model an inconsistent retained v3 database; no proof of external ownership.
        self.store.db.execute("UPDATE sessions SET provider_session_id='remote-a',provider_receipt_id='receipt-a' WHERE session_id='other'")
        self.store.revoke('other')
        self.assertEqual(self.jobs('other')[0]['job_id'],'lookup:other')
        self.assertEqual(self.provider.revokes,[])
        self.assertEqual(self.session('owner')['state'],'active')

    def test_invalid_activation_subclass_does_not_change_current_authority(self):
        class UntrustedActivation(RealtimeActivation):pass
        self.provider.result=UntrustedActivation('p','r')
        self.error('realtime_provider_response_invalid',lambda:self.activate())
        self.assertEqual(self.session()['state'],'indeterminate')

    def test_actual_process_exit_during_conflict_cleanup_retains_both_jobs(self):
        self.activate()
        script='''
import os,sys,time
from services.control_plane.durable_realtime import DurableRealtimeStore,RealtimeActivation
class P:
 def revoke(self,**kw):os._exit(37)
s=DurableRealtimeStore(sys.argv[1],provider=P(),clock=lambda:1000)
a=s.db.execute("SELECT attempt_id FROM realtime_attempts WHERE session_id='s'").fetchone()[0]
s._commit_activation('s',a,RealtimeActivation('remote-b','receipt-b'),until=time.monotonic()+5,earliest=1000)
'''
        result=subprocess.run([sys.executable,'-c',script,self.path],capture_output=True,timeout=8)
        self.assertEqual(result.returncode,37,result.stderr.decode())
        other=self.open()
        self.assertEqual(other.recovery_status('s')['state'],'revoked')
        self.assertEqual(other.recovery_status('s')['cleanup']['pending'],2)
        self.assertEqual(other.recovery_status('s')['cleanup']['attempts'],1)
        self.provider.fail_revoke=False
        self.assertEqual(other.drain_revocations(),0)


if __name__=='__main__':unittest.main()
