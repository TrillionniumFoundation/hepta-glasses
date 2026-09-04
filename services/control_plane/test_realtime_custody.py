"""Regression tests: local SQLite and fake providers, never physical evidence."""
import sqlite3
from contextlib import closing
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
        self.block = False
        self.fail = False
        self.fail_revoke = False
        self.activation_calls = 0
        self.revoked = []
        self.receipt = RealtimeActivation("test-provider-session", "test-provider-receipt")

    def activate(self, **kwargs):
        self.activation_calls += 1
        self.entered.set()
        if self.block and not self.release.wait(3):
            raise TimeoutError("test barrier")
        if self.fail:
            raise TimeoutError("test uncertain dispatch")
        return self.receipt

    def reconcile_activation(self, **kwargs):
        return self.receipt

    def revoke(self, *, provider_session_id, timeout_seconds):
        if self.fail_revoke:
            raise TimeoutError("test revoke unavailable")
        self.revoked.append(provider_session_id)


class RealtimeCustodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "realtime.db")
        self.provider = Provider()
        self.stores = []
        self.store = self.open_store()

    def open_store(self, **kwargs):
        store = DurableRealtimeStore(self.path, provider=self.provider, **kwargs)
        self.stores.append(store)
        return store

    def tearDown(self):
        self.provider.release.set()
        for store in self.stores:
            try:
                store.close()
            except sqlite3.ProgrammingError:
                pass
        self.tmp.cleanup()

    def ticket(self, subject="owner", session_id="session"):
        return self.store.issue_ticket(subject=subject, session_id=session_id, now=10)

    def async_activate(self, ticket):
        values, errors = [], []
        def run():
            try:
                values.append(self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11))
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(self.provider.entered.wait(2))
        return worker, values, errors

    def test_late_activation_after_cross_connection_revoke_never_restores_authority(self):
        self.provider.block = True
        worker, values, errors = self.async_activate(self.ticket())
        second = self.open_store()
        second.revoke("session")
        self.provider.release.set()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(values, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DurableRealtimeError)
        self.assertEqual(second.db.execute("SELECT state FROM sessions").fetchone()[0], "revoked")
        self.assertEqual(self.provider.revoked, ["test-provider-session"])
        self.assertEqual(second.drain_revocations(), 0)
        with self.assertRaises(DurableRealtimeError):
            second.require_generation("session", 2)

    def test_late_activation_error_does_not_erase_revocation(self):
        self.provider.block = self.provider.fail = True
        worker, _, _ = self.async_activate(self.ticket())
        self.open_store().revoke("session")
        self.provider.release.set()
        worker.join(3)
        self.assertEqual(self.store.db.execute("SELECT state FROM sessions").fetchone()[0], "revoked")
        self.assertEqual(self.store.pending_recovery(), ["session"])

    def test_session_subject_collision_rejected_before_ticket_or_provider(self):
        self.ticket(subject="subject-A")
        with self.assertRaisesRegex(DurableRealtimeError, "subject_conflict"):
            self.open_store().issue_ticket(subject="subject-B", session_id="session", now=10)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 1)
        self.assertEqual(self.provider.activation_calls, 0)

    def test_process_death_after_durable_preparation_recovers_without_activation_replay(self):
        path = str(Path(self.tmp.name) / "crash.db")
        script = '''
import os, sys
from services.control_plane.durable_realtime import DurableRealtimeStore
class Provider:
    def activate(self, **kwargs): os._exit(73)
s = DurableRealtimeStore(sys.argv[1], provider=Provider())
t = s.issue_ticket(subject="owner",session_id="crashed",now=10)
s.activate(ticket=t,subject="owner",session_id="crashed",now=11)
'''
        run = subprocess.run([sys.executable, "-c", script, path], timeout=5, capture_output=True)
        self.assertEqual(run.returncode, 73, run.stderr.decode())
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT state FROM sessions").fetchone()[0], "activating")
        recovered = DurableRealtimeStore(path, provider=self.provider)
        try:
            self.assertEqual(recovered.pending_recovery(), ["crashed"])
            self.assertEqual(recovered.reconcile("crashed")["state"], "active")
            self.assertEqual(self.provider.activation_calls, 0)
        finally:
            recovered.close()

    def test_failed_terminal_transaction_remains_recoverable(self):
        ticket = self.ticket()
        self.store.db.execute("CREATE TRIGGER refuse_active BEFORE UPDATE ON sessions "
                              "WHEN NEW.state='active' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        self.assertEqual(self.store.db.execute("SELECT state FROM sessions").fetchone()[0], "activating")
        self.store.db.execute("DROP TRIGGER refuse_active")
        self.assertEqual(self.open_store().reconcile("session")["state"], "active")
        self.assertEqual(self.provider.activation_calls, 1)

    def test_provider_revoke_failure_is_durable_and_retryable_cleanup_only(self):
        ticket = self.ticket()
        self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        self.provider.fail_revoke = True
        with self.assertRaisesRegex(DurableRealtimeError, "revoke_pending"):
            self.store.revoke("session")
        second = self.open_store()
        self.assertEqual(second.pending_recovery(), ["session"])
        self.provider.fail_revoke = False
        self.assertEqual(second.drain_revocations(), 0)
        self.assertEqual(self.provider.activation_calls, 1)

    def test_caller_timeout_keeps_single_use_ticket_and_recovery(self):
        self.provider.block = True
        ticket = self.ticket()
        start = time.monotonic()
        with self.assertRaisesRegex(DurableRealtimeError, "indeterminate"):
            self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11, timeout_seconds=.03)
        self.assertLess(time.monotonic() - start, 1)
        with self.assertRaisesRegex(DurableRealtimeError, "replayed"):
            self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        self.provider.release.set()
        self.assertEqual(self.store.reconcile("session")["state"], "active")
        self.assertEqual(self.provider.activation_calls, 1)

    def test_none_lookup_is_not_non_execution_proof(self):
        ticket = self.ticket()
        self.provider.fail = True
        with self.assertRaises(DurableRealtimeError):
            self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        self.provider.receipt = None
        with self.assertRaisesRegex(DurableRealtimeError, "indeterminate"):
            self.store.reconcile("session")
        self.assertEqual(self.provider.activation_calls, 1)

    def test_reissue_and_revocation_do_not_reset_single_use_authority(self):
        old = self.ticket()
        current = self.ticket()
        with self.assertRaisesRegex(DurableRealtimeError, "replayed"):
            self.store.activate(ticket=old, subject="owner", session_id="session", now=11)
        self.store.activate(ticket=current, subject="owner", session_id="session", now=11)
        self.store.revoke("session")
        with self.assertRaisesRegex(DurableRealtimeError, "not_new"):
            self.ticket()

    def test_generation_and_boolean_rejection(self):
        ticket = self.ticket()
        self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        with self.assertRaises(DurableRealtimeError):
            self.store.require_generation("session", True)
        self.assertEqual(self.store.interrupt("session", generation=1)["generation"], 2)
        with self.assertRaisesRegex(DurableRealtimeError, "stale"):
            self.store.interrupt("session", generation=1)

    def test_malformed_provider_receipt_remains_recoverable(self):
        ticket = self.ticket()
        self.provider.receipt = RealtimeActivation("", "")
        with self.assertRaisesRegex(DurableRealtimeError, "response_invalid"):
            self.store.activate(ticket=ticket, subject="owner", session_id="session", now=11)
        self.assertEqual(self.store.pending_recovery(), ["session"])

    def test_capacity_and_invalid_deadlines_fail_before_effect(self):
        limited = self.open_store(maximum_records=1)
        self.ticket()
        with self.assertRaisesRegex(DurableRealtimeError, "capacity"):
            limited.issue_ticket(subject="owner", session_id="second", now=10)
        for value in [True, float("nan"), float("inf"), 0, -1, 61]:
            with self.assertRaises(DurableRealtimeError):
                self.store.activate(ticket="x", subject="owner", session_id="s", now=11, timeout_seconds=value)
        self.assertEqual(self.provider.activation_calls, 0)

    def test_unknown_schema_is_not_silently_reinterpreted(self):
        self.store.db.execute("UPDATE hepta_component_schema SET version=999 WHERE component='realtime'")
        with self.assertRaisesRegex(ValueError, "schema_migration_required"):
            self.open_store()


if __name__ == "__main__":
    unittest.main()
