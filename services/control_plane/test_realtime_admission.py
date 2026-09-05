"""Actual SQLite/restart/deadline tests; provider fixtures do not qualify service tenancy."""
from contextlib import closing
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.durable_realtime import DurableRealtimeError, DurableRealtimeStore, RealtimeActivation


class Provider:
    def __init__(self):
        self.activations = self.lookups = 0
        self.revoked = []
        self.before = lambda: None
        self.before_lookup = lambda: None
        self.before_revoke = lambda: None
        self.result = RealtimeActivation('fixture-provider', 'fixture-receipt')
        self.unknown = False
        self.fail_revoke = False
        self.received_timeout = None

    def activate(self, **kwargs):
        self.activations += 1
        self.received_timeout = kwargs['timeout_seconds']
        self.before()
        return self.result

    def reconcile_activation(self, **kwargs):
        self.lookups += 1
        self.before_lookup()
        return None if self.unknown else self.result

    def revoke(self, *, provider_session_id, timeout_seconds):
        self.before_revoke()
        if self.fail_revoke:
            raise TimeoutError('fixture cleanup unavailable')
        self.revoked.append(provider_session_id)


class RealtimeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'state.sqlite')
        self.now = 1000
        self.provider = Provider()
        self.store = self.open()

    def open(self, **changes):
        args = dict(provider=self.provider, clock=lambda: self.now, ticket_ttl_seconds=1)
        args.update(changes)
        store = DurableRealtimeStore(self.path, **args)
        self.addCleanup(store.close)
        return store

    def ticket(self):
        return self.store.issue_ticket(subject='u', session_id='s')

    def activate(self, ticket, **kwargs):
        return self.store.activate(ticket=ticket, subject='u', session_id='s', **kwargs)

    def state(self):
        return self.store.db.execute("SELECT state FROM sessions WHERE session_id='s'").fetchone()[0]

    def uncertain(self):
        ticket = self.ticket()
        with patch.object(self.provider, 'activate', side_effect=TimeoutError('fixture')):
            self.error('realtime_activation_indeterminate', lambda: self.activate(ticket))
        return ticket

    def error(self, code, operation):
        with self.assertRaises(DurableRealtimeError) as error:
            operation()
        self.assertEqual(error.exception.code, code)

    def expire_trigger(self, action):
        self.store.db.create_function('test_boundary_tick', 0, lambda: (action(), 0)[1])
        self.store.db.execute("CREATE TRIGGER boundary_tick AFTER UPDATE ON sessions WHEN NEW.state='active' "
                              "BEGIN SELECT test_boundary_tick(); END")

    def test_provider_result_after_ticket_expiry_is_revoked_and_cleaned(self):
        ticket = self.ticket()
        self.provider.before = lambda: setattr(self, 'now', 1002)
        self.error('realtime_ticket_expired', lambda: self.activate(ticket))
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.provider.revoked, ['fixture-provider'])
        self.assertEqual(self.provider.activations, 1)

    def test_exact_expiry_boundary_is_not_admitted(self):
        ticket = self.ticket()
        self.now = 1001
        self.error('realtime_ticket_expired', lambda: self.activate(ticket))
        self.assertEqual(self.provider.activations, 0)
        self.assertEqual(self.state(), 'new')

    def test_expiry_at_last_transaction_check_never_exposes_active(self):
        ticket = self.ticket()
        observed = []
        other = self.open()
        def tick():
            observed.append(other.db.execute("SELECT state FROM sessions WHERE session_id='s'").fetchone()[0])
            self.now = 1001
        self.expire_trigger(tick)
        self.error('realtime_ticket_expired', lambda: self.activate(ticket))
        self.assertEqual(observed, ['activating'])
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.provider.revoked, ['fixture-provider'])

    def test_final_denial_and_cleanup_commit_before_exception(self):
        ticket = self.ticket()
        self.provider.before = lambda: setattr(self, 'now', 1001)
        self.provider.fail_revoke = True
        self.error('realtime_ticket_expired', lambda: self.activate(ticket))
        reopened = self.open()
        self.assertEqual(reopened.db.execute('SELECT state FROM sessions').fetchone()[0], 'revoked')
        self.assertEqual(reopened.pending_recovery(), ['s'])
        self.provider.fail_revoke = False
        self.assertEqual(reopened.drain_revocations(), 0)
        self.assertEqual(self.provider.activations, 1)

    def test_expired_unknown_recovery_does_not_restore_admission(self):
        self.uncertain()
        self.now = 1002
        self.error('realtime_session_revoked_or_stale', lambda: self.open().reconcile('s'))
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.provider.lookups, 1)
        self.assertEqual(self.provider.revoked, ['fixture-provider'])

    def test_no_remote_record_remains_pending_cleanup(self):
        self.uncertain()
        self.now = 1002
        self.provider.unknown = True
        self.error('realtime_activation_indeterminate', lambda: self.store.reconcile('s'))
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.store.pending_recovery(), ['s'])
        self.assertGreater(self.store.drain_revocations(), 0)
        self.assertEqual(self.provider.revoked, [])

    def test_expiry_during_readback_does_not_restore_active(self):
        self.uncertain()
        self.provider.before_lookup = lambda: setattr(self, 'now', 1002)
        self.error('realtime_ticket_expired', lambda: self.store.reconcile('s'))
        self.assertEqual(self.state(), 'revoked')

    def test_larger_constructor_ttl_does_not_extend_existing_ticket(self):
        self.uncertain()
        self.now = 1002
        other = self.open(ticket_ttl_seconds=300)
        self.error('realtime_session_revoked_or_stale', lambda: other.reconcile('s'))
        self.assertEqual(self.state(), 'revoked')

    def test_active_session_lifetime_is_not_ticket_admission_ttl(self):
        self.activate(self.ticket())
        self.now = 2000
        self.assertEqual(self.store.require_generation('s', 1)['state'], 'active')
        self.assertEqual(self.store.reconcile('s')['state'], 'active')
        self.assertEqual(self.provider.lookups, 0)
        self.store.revoke('s')
        self.assertEqual(self.state(), 'revoked')

    def test_expired_ticket_cannot_be_reissued_for_revoked_session(self):
        t = self.uncertain(); self.now = 1002
        self.provider.unknown = True
        self.error('realtime_activation_indeterminate', lambda: self.store.reconcile('s'))
        self.error('realtime_session_not_new', self.ticket)
        self.error('realtime_ticket_expired', lambda: self.activate(t))

    def test_required_host_clock_and_obsolete_caller_time_rejected(self):
        with self.assertRaises(TypeError):
            DurableRealtimeStore(self.path, provider=self.provider)
        with self.assertRaises(TypeError):
            self.store.issue_ticket(subject='u', session_id='s', now=1000)
        t = self.ticket()
        with self.assertRaises(TypeError):
            self.store.activate(ticket=t, subject='u', session_id='s', now=1000)
        self.assertEqual(self.provider.activations, 0)

    def test_clock_shape_overflow_and_invalid_configuration(self):
        for value in (True, -1, float('nan'), '1000'):
            self.now = value
            self.error('realtime_clock_invalid', self.ticket)
        self.now = 253402300799
        self.error('realtime_ticket_expiry_invalid', self.ticket)
        for kwargs in ({'clock': None}, {'maximum_workers': True}, {'maximum_workers': 17}, {'maximum_records': 1000001}):
            with self.assertRaises(ValueError): self.open(**kwargs)

    def test_private_clock_error_not_reflected_or_stored(self):
        def broken(): raise RuntimeError('private-fixture-clock-text')
        self.store.clock = broken
        self.error('realtime_clock_invalid', self.ticket)
        for p in Path(self.tmp.name).glob('state.sqlite*'):
            self.assertNotIn(b'private-fixture-clock-text', p.read_bytes())

    def test_clock_failure_after_provider_keeps_denial_and_cleanup(self):
        t = self.ticket()
        self.provider.before = lambda: setattr(self, 'now', True)
        self.error('realtime_clock_invalid', lambda: self.activate(t))
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.provider.revoked, ['fixture-provider'])

    def test_backward_clock_during_provider_call_does_not_admit(self):
        t = self.ticket()
        self.provider.before = lambda: setattr(self, 'now', 999)
        self.error('realtime_clock_rollback', lambda: self.activate(t))
        self.assertEqual(self.state(), 'revoked')

    def test_expiry_before_dispatch_after_worker_scheduling_prevents_provider(self):
        t = self.ticket(); original = self.store._calls.run
        def schedule(operation, **kwargs):
            self.now = 1002
            return original(operation, **kwargs)
        with patch.object(self.store._calls, 'run', side_effect=schedule):
            self.error('realtime_activation_indeterminate', lambda: self.activate(t))
        self.assertEqual(self.provider.activations, 0)
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.store.pending_recovery(), ['s'])

    def test_revoke_before_worker_prevents_provider(self):
        t = self.ticket(); original = self.store._calls.run
        def schedule(operation, **kwargs):
            self.open().revoke('s')
            return original(operation, **kwargs)
        with patch.object(self.store._calls, 'run', side_effect=schedule):
            self.error('realtime_activation_indeterminate', lambda: self.activate(t))
        self.assertEqual(self.provider.activations, 0)
        self.assertEqual(self.state(), 'revoked')

    def test_provider_receives_remaining_ticket_lifetime(self):
        self.activate(self.ticket(), timeout_seconds=10)
        self.assertGreater(self.provider.received_timeout, 0)
        self.assertLessEqual(self.provider.received_timeout, 1)

    def test_issuance_samples_clock_after_database_lock(self):
        other = self.open(); begun = threading.Event(); values = []
        def worker():
            begun.set()
            values.append(self.ticket())
        with other._storage.transaction():
            t = threading.Thread(target=worker); t.start(); self.assertTrue(begun.wait(1))
            self.now = 1005
        t.join(2); self.assertFalse(t.is_alive()); self.assertEqual(len(values), 1)
        self.assertEqual(self.store.db.execute('SELECT expires_at FROM tickets').fetchone()[0], 1006)

    def test_activation_lock_wait_cannot_reuse_old_now(self):
        ticket = self.ticket(); other = self.open(); begun = threading.Event(); errors = []
        def worker():
            begun.set()
            try: self.activate(ticket)
            except DurableRealtimeError as e: errors.append(e.code)
        with other._storage.transaction():
            t = threading.Thread(target=worker); t.start(); self.assertTrue(begun.wait(1))
            self.now = 1002
        t.join(2); self.assertFalse(t.is_alive())
        self.assertEqual(errors, ['realtime_ticket_expired']); self.assertEqual(self.provider.activations, 0)

    def test_issuance_last_check_rolls_back_session_and_ticket(self):
        with patch.object(self.store, 'clock', side_effect=[1000, 1001]):
            self.error('realtime_ticket_expired', self.ticket)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM tickets').fetchone()[0], 0)

    def test_reservation_last_check_rolls_back_ticket_consumption(self):
        t = self.ticket()
        with patch.object(self.store, 'clock', side_effect=[1000, 1001]):
            self.error('realtime_ticket_expired', lambda: self.activate(t))
        self.assertEqual(self.state(), 'new')
        self.assertEqual(self.store.db.execute('SELECT state FROM tickets').fetchone()[0], 'issued')
        self.assertEqual(self.provider.activations, 0)

    def test_missing_consumed_ticket_is_not_fresh_authority(self):
        self.uncertain()
        self.store.db.execute('DELETE FROM tickets')
        self.error('realtime_session_revoked_or_stale', lambda: self.store.reconcile('s'))
        self.assertEqual(self.state(), 'revoked')
        self.assertEqual(self.provider.revoked, ['fixture-provider'])

    def test_ambiguous_consumed_tickets_cannot_authorize_recovery(self):
        self.uncertain()
        self.store.db.execute("INSERT INTO tickets SELECT 'other-digest',subject,session_id,expires_at,'consumed' FROM tickets")
        self.error('realtime_session_revoked_or_stale', lambda: self.store.reconcile('s'))
        self.assertEqual(self.state(), 'revoked')

    def test_missing_marked_tables_never_recreated(self):
        for table in ('sessions', 'tickets', 'realtime_attempts', 'realtime_revoke_outbox'):
            with self.subTest(table=table), tempfile.TemporaryDirectory() as d:
                path = d+'/r.db'; s = DurableRealtimeStore(path, provider=self.provider, clock=lambda:1000); s.close()
                with closing(sqlite3.connect(path)) as db, db: db.execute('DROP TABLE '+table)
                with self.assertRaisesRegex(ValueError, 'realtime_schema_integrity_invalid'):
                    DurableRealtimeStore(path, provider=self.provider, clock=lambda:1000)
                with closing(sqlite3.connect(path)) as db:
                    self.assertIsNone(db.execute('SELECT name FROM sqlite_master WHERE name=?',(table,)).fetchone())

    def test_unmarked_existing_state_is_not_auto_migrated(self):
        self.ticket()
        self.store.db.execute("DELETE FROM hepta_component_schema WHERE component='realtime'")
        with self.assertRaisesRegex(ValueError, 'realtime_unmarked_schema_rejected'): self.open()
        self.assertEqual(self.store.db.execute('SELECT state FROM tickets').fetchone()[0], 'issued')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM realtime_attempts').fetchone()[0], 0)

    def test_intact_v2_reopen_preserves_deadline_and_pending_state(self):
        self.uncertain(); before = [tuple(r) for r in self.store.db.execute('SELECT * FROM tickets')]
        other = self.open()
        self.assertEqual(before,[tuple(r) for r in other.db.execute('SELECT * FROM tickets')])
        self.assertEqual(other.reconcile('s')['state'], 'active')

    def test_caller_deadline_at_result_commit_keeps_uncertainty(self):
        ticket = self.ticket(); ticks = [0.0]
        self.expire_trigger(lambda: ticks.__setitem__(0, 11.0))
        with patch('services.control_plane.durable_realtime.time.monotonic', side_effect=lambda:ticks[0]):
            self.error('realtime_deadline_expired', lambda: self.activate(ticket, timeout_seconds=10))
        self.assertEqual(self.state(), 'indeterminate')
        self.assertEqual(self.provider.revoked, [])

    def test_expiry_cleanup_does_not_reset_exhausted_caller_budget(self):
        ticket = self.ticket(); ticks = [0.0]
        def expire(): self.now = 1001; ticks[0] = 11.0
        self.expire_trigger(expire)
        with patch('services.control_plane.durable_realtime.time.monotonic', side_effect=lambda:ticks[0]):
            self.error('realtime_ticket_expired', lambda: self.activate(ticket, timeout_seconds=10))
        self.assertEqual(self.state(), 'revoked'); self.assertEqual(self.provider.revoked, [])
        self.assertEqual(self.store.pending_recovery(), ['s'])
        self.assertEqual(self.store.drain_revocations(), 0)

    def test_revocation_batch_shares_one_timeout_not_one_per_job(self):
        with self.store._storage.transaction():
            for i in range(4): self.store._queue_revoke('s'+str(i), 'p'+str(i))
        release = threading.Event(); self.addCleanup(release.set)
        started = []
        def enter():
            started.append(True)
            release.wait(2)
        self.provider.before_revoke = enter
        start = time.monotonic()
        pending = self.store.drain_revocations(limit=4, timeout_seconds=.05)
        elapsed = time.monotonic()-start
        release.set()
        self.assertLess(elapsed, .3); self.assertEqual(pending, 4)
        self.assertEqual(len(started), 1)
        time.sleep(.02)
        self.assertLessEqual(len(self.provider.revoked), 1)

    def test_actual_process_exit_after_expired_result_retains_cleanup(self):
        script = '''
import os,sys
from services.control_plane.durable_realtime import DurableRealtimeStore,RealtimeActivation,DurableRealtimeError
now=[1000]
class Provider:
 def activate(self,**kw): now[0]=1002; return RealtimeActivation('crash-remote','crash-receipt')
 def reconcile_activation(self,**kw): return None
 def revoke(self,**kw): os._exit(29)
s=DurableRealtimeStore(sys.argv[1],provider=Provider(),clock=lambda:now[0],ticket_ttl_seconds=1)
t=s.issue_ticket(subject='u',session_id='s')
s.activate(ticket=t,subject='u',session_id='s')
'''
        r = subprocess.run([sys.executable,'-c',script,self.path],capture_output=True,timeout=8)
        self.assertEqual(r.returncode,29,r.stderr.decode())
        other = self.open(); self.assertEqual(self.state(),'revoked')
        self.assertEqual(other.pending_recovery(),['s'])
        self.assertEqual(other.drain_revocations(),0)
        self.assertEqual(self.provider.activations,0)
        self.assertEqual(self.provider.revoked,['crash-remote'])


if __name__ == '__main__':
    unittest.main()
