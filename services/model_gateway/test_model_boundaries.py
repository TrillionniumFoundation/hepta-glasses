"""Hostile local custody tests; fixture providers are not live provider evidence."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from services.control_plane.bounded_calls import CallOutcome
from services.model_gateway.production import (
    ModelExecutionError, ProductionModelGateway, ProviderResult, context_bytes,
)


class Provider:
    def __init__(self):
        self.calls = self.reads = 0
        self.fail = False
        self.before = lambda kw: None
        self.read_before = lambda kw: None
        self.result = lambda kw: ProviderResult("inert-answer-sentinel", "req_fixture", "resp_fixture", kw["request_key"])

    def generate(self, **kw):
        self.calls += 1
        self.before(kw)
        if self.fail:
            raise RuntimeError("never expose provider error sentinel")
        return self.result(kw)

    def reconcile(self, **kw):
        self.reads += 1
        self.read_before(kw)
        return self.result(kw)


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "model.sqlite")
        self.now = 1000
        self.provider = Provider()
        self.gateway = self.open()

    def open(self, **changes):
        args = dict(provider=self.provider, provider_binding="fixture", clock=lambda: self.now)
        args.update(changes)
        g = ProductionModelGateway(self.path, **args)
        self.addCleanup(g.close)
        return g

    def execute(self, *, gateway=None, **changes):
        args = dict(subject="user", session_id="session", idempotency_key="key", question="inert-question-sentinel",
                    context={"purpose": "inert-context-sentinel"}, expires_at=1100, timeout_seconds=1)
        args.update(changes)
        return (gateway or self.gateway).execute(**args)

    def status(self, **changes):
        return self.gateway.status(**dict(subject="user", idempotency_key="key", **changes))

    def error(self, code, operation):
        with self.assertRaises(ModelExecutionError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def uncertain(self):
        self.provider.fail = True
        self.error("model_effect_indeterminate", self.execute)
        self.provider.fail = False

    def test_restart_preserves_commit_and_never_caches_answer(self):
        _, first = self.execute()
        self.assertEqual(first, self.open().status(subject="user", idempotency_key="key"))
        self.error("model_duplicate_committed", lambda: self.execute(gateway=self.open()))
        for p in Path(self.temp.name).glob("model.sqlite*"):
            raw = p.read_bytes()
            for marker in (b"inert-answer-sentinel", b"inert-question-sentinel", b"inert-context-sentinel", b"req_fixture", b"resp_fixture"):
                self.assertNotIn(marker, raw)

    def test_subject_scoped_keys_and_remote_attempt_keys(self):
        a = self.execute()[1]
        b = self.execute(subject="another")[1]
        self.assertNotEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(self.provider.calls, 2)
        keys = [r[0] for r in self.gateway.db.execute("SELECT request_key FROM requests")]
        self.assertEqual(len(set(keys)), 2)

    def test_session_drift_conflicts(self):
        self.execute()
        self.error("model_idempotency_conflict", lambda: self.execute(session_id="another"))

    def test_authority_extension_conflicts(self):
        self.execute()
        self.error("model_idempotency_conflict", lambda: self.execute(expires_at=1101))

    def test_policy_and_provider_binding_change_rejected(self):
        for changes in ({"provider_binding": "other"}, {"daily_request_limit": 2}, {"maximum_readbacks": 2}, {"maximum_workers": 1}):
            with self.subTest(changes=changes):
                self.error("model_policy_migration_required", lambda: self.open(**changes))

    def test_unversioned_predecessor_is_not_ignored(self):
        p = str(Path(self.temp.name) / "legacy.sqlite")
        with closing(sqlite3.connect(p)) as db, db:
            db.execute("CREATE TABLE requests(idempotency_key TEXT,state TEXT)")
            db.execute("INSERT INTO requests VALUES('unfinished','prepared')")
        self.error("model_unversioned_migration_required", lambda: ProductionModelGateway(p, provider=self.provider, provider_binding="fixture", clock=lambda: self.now))
        with closing(sqlite3.connect(p)) as db, db:
            self.assertEqual(db.execute("SELECT * FROM requests").fetchall(), [("unfinished", "prepared")])

    def test_empty_legacy_tables_still_require_reviewed_migration(self):
        p = str(Path(self.temp.name) / "legacy-empty.sqlite")
        with closing(sqlite3.connect(p)) as db, db:
            db.execute("CREATE TABLE revoked_sessions(session_id TEXT)")
        self.error("model_unversioned_migration_required", lambda: ProductionModelGateway(p, provider=self.provider, provider_binding="fixture", clock=lambda: self.now))

    def test_removed_schema_marker_is_not_recreated(self):
        self.gateway.db.execute("DELETE FROM hepta_component_schema WHERE component='model_gateway'")
        self.error("model_unversioned_migration_required", self.open)

    def test_unknown_schema_version_fails(self):
        self.gateway.db.execute("UPDATE hepta_component_schema SET version=9 WHERE component='model_gateway'")
        with self.assertRaisesRegex(ValueError, "migration_required"):
            self.open()

    def test_missing_policy_row_cannot_reset_suspension(self):
        self.gateway.db.execute("DELETE FROM model_policy")
        self.error("model_schema_integrity_invalid", self.open)

    def test_dropped_revocation_table_cannot_reset_denials(self):
        self.gateway.revoke_session("session", subject="user")
        self.gateway.db.execute("DROP TABLE revoked_sessions")
        self.error("model_schema_integrity_invalid", self.open)

    def test_known_provider_binding_must_match_configured_identity(self):
        from services.model_gateway.responses_provider import ResponsesProvider
        provider = ResponsesProvider("fixture-model", "fixture-deployment", lambda: "unused")
        self.error("model_provider_configuration_binding_mismatch", lambda: self.open(provider=provider))

    def test_boolean_nonfinite_and_oversized_deadlines(self):
        for x in (True, False, float("nan"), float("inf"), 0, -1, 61, "1"):
            with self.subTest(value=x):
                self.error("model_deadline_invalid", lambda: self.execute(timeout_seconds=x))
        self.assertEqual(self.provider.calls, 0)

    def test_invalid_identifiers_do_not_dispatch(self):
        for x in ("", " ", "a\nb", "a/b", "x" * 129, True, []):
            with self.subTest(value=x):
                self.error("model_binding_invalid", lambda: self.execute(subject=x))

    def test_invalid_and_expired_authority(self):
        for x in (True, float("inf"), "1001"):
            self.error("model_deadline_invalid", lambda: self.execute(expires_at=x))
        self.error("model_authority_expired", lambda: self.execute(expires_at=1000))
        self.error("model_authority_lifetime_invalid", lambda: self.execute(expires_at=1301))

    def test_question_limits_and_invalid_unicode(self):
        for x in ("", " ", "x" * 8001, True, "\ud800"):
            self.error("model_question_invalid", lambda: self.execute(question=x))

    def test_context_nonfinite_keys_types_and_huge_numbers(self):
        for x in ({1: "value"}, {"x": object()}, {"x": float("nan")}, {"x": 1 << 54}, {"x": "\ud800"}, []):
            with self.subTest(value=repr(x)), self.assertRaises(ModelExecutionError):
                self.execute(context=x)

    def test_context_depth_cycle_nodes_and_encoded_byte_limits(self):
        cycle = {}; cycle["self"] = cycle
        for x in (cycle, {"x": "界" * 20000}, {"x": [0] * 257}, {"x": [[0] * 256] * 10}):
            with self.assertRaises(ModelExecutionError):
                context_bytes(x)

    def test_context_is_defensive_snapshot(self):
        original = {"x": ["before"]}
        def mutate(kw):
            kw["context"]["x"].append("provider-change")
        self.provider.before = mutate
        self.execute(context=original)
        self.assertEqual(original, {"x": ["before"]})

    def test_provider_error_text_and_chain_not_exposed(self):
        self.provider.fail = True
        error = self.error("model_effect_indeterminate", self.execute)
        self.assertIsNone(error.__cause__)
        self.assertNotIn("sentinel", repr(error))

    def test_wrong_provider_request_binding_rejected(self):
        self.provider.result = lambda kw: ProviderResult("answer", "req", "resp", "0" * 64)
        self.error("model_provider_binding_invalid", self.execute)
        self.assertEqual(self.status().state, "indeterminate")

    def test_mutable_or_untyped_provider_result_rejected(self):
        self.provider.result = lambda kw: {"answer": "answer"}
        self.error("model_provider_binding_invalid", self.execute)

    def test_empty_oversized_and_invalid_unicode_answers(self):
        for i, answer in enumerate(("", " ", "x" * 65537, "界" * 30000, "\ud800")):
            self.provider.result = lambda kw, a=answer: ProviderResult(a, "req", "resp", kw["request_key"])
            self.error("model_provider_response_invalid", lambda: self.execute(idempotency_key=f"key{i}"))

    def test_provider_identifiers_cannot_inject_log_or_grow_database(self):
        for i, value in enumerate(("\n", "x" * 129, "a b", [])):
            self.provider.result = lambda kw, v=value: ProviderResult("answer", v, "resp", kw["request_key"])
            self.error("model_binding_invalid", lambda: self.execute(idempotency_key=f"key{i}"))

    def test_revoke_unknown_session_before_admission(self):
        self.gateway.revoke_session("session", subject="user")
        self.error("model_delivery_revoked", lambda: self.execute(gateway=self.open()))
        self.assertEqual(self.provider.calls, 0)

    def test_cancel_unknown_request_before_admission(self):
        self.gateway.cancel(subject="user", idempotency_key="key")
        self.error("model_delivery_revoked", lambda: self.execute(gateway=self.open()))

    def test_session_revocation_is_subject_scoped(self):
        self.gateway.revoke_session("session", subject="other")
        self.execute()

    def test_revocation_during_provider_call_prevents_commit(self):
        other = self.open()
        self.provider.before = lambda kw: other.revoke_session("session", subject="user")
        with self.assertRaises(ModelExecutionError):
            self.execute()
        self.assertEqual(self.status().state, "cancelled")
        self.assertIsNone(self.status().answer_digest)

    def test_cancellation_during_provider_call_prevents_commit(self):
        self.provider.before = lambda kw: self.open().cancel(subject="user", idempotency_key="key")
        with self.assertRaises(ModelExecutionError):
            self.execute()
        self.assertEqual(self.status().state, "cancelled")

    def test_revoke_after_commit_preserves_historical_fact_but_blocks_delivery(self):
        self.execute()
        result = self.gateway.revoke_session("session", subject="user")
        self.assertFalse(result["remote_cancellation_confirmed"])
        self.assertEqual(self.status().state, "committed")
        self.assertTrue(self.status().delivery_revoked)
        self.error("model_delivery_revoked", self.execute)

    def test_denial_remains_available_during_clock_failure(self):
        self.now = True
        self.gateway.revoke_session("session", subject="user")
        self.now = 1000
        self.error("model_delivery_revoked", self.execute)

    def test_denial_is_idempotent(self):
        for _ in range(10):
            self.gateway.cancel(subject="user", idempotency_key="key")
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM model_events").fetchone()[0], 1)

    def test_denial_at_capacity_suspends_registry_without_eviction(self):
        p = str(Path(self.temp.name) / "small.sqlite")
        g = ProductionModelGateway(p, provider=self.provider, provider_binding="fixture", clock=lambda: self.now, maximum_entries=1)
        self.addCleanup(g.close)
        g.cancel(subject="user", idempotency_key="a")
        self.assertTrue(g.cancel(subject="user", idempotency_key="b")["registry_suspended"])
        self.error("model_delivery_revoked", lambda: self.execute(gateway=g, subject="unrelated"))
        self.assertEqual(g.db.execute("SELECT COUNT(*) FROM model_cancellations").fetchone()[0], 1)

    def test_invalid_clock_and_rollback_after_restart(self):
        self.execute()
        other = self.open()
        self.now = 999
        self.error("model_clock_rollback", lambda: self.execute(gateway=other, idempotency_key="new"))
        self.now = True
        self.error("model_clock_invalid", lambda: self.execute(idempotency_key="new"))

    def test_expiry_during_provider_call_rejects_answer(self):
        self.provider.before = lambda kw: setattr(self, "now", 1100)
        self.error("model_authority_expired", self.execute)
        self.assertEqual(self.status().state, "indeterminate")

    def test_expiry_at_final_commit_check_rolls_back(self):
        original = self.gateway._event
        def late(db, event, key, now):
            original(db, event, key, now)
            if event == "committed":
                self.now = 1100
        with patch.object(self.gateway, "_event", side_effect=late):
            self.error("model_authority_expired", self.execute)
        self.assertEqual(self.status().state, "indeterminate")
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM model_events WHERE event='committed'").fetchone()[0], 0)

    def test_commit_storage_failure_rolls_back_answer_and_event(self):
        self.gateway.db.execute("CREATE TRIGGER deny_commit BEFORE UPDATE ON requests WHEN NEW.state='committed' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute()
        self.assertEqual(self.status().state, "indeterminate")
        self.assertIsNone(self.status().answer_digest)
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM model_events WHERE event='committed'").fetchone()[0], 0)

    def test_audit_reservation_failure_prevents_dispatch(self):
        self.gateway.db.execute("CREATE TRIGGER deny_event BEFORE INSERT ON model_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)

    def test_readback_only_after_failure_and_fresh_binding(self):
        self.uncertain()
        answer, receipt = self.execute(gateway=self.open())
        self.assertEqual(answer, "inert-answer-sentinel")
        self.assertEqual(receipt.readbacks, 1)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.reads, 1)

    def test_unknown_readback_is_not_new_submission(self):
        self.uncertain()
        self.provider.result = lambda kw: None
        self.error("model_effect_indeterminate", self.execute)
        self.assertEqual(self.provider.calls, 1)

    def test_readback_budget_is_durable(self):
        self.uncertain()
        self.provider.result = lambda kw: None
        for _ in range(3):
            self.error("model_effect_indeterminate", lambda: self.execute(gateway=self.open()))
        self.error("model_readback_budget_exhausted", self.execute)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.provider.reads, 3)

    def test_revocation_during_readback_rejects_answer(self):
        self.uncertain()
        self.provider.read_before = lambda kw: self.open().revoke_session("session", subject="user")
        with self.assertRaises(ModelExecutionError):
            self.execute()
        self.assertEqual(self.status().state, "cancelled")

    def test_older_claim_is_fenced_at_final_commit(self):
        def change(kw):
            with self.open().storage.transaction() as db:
                db.execute("UPDATE requests SET claim='replacement' WHERE request_key=?", (kw["request_key"],))
        self.provider.before = change
        self.error("model_attempt_fenced", self.execute)
        self.assertIsNone(self.status().answer_digest)

    def test_worker_pool_not_started_cannot_erase_request_or_replay(self):
        with patch.object(self.gateway._calls, "run", return_value=CallOutcome("not_started")):
            self.error("model_effect_indeterminate", self.execute)
        self.assertEqual(self.status().state, "indeterminate")
        self.assertEqual(self.provider.calls, 0)
        self.execute()
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.reads, 1)

    def test_actual_late_worker_does_not_commit(self):
        entered, release = threading.Event(), threading.Event()
        def block(kw):
            entered.set()
            release.wait(2)
        self.provider.before = block
        self.error("model_effect_indeterminate", lambda: self.execute(timeout_seconds=0.05))
        self.assertTrue(entered.is_set())
        release.set()
        time.sleep(0.03)
        self.assertEqual(self.status().state, "indeterminate")
        self.assertIsNone(self.status().answer_digest)

    def test_actual_hung_workers_exhaust_fixed_pool(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.provider.before = lambda kw: release.wait(2)
        for i in range(5):
            self.error("model_effect_indeterminate", lambda: self.execute(idempotency_key=f"key{i}", timeout_seconds=0.03))
        self.assertEqual(self.provider.calls, 4)
        release.set()
        time.sleep(0.03)

    def test_duplicate_connections_cannot_double_dispatch(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.provider.before = lambda kw: (entered.set(), release.wait(2))
        results = []
        thread = threading.Thread(target=lambda: results.append(self.execute()))
        thread.start()
        self.assertTrue(entered.wait(1))
        self.error("model_request_in_progress", lambda: self.execute(gateway=self.open()))
        release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertEqual(self.provider.calls, 1)

    def test_quota_is_atomic_across_connections(self):
        p = str(Path(self.temp.name) / "quota.sqlite")
        args = dict(provider=self.provider, provider_binding="fixture", clock=lambda: self.now, daily_request_limit=1)
        a, b = ProductionModelGateway(p, **args), ProductionModelGateway(p, **args)
        self.addCleanup(a.close); self.addCleanup(b.close)
        barrier, results = threading.Barrier(2), []
        def run(g, key):
            barrier.wait()
            try:
                self.execute(gateway=g, idempotency_key=key)
                results.append("success")
            except ModelExecutionError as e:
                results.append(e.code)
        ts = [threading.Thread(target=run, args=(a, "a")), threading.Thread(target=run, args=(b, "b"))]
        for t in ts: t.start()
        for t in ts: t.join(2)
        self.assertEqual(sorted(results), ["model_quota_exhausted", "success"])
        self.assertEqual(self.provider.calls, 1)

    def test_lock_wait_does_not_extend_authority(self):
        other = self.open()
        started, results = threading.Event(), []
        def run():
            started.set()
            try: self.execute()
            except ModelExecutionError as e: results.append(e.code)
        with other.storage.transaction():
            thread = threading.Thread(target=run); thread.start()
            self.assertTrue(started.wait(1))
            self.now = 1100
        thread.join(2)
        self.assertEqual(results, ["model_authority_expired"])
        self.assertEqual(self.provider.calls, 0)

    def test_lock_wait_samples_new_quota_day(self):
        self.now = 86399
        other = self.open()
        started, results = threading.Event(), []
        def run():
            started.set()
            results.append(self.execute(expires_at=86500))
        with other.storage.transaction():
            thread = threading.Thread(target=run); thread.start()
            self.assertTrue(started.wait(1))
            self.now = 86400
        thread.join(2)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.gateway.db.execute("SELECT day FROM requests").fetchone()[0], 1)

    def test_readback_claim_is_serialized_across_connections(self):
        self.uncertain()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.provider.read_before = lambda kw: (entered.set(), release.wait(2))
        results = []
        t = threading.Thread(target=lambda: results.append(self.execute())); t.start()
        self.assertTrue(entered.wait(1))
        self.error("model_request_in_progress", lambda: self.execute(gateway=self.open()))
        release.set(); t.join(2)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.provider.reads, 1)

    def test_recovery_inventory_bounded_and_subject_scoped(self):
        self.uncertain()
        self.assertEqual(len(self.gateway.recoverable(subject="user")), 1)
        self.assertEqual(self.gateway.recoverable(subject="other"), ())
        for limit in (True, 0, 101):
            self.error("model_inventory_limit_invalid", lambda: self.gateway.recoverable(subject="user", limit=limit))
        self.error("model_request_unknown", lambda: self.gateway.status(subject="other", idempotency_key="key"))

    def test_actual_process_exit_after_reservation_only_allows_readback(self):
        script = '''
import os,sys
from services.model_gateway.production import ProductionModelGateway
class P:
 def generate(self,**kw): os._exit(23)
 def reconcile(self,**kw): raise AssertionError('not reached')
g=ProductionModelGateway(sys.argv[1],provider=P(),provider_binding='fixture',clock=lambda:1000)
g.execute(subject='user',session_id='session',idempotency_key='key',question='inert-question-sentinel',context={'purpose':'inert-context-sentinel'},expires_at=1100,timeout_seconds=1)
'''
        result = subprocess.run([sys.executable, "-c", script, self.path], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        self.assertEqual(self.status().state, "prepared")
        self.now = 1003
        _, receipt = self.execute(gateway=self.open())
        self.assertEqual(receipt.state, "committed")
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.provider.reads, 1)

    def test_actual_process_exit_before_reservation_commit_leaves_no_request(self):
        script = '''
import os,sys
from services.model_gateway.production import ProductionModelGateway
class P:
 def generate(self,**kw): raise AssertionError('not reached')
 def reconcile(self,**kw): raise AssertionError('not reached')
g=ProductionModelGateway(sys.argv[1],provider=P(),provider_binding='fixture',clock=lambda:1000)
original=g._event
def stop(*args):
 original(*args)
 os._exit(24)
g._event=stop
g.execute(subject='user',session_id='session',idempotency_key='key',question='inert-question-sentinel',context={'purpose':'inert-context-sentinel'},expires_at=1100)
'''
        result = subprocess.run([sys.executable, "-c", script, self.path], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 24, result.stderr.decode())
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM model_events").fetchone()[0], 0)

    def test_actual_process_exit_after_revocation_retains_denial(self):
        script = '''
import os,sys
from services.model_gateway.production import ProductionModelGateway
class P:
 def generate(self,**kw): raise AssertionError('not reached')
 def reconcile(self,**kw): raise AssertionError('not reached')
g=ProductionModelGateway(sys.argv[1],provider=P(),provider_binding='fixture',clock=lambda:1000)
g.revoke_session('session',subject='user')
os._exit(25)
'''
        result = subprocess.run([sys.executable, "-c", script, self.path], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 25, result.stderr.decode())
        self.error("model_delivery_revoked", lambda: self.execute(gateway=self.open()))


if __name__ == "__main__":
    unittest.main()
