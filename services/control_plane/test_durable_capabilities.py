"""Real SQLite/restart/race tests; adapter fixtures are not provider evidence."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from services.control_plane.bounded_calls import CallOutcome
from services.control_plane.capabilities import (
    CapabilityError, CapabilityRequest, CapabilitySpec, DecisionLease,
    RiskTier, TrustClass, canonical_digest,
)
from services.control_plane.durable_capabilities import (
    DurableCapabilityGateway, ProviderObservation,
)


class Adapter:
    def __init__(self):
        self.calls = 0
        self.reads = 0
        self.operations = []
        self.result = "applied"
        self.terminal = True
        self.failure = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.transform = lambda value: value

    def observation(self, request, operation_id):
        return self.transform(ProviderObservation(operation_id, "reminder-v1",
            canonical_digest(dict(request.arguments)), self.result, self.terminal,
            "record-1" if self.result == "applied" else None))

    def execute(self, request, operation_id):
        self.calls += 1
        self.operations.append(operation_id)
        self.entered.set()
        if self.block:
            self.release.wait(2)
        if self.failure:
            raise RuntimeError("provider-private-detail-must-not-persist")
        return self.observation(request, operation_id)

    def readback(self, request, operation_id, external_id):
        self.reads += 1
        if self.failure:
            raise RuntimeError("provider-private-detail-must-not-persist")
        return self.observation(request, operation_id)


class DurableCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "capabilities.sqlite")
        self.now = 1000
        self.gateways = []
        self.adapters = []
        self.request = CapabilityRequest("request-1", "task-1", "subject-1", "device-1",
            "reminder.create", {"title": "fixture-private-title"}, "key-1", 1100, TrustClass.USER)
        self.spec = CapabilitySpec("reminder.create", RiskTier.R2, True, frozenset({"title"}),
                                   reconciliation_supported=True)
        self.gateway, self.adapter = self.make()

    def tearDown(self):
        for adapter in self.adapters:
            adapter.release.set()
        for gateway in self.gateways:
            try:
                gateway.close()
            except sqlite3.Error:
                pass
        self.temp.cleanup()

    def make(self, *, spec=None, provider="reminder-v1", **kwargs):
        adapter = Adapter()
        gateway = DurableCapabilityGateway(self.path, clock=lambda: self.now, **kwargs)
        gateway.register(spec or self.spec, provider_id=provider, adapter=adapter)
        self.gateways.append(gateway)
        self.adapters.append(adapter)
        return gateway, adapter

    def lease(self, request=None, **changes):
        request = request or self.request
        return replace(DecisionLease("lease-" + request.idempotency_key, request.subject,
            request.device_id, request.task_id, request.name,
            canonical_digest(dict(request.arguments)), 1100, False), **changes)

    def execute(self, request=None, gateway=None, **kwargs):
        request = request or self.request
        kwargs.setdefault("lease", self.lease(request))
        return (gateway or self.gateway).execute(request, **kwargs)

    def assert_code(self, code, operation):
        with self.assertRaises(CapabilityError) as result:
            operation()
        self.assertEqual(result.exception.code, code)

    def uncertain(self):
        self.adapter.failure = True
        self.assertEqual(self.execute().status, "indeterminate")
        self.adapter.failure = False

    def test_success_and_replay(self):
        first, second = self.execute(), self.execute()
        self.assertEqual(first.status, "succeeded")
        self.assertTrue(second.replayed)
        self.assertEqual(first.result, second.result)
        self.assertEqual(self.adapter.calls, 1)
        self.assertLess(first.prepared_sequence, first.completed_sequence)

    def test_restart_replays_without_dispatch(self):
        first = self.execute()
        other, adapter = self.make()
        second = self.execute(gateway=other)
        self.assertEqual(first.result, second.result)
        self.assertTrue(second.replayed)
        self.assertEqual(adapter.calls, 0)

    def test_replay_after_expiration_still_does_not_dispatch(self):
        self.execute()
        self.now = 1200
        self.assertTrue(self.execute().replayed)
        self.assertEqual(self.adapter.calls, 1)

    def test_cross_connection_concurrent_duplicate_dispatches_once(self):
        other, adapter = self.make()
        self.adapter.block = True
        result = []
        thread = threading.Thread(target=lambda: result.append(self.execute()))
        thread.start()
        self.assertTrue(self.adapter.entered.wait(1))
        duplicate = self.execute(gateway=other)
        self.assertEqual(duplicate.status, "indeterminate")
        self.assertTrue(duplicate.replayed)
        self.assertEqual(adapter.calls, 0)
        self.adapter.release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0].status, "succeeded")

    def test_conflicting_arguments_rejected(self):
        self.execute()
        self.assert_code("idempotency_conflict", lambda: self.execute(
            replace(self.request, arguments={"title": "different"})))

    def test_conflicting_device_task_request_origin_and_deadline_rejected(self):
        self.execute()
        for changes in ({"device_id": "device-2"}, {"task_id": "task-2"},
                        {"request_id": "request-2"}, {"origin": TrustClass.SYSTEM}, {"deadline": 1101}):
            with self.subTest(changes=changes):
                self.assert_code("idempotency_conflict", lambda: self.execute(replace(self.request, **changes)))

    def test_different_subject_has_separate_idempotency_namespace(self):
        first = self.execute()
        request = replace(self.request, subject="subject-2")
        second = self.execute(request, lease=self.lease(request, lease_id="subject-2-lease"))
        self.assertEqual(second.status, "succeeded")
        self.assertNotEqual(first.result["operation_id"], second.result["operation_id"])

    def test_changed_provider_cannot_replay_or_readback(self):
        self.execute()
        other, _ = self.make(provider="other-provider")
        self.assert_code("idempotency_conflict", lambda: self.execute(gateway=other))
        self.assert_code("idempotency_conflict", lambda: other.reconcile(self.request))

    def test_changed_spec_cannot_replay(self):
        self.execute()
        other, _ = self.make(spec=replace(self.spec, risk=RiskTier.R3))
        self.assert_code("idempotency_conflict", lambda: self.execute(gateway=other))

    def test_no_lease_denied(self):
        receipt = self.execute(lease=None)
        self.assertEqual(receipt.status, "denied")
        self.assertEqual(receipt.result["reason"], "decision_lease_required")
        self.assertEqual(self.adapter.calls, 0)

    def test_lease_consumption_survives_restart(self):
        self.execute()
        other, adapter = self.make()
        request = replace(self.request, idempotency_key="key-2")
        receipt = self.execute(request, gateway=other, lease=self.lease())
        self.assertEqual(receipt.result["reason"], "decision_lease_consumed")
        self.assertEqual(adapter.calls, 0)

    def test_lease_binding_and_types(self):
        for index, changes in enumerate(({"subject": "other"}, {"device_id": "other"},
                {"task_id": "other"}, {"action": "other"}, {"argument_digest": "a" * 64},
                {"single_use": False}, {"expires_at": True}, {"biometric_verified": 1})):
            with self.subTest(changes=changes):
                request = replace(self.request, idempotency_key=f"binding-{index}")
                receipt = self.execute(request, lease=self.lease(request, **changes))
                self.assertEqual(receipt.status, "denied")
        self.assertEqual(self.adapter.calls, 0)

    def test_expired_lease_and_deadline(self):
        self.assertEqual(self.execute(lease=self.lease(expires_at=1000)).result["reason"],
                         "decision_lease_expired")
        request = replace(self.request, idempotency_key="expired", deadline=999)
        self.assertEqual(self.execute(request).result["reason"], "capability_deadline_expired")

    def test_untrusted_origin_requires_confirmation(self):
        self.assertEqual(self.execute(replace(self.request, origin=TrustClass.UNTRUSTED)).status, "denied")
        request = replace(self.request, idempotency_key="confirmed", origin=TrustClass.UNTRUSTED,
                          human_confirmation_digest=canonical_digest(dict(self.request.arguments)))
        self.assertEqual(self.execute(request).status, "succeeded")

    def test_wrong_confirmation_rejected(self):
        request = replace(self.request, human_confirmation_digest="a" * 64)
        self.assertEqual(self.execute(request).result["reason"], "confirmation_digest_mismatch")

    def test_r3_requires_biometric(self):
        other, _ = self.make(spec=replace(self.spec, risk=RiskTier.R3))
        self.assertEqual(self.execute(gateway=other).result["reason"], "biometric_confirmation_required")
        request = replace(self.request, idempotency_key="biometric")
        self.assertEqual(self.execute(request, gateway=other,
            lease=self.lease(request, biometric_verified=True)).status, "succeeded")

    def test_r4_disabled(self):
        other, _ = self.make(spec=replace(self.spec, risk=RiskTier.R4))
        self.assertEqual(self.execute(gateway=other).result["reason"], "r4_disabled")

    def test_missing_and_unknown_fields(self):
        for index, arguments in enumerate(({}, {"title": "x", "extra": "x"})):
            request = replace(self.request, idempotency_key=f"fields-{index}", arguments=arguments)
            self.assertEqual(self.execute(request).status, "denied")

    def test_exception_is_uncertain_and_never_retried(self):
        self.adapter.failure = True
        first, second = self.execute(), self.execute()
        self.assertEqual(first.status, "indeterminate")
        self.assertFalse(first.result["retry_safe"])
        self.assertTrue(second.replayed)
        self.assertEqual(self.adapter.calls, 1)
        self.assertNotIn("provider-private", json.dumps(first.result))

    def test_restart_retains_recovery_inventory(self):
        self.uncertain()
        other, adapter = self.make()
        self.assertEqual(len(other.pending("subject-1")), 1)
        self.assertEqual(other.pending("other-subject"), [])
        receipt = other.reconcile(self.request)
        self.assertEqual(receipt.status, "succeeded")
        self.assertTrue(receipt.reconciled)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(adapter.reads, 1)
        self.assertEqual(other.pending("subject-1"), [])

    def test_crash_after_reservation_cannot_dispatch_again(self):
        with patch.object(self.gateway._calls, "run", side_effect=SystemExit("simulated crash")):
            with self.assertRaises(SystemExit):
                self.execute()
        other, adapter = self.make()
        self.assertEqual(self.execute(gateway=other).status, "indeterminate")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(other.pending("subject-1")[0]["state"], "dispatching")

    def test_pre_effect_commit_failure_does_not_call_provider(self):
        with self.gateway.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON hg_capability_events "
                       "BEGIN SELECT RAISE(ABORT,'test audit unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute()
        self.assertEqual(self.adapter.calls, 0)
        with self.gateway.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM hg_capability_operations").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM hg_capability_leases").fetchone()[0], 0)

    def test_terminal_commit_failure_leaves_nonreplayable_reservation(self):
        old = self.adapter.execute
        def fail_terminal(request, operation_id):
            with self.gateway.store.transaction() as db:
                db.execute("CREATE TRIGGER reject_terminal BEFORE INSERT ON hg_capability_events "
                           "BEGIN SELECT RAISE(ABORT,'test terminal audit unavailable'); END")
            return old(request, operation_id)
        self.adapter.execute = fail_terminal
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute()
        other, adapter = self.make()
        self.assertEqual(self.execute(gateway=other).status, "indeterminate")
        self.assertEqual(adapter.calls, 0)

    def test_timeout_does_not_accept_late_success(self):
        other, adapter = self.make(maximum_wait_seconds=0.01)
        adapter.block = True
        receipt = self.execute(gateway=other)
        self.assertEqual(receipt.status, "indeterminate")
        adapter.release.set()
        self.assertEqual(self.execute(gateway=other).status, "indeterminate")
        self.assertEqual(other.reconcile(self.request).status, "succeeded")

    def test_not_started_is_failed_but_never_auto_retried(self):
        with patch.object(self.gateway._calls, "run", return_value=CallOutcome("not_started")):
            self.assertEqual(self.execute().status, "failed")
        self.assertEqual(self.execute().status, "failed")
        self.assertEqual(self.adapter.calls, 0)

    def test_nonterminal_absence_is_not_proof_of_no_effect(self):
        self.uncertain()
        self.adapter.result = "not_applied"
        self.adapter.terminal = False
        receipt = self.gateway.reconcile(self.request)
        self.assertEqual(receipt.status, "indeterminate")
        self.assertTrue(receipt.result["effect_may_have_occurred"])

    def test_terminal_not_applied_is_failed_without_retry(self):
        self.uncertain()
        self.adapter.result = "not_applied"
        receipt = self.gateway.reconcile(self.request)
        self.assertEqual(receipt.status, "failed")
        self.assertFalse(receipt.result["effect_may_have_occurred"])
        self.assertFalse(receipt.result["retry_safe"])
        self.execute()
        self.assertEqual(self.adapter.calls, 1)

    def test_bad_observation_binding_is_uncertain(self):
        for index, changes in enumerate(({"operation_id": "wrong"}, {"provider_id": "wrong"},
                {"argument_digest": "a" * 64}, {"terminal": 1}, {"disposition": []},
                {"external_id": "invalid\nprivate"}, {"external_id": []})):
            with self.subTest(changes=changes):
                self.adapter.transform = lambda value, changes=changes: replace(value, **changes)
                request = replace(self.request, idempotency_key=f"observation-{index}")
                self.assertEqual(self.execute(request).status, "indeterminate")

    def test_arbitrary_provider_response_is_not_stored(self):
        self.adapter.transform = lambda value: {"private": "private-response-content"}
        self.assertEqual(self.execute().status, "indeterminate")
        for path in Path(self.temp.name).glob("capabilities.sqlite*"):
            self.assertNotIn(b"private-response-content", path.read_bytes())

    def test_plaintext_arguments_and_exception_text_absent_from_database(self):
        self.uncertain()
        for path in Path(self.temp.name).glob("capabilities.sqlite*"):
            contents = path.read_bytes()
            self.assertNotIn(b"fixture-private-title", contents)
            self.assertNotIn(b"provider-private-detail", contents)
            self.assertNotIn(b"subject-1", contents)

    def test_readback_failure_preserves_uncertainty(self):
        self.uncertain()
        self.adapter.failure = True
        self.assertEqual(self.gateway.reconcile(self.request).status, "indeterminate")
        self.assertEqual(self.adapter.calls, 1)

    def test_readback_limit_survives_restart(self):
        other, adapter = self.make(maximum_readbacks=1)
        adapter.failure = True
        self.execute(gateway=other)
        other.reconcile(self.request)
        restarted, _ = self.make(maximum_readbacks=1)
        self.assert_code("capability_readback_capacity_exhausted", lambda: restarted.reconcile(self.request))
        self.assertEqual(restarted.pending("subject-1")[0]["readbacks"], 1)

    def test_readback_crash_consumes_budget(self):
        self.uncertain()
        with patch.object(self.gateway._calls, "run", side_effect=SystemExit("simulated crash")):
            with self.assertRaises(SystemExit):
                self.gateway.reconcile(self.request)
        self.assertEqual(self.gateway.pending("subject-1")[0]["readbacks"], 1)

    def test_terminal_state_does_not_issue_readbacks(self):
        self.execute()
        receipt = self.gateway.reconcile(self.request)
        self.assertTrue(receipt.replayed)
        self.assertEqual(self.adapter.reads, 0)

    def test_revocation_is_persistent_and_no_resurrection_api(self):
        self.gateway.revoke_subject("subject-1")
        other, adapter = self.make()
        receipt = self.execute(gateway=other)
        self.assertEqual(receipt.result["reason"], "subject_revoked")
        self.assertEqual(adapter.calls, 0)
        other.revoke_subject("subject-1")

    def test_revocation_does_not_falsify_existing_effect(self):
        first = self.execute()
        self.gateway.revoke_subject("subject-1")
        self.assertEqual(self.execute().result, first.result)
        self.assertEqual(self.execute().status, "succeeded")

    def test_revoke_after_uncertain_dispatch_allows_only_readback(self):
        self.uncertain()
        self.gateway.revoke_subject("subject-1")
        self.assertEqual(self.execute().status, "indeterminate")
        self.assertEqual(self.gateway.reconcile(self.request).status, "succeeded")
        self.assertEqual(self.adapter.calls, 1)

    def test_revoke_between_reservation_and_dispatch_prevents_effect(self):
        original = self.gateway._calls.run
        def revoke(operation, **kwargs):
            self.gateway.revoke_subject("subject-1")
            return original(operation, **kwargs)
        with patch.object(self.gateway._calls, "run", side_effect=revoke):
            receipt = self.execute()
        self.assertEqual(receipt.status, "failed")
        self.assertEqual(self.adapter.calls, 0)

    def test_expire_between_reservation_and_dispatch_prevents_effect(self):
        original = self.gateway._calls.run
        def expire(operation, **kwargs):
            self.now = 1200
            return original(operation, **kwargs)
        with patch.object(self.gateway._calls, "run", side_effect=expire):
            self.assertEqual(self.execute().status, "failed")
        self.assertEqual(self.adapter.calls, 0)

    def test_capacity_never_evicts_duplicate_protection(self):
        other, adapter = self.make(maximum_operations=1)
        first = self.execute(gateway=other)
        self.assert_code("capability_receipt_capacity_exhausted", lambda: self.execute(
            replace(self.request, idempotency_key="key-2"), gateway=other))
        self.assertEqual(self.execute(gateway=other).result, first.result)
        self.assertEqual(adapter.calls, 1)

    def test_pending_inventory_is_bounded_and_paginated(self):
        self.adapter.failure = True
        for index in range(3):
            self.execute(replace(self.request, idempotency_key=f"pending-{index}"))
        first = self.gateway.pending("subject-1", limit=2)
        second = self.gateway.pending("subject-1", limit=2, after=first[-1]["operation_id"])
        self.assertEqual(len(first) + len(second), 3)
        self.assertEqual(len({item["operation_id"] for item in first + second}), 3)

    def test_invalid_inventory_queries(self):
        for kwargs in ({"limit": 0}, {"limit": True}, {"limit": 101}, {"after": "../"}):
            self.assert_code("capability_inventory_query_invalid", lambda: self.gateway.pending("subject-1", **kwargs))

    def test_unknown_operation_cannot_be_reconciled(self):
        self.assert_code("capability_operation_unknown", lambda: self.gateway.reconcile(self.request))

    def test_invalid_request_shapes(self):
        for changes in ({"deadline": True}, {"request_id": " bad"},
                        {"subject": "a\nb"}, {"origin": "user"},
                        {"human_confirmation_digest": 1}, {"human_confirmation_digest": "wrong"}):
            with self.subTest(changes=changes):
                self.assert_code("capability_request_invalid", lambda: self.execute(replace(self.request, **changes)))

    def test_invalid_json_and_oversized_arguments(self):
        cycle = {}
        cycle["self"] = cycle
        for arguments in ({"title": float("nan")}, {"title": "x" * 65537},
                          {"title": {1: "coerced"}}, cycle):
            self.assert_code("capability_arguments_invalid", lambda: self.gateway.execute(
                replace(self.request, arguments=arguments), lease=self.lease()))

    def test_invalid_clock_rejected_before_effect(self):
        self.now = True
        self.assert_code("capability_clock_invalid", self.execute)
        self.assertEqual(self.adapter.calls, 0)

    def test_schema_version_mismatch_rejected(self):
        with self.gateway.store.transaction() as db:
            db.execute("UPDATE hepta_component_schema SET version=99 WHERE component='durable_capabilities'")
        with self.assertRaisesRegex(ValueError, "schema_migration_required"):
            self.make()

    def test_unmarked_existing_schema_rejected(self):
        with self.gateway.store.transaction() as db:
            db.execute("DELETE FROM hepta_component_schema WHERE component='durable_capabilities'")
        with self.assertRaisesRegex(ValueError, "unmarked_schema_rejected"):
            self.make()

    def test_invalid_configuration(self):
        for kwargs in ({"maximum_wait_seconds": 0}, {"maximum_wait_seconds": float("inf")},
                {"maximum_operations": True}, {"maximum_readbacks": 33}, {"maximum_active_calls": 0}):
            with self.assertRaises(ValueError):
                DurableCapabilityGateway(self.path, clock=lambda: self.now, **kwargs)

    def test_registration_rejects_read_only_and_duplicate(self):
        with self.assertRaises(CapabilityError):
            self.gateway.register(self.spec, provider_id="reminder-v1", adapter=self.adapter)
        with self.assertRaises(CapabilityError):
            self.gateway.register(replace(self.spec, name="read", mutating=False),
                                  provider_id="reminder-v1", adapter=self.adapter)


    def test_actual_process_exit_after_reservation(self):
        code = """
import os, sys
from services.control_plane.test_durable_capabilities import Adapter
from services.control_plane.capabilities import CapabilitySpec, RiskTier, CapabilityRequest, TrustClass, DecisionLease, canonical_digest
from services.control_plane.durable_capabilities import DurableCapabilityGateway
r = CapabilityRequest('request-1','task-1','subject-1','device-1','reminder.create', {'title':'fixture-private-title'},'key-1',1100,TrustClass.USER)
g = DurableCapabilityGateway(sys.argv[1], clock=lambda:1000)
g.register(CapabilitySpec('reminder.create',RiskTier.R2,True,frozenset({'title'}),reconciliation_supported=True),provider_id='reminder-v1',adapter=Adapter())
g._calls.run = lambda *args, **kwargs: os._exit(17)
g.execute(r, lease=DecisionLease('lease-key-1',r.subject,r.device_id,r.task_id,r.name,canonical_digest(dict(r.arguments)),1100,False))
"""
        result = subprocess.run([sys.executable, "-c", code, self.path],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
        self.assertEqual(self.execute().status, "indeterminate")
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.gateway.pending("subject-1")[0]["state"], "dispatching")

    def test_actual_process_exit_after_effect_before_receipt(self):
        marker = str(Path(self.temp.name) / "effect-marker")
        code = """
import os, sys
from pathlib import Path
from services.control_plane.test_durable_capabilities import Adapter
from services.control_plane.capabilities import CapabilitySpec, RiskTier, CapabilityRequest, TrustClass, DecisionLease, canonical_digest
from services.control_plane.durable_capabilities import DurableCapabilityGateway
class CrashAdapter(Adapter):
    def execute(self, request, operation_id):
        with open(sys.argv[2], 'w') as stream:
            stream.write(operation_id)
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(19)
r = CapabilityRequest('request-1','task-1','subject-1','device-1','reminder.create', {'title':'fixture-private-title'},'key-1',1100,TrustClass.USER)
g = DurableCapabilityGateway(sys.argv[1], clock=lambda:1000)
g.register(CapabilitySpec('reminder.create',RiskTier.R2,True,frozenset({'title'}),reconciliation_supported=True),provider_id='reminder-v1',adapter=CrashAdapter())
g.execute(r, lease=DecisionLease('lease-key-1',r.subject,r.device_id,r.task_id,r.name,canonical_digest(dict(r.arguments)),1100,False))
"""
        result = subprocess.run([sys.executable, "-c", code, self.path, marker],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 19, result.stderr.decode())
        receipt = self.execute()
        self.assertEqual(receipt.status, "indeterminate")
        self.assertEqual(receipt.result["operation_id"], Path(marker).read_text())
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(self.gateway.reconcile(self.request).status, "succeeded")

    def test_terminal_readback_before_dispatch_blocks_dispatch(self):
        original = self.gateway._calls.run
        self.adapter.result = "not_applied"
        first = True
        def readback_first(operation, **kwargs):
            nonlocal first
            if first:
                first = False
                self.assertEqual(self.gateway.reconcile(self.request).status, "failed")
            return original(operation, **kwargs)
        with patch.object(self.gateway._calls, "run", side_effect=readback_first):
            self.assertEqual(self.execute().status, "failed")
        self.assertEqual(self.adapter.calls, 0)

    def test_conflicting_late_terminal_observation_is_quarantined(self):
        self.adapter.block = True
        receipts = []
        thread = threading.Thread(target=lambda: receipts.append(self.execute()))
        thread.start()
        self.assertTrue(self.adapter.entered.wait(1))
        self.adapter.result = "not_applied"
        self.assertEqual(self.gateway.reconcile(self.request).status, "failed")
        self.adapter.result = "applied"
        self.adapter.release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(receipts[0].status, "indeterminate")
        self.assertEqual(receipts[0].result["reason"], "provider_terminal_conflict")
        self.assert_code("capability_receipt_conflict", lambda: self.gateway.reconcile(self.request))
        self.assertEqual(self.adapter.calls, 1)

    def test_already_admitted_readback_cannot_clear_terminal_conflict(self):
        self.uncertain()
        entered = [threading.Event() for _ in range(3)]
        release = [threading.Event() for _ in range(3)]
        lock = threading.Lock()
        count = 0
        def readback(request, operation_id, external_id):
            nonlocal count
            with lock:
                index = count
                count += 1
            entered[index].set()
            if not release[index].wait(2):
                raise RuntimeError("fixture readback release timed out")
            return ProviderObservation(operation_id, "reminder-v1",
                canonical_digest(dict(request.arguments)),
                "not_applied" if index == 1 else "applied", True)
        receipts = [None] * 3
        threads = []
        with patch.object(self.adapter, "readback", side_effect=readback):
            try:
                for index in range(3):
                    thread = threading.Thread(target=lambda i=index: receipts.__setitem__(
                        i, self.gateway.reconcile(self.request)))
                    threads.append(thread)
                    thread.start()
                    self.assertTrue(entered[index].wait(1))
                for index, expected in enumerate(["succeeded", "indeterminate", "indeterminate"]):
                    release[index].set()
                    threads[index].join(2)
                    self.assertFalse(threads[index].is_alive())
                    self.assertEqual(receipts[index].status, expected)
                self.assertEqual(receipts[2].result["reason"], "provider_terminal_conflict")
                self.assert_code("capability_receipt_conflict", lambda: self.gateway.reconcile(self.request))
            finally:
                for event in release:
                    event.set()
                for thread in threads:
                    thread.join(2)

    def test_readback_external_identity_cannot_drift(self):
        self.adapter.terminal = False
        self.execute()
        self.adapter.terminal = True
        self.adapter.transform = lambda value: replace(value, external_id="other-record")
        receipt = self.gateway.reconcile(self.request)
        self.assertEqual(receipt.status, "indeterminate")
        self.assertEqual(receipt.result["external_id"], "record-1")

    def test_worker_saturation_does_not_spawn_second_effect(self):
        other, adapter = self.make(maximum_wait_seconds=0.01, maximum_active_calls=1)
        adapter.block = True
        self.assertEqual(self.execute(gateway=other).status, "indeterminate")
        request = replace(self.request, idempotency_key="second-key")
        self.assertEqual(self.execute(request, gateway=other).status, "failed")
        self.assertEqual(adapter.calls, 1)
        adapter.release.set()

    def test_caller_mutation_cannot_change_admitted_arguments(self):
        original = self.gateway._calls.run
        def alter(operation, **kwargs):
            self.request.arguments["title"] = "different-after-admission"
            return original(operation, **kwargs)
        with patch.object(self.gateway._calls, "run", side_effect=alter):
            self.assertEqual(self.execute().status, "succeeded")
        self.assert_code("idempotency_conflict", self.execute)

    def test_denial_does_not_consume_valid_lease(self):
        request = replace(self.request, origin=TrustClass.UNTRUSTED)
        self.assertEqual(self.execute(request).status, "denied")
        request = replace(self.request, idempotency_key="allowed-key")
        self.assertEqual(self.execute(request, lease=self.lease()).status, "succeeded")

    def test_revocation_inventory_capacity_is_bounded(self):
        other, _ = self.make(maximum_operations=1)
        other.revoke_subject("subject-1")
        other.revoke_subject("subject-1")
        self.assert_code("capability_revocation_capacity_exhausted", lambda: other.revoke_subject("subject-2"))

    def test_expired_request_can_readback_without_new_mutation_authority(self):
        self.uncertain()
        self.now = 1200
        self.assertEqual(self.gateway.reconcile(self.request).status, "succeeded")
        self.assertEqual(self.adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
