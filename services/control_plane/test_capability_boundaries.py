from __future__ import annotations
import threading
import time
import unittest
from dataclasses import replace
from .capabilities import (AuditJournal, CapabilityError, CapabilityGateway,
    CapabilityRequest, CapabilitySpec, DecisionLease, IndeterminateEffect,
    RiskTier, TrustClass, canonical_digest)


class CapabilityBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000
        self.release = threading.Event()
        self.entered = threading.Event()
        self.calls = 0
        self.gateway = CapabilityGateway(journal=AuditJournal(), clock=lambda: self.now,
            maximum_wait_seconds=0.08, maximum_active_calls=1)
        self.addCleanup(self.release.set)

    def request(self, key="one"):
        return CapabilityRequest(key, "task", "user", "device", "reminder.create",
            {"title": "example"}, key, self.now + 60, TrustClass.USER)

    def lease(self, request):
        return DecisionLease("lease-" + request.idempotency_key, request.subject,
            request.device_id, request.task_id, request.name,
            canonical_digest(dict(request.arguments)), self.now + 60, False)

    def register(self, function, *, mutating=True, reconcile=None):
        outer = self
        class Adapter:
            def execute(self, request):
                outer.calls += 1
                outer.entered.set()
                return function(request)
            def reconcile(self, request, external_id):
                return reconcile(request, external_id)
        self.gateway.register(CapabilitySpec("reminder.create", RiskTier.R2, mutating,
            frozenset({"title"}), reconciliation_supported=reconcile is not None), Adapter())

    def test_post_dispatch_exception_is_indeterminate_and_not_reexecuted(self):
        def operation(request):
            raise TimeoutError("provider may already have committed")
        self.register(operation)
        request = self.request()
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "indeterminate")
        self.assertFalse(receipt.result["retry_safe"])
        self.assertTrue(self.gateway.execute(request, lease=self.lease(request)).replayed)
        self.assertEqual(self.calls, 1)

    def test_timeout_late_success_cannot_overwrite_receipt(self):
        completed = threading.Event()
        def operation(request):
            self.release.wait(2)
            completed.set()
            return {"authoritative": True}
        self.register(operation)
        request = self.request()
        start = time.monotonic()
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(receipt.status, "indeterminate")
        self.release.set()
        self.assertTrue(completed.wait(1))
        self.assertEqual(self.gateway.execute(request, lease=self.lease(request)).status, "indeterminate")
        self.assertEqual(self.calls, 1)

    def test_timed_out_worker_keeps_capacity_permit(self):
        self.register(lambda request: (self.release.wait(2), {})[1])
        first, second = self.request(), self.request("two")
        self.assertEqual(self.gateway.execute(first, lease=self.lease(first)).status, "indeterminate")
        denied = self.gateway.execute(second, lease=self.lease(second))
        self.assertEqual(denied.result["error_type"], "WorkerCapacityExceeded")
        self.assertTrue(denied.result["retry_safe"])
        self.assertEqual(self.calls, 1)

    def test_duplicate_waiter_is_bounded_without_replacing_owner(self):
        self.gateway.maximum_wait_seconds = 0.3
        self.register(lambda request: (self.release.wait(2), {})[1])
        request = self.request()
        result = []
        worker = threading.Thread(target=lambda: result.append(self.gateway.execute(request, lease=self.lease(request))))
        worker.start()
        self.assertTrue(self.entered.wait(1))
        self.gateway.maximum_wait_seconds = 0.01
        with self.assertRaisesRegex(CapabilityError, "in_flight_deadline"):
            self.gateway.execute(request, lease=self.lease(request))
        self.release.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0].status, "succeeded")
        self.assertEqual(self.calls, 1)

    def test_reconciliation_error_retains_indeterminate_receipt(self):
        def operation(request):
            raise IndeterminateEffect("external-1")
        def reconcile(request, external_id):
            raise ConnectionError("readback unavailable")
        self.register(operation, reconcile=reconcile)
        request = self.request()
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "indeterminate")
        self.assertTrue(receipt.reconciled)
        self.assertEqual(receipt.result["external_id"], "external-1")
        self.assertTrue(self.gateway.execute(request, lease=self.lease(request)).replayed)
        self.gateway.journal.verify()

    def test_terminal_audit_failure_quarantines_effect_and_disables_new_work(self):
        class FailingJournal(AuditJournal):
            def append(self, event, payload):
                if event == "capability.completed":
                    raise OSError("disk unavailable")
                return super().append(event, payload)
        self.gateway.journal = FailingJournal()
        self.register(lambda request: {"authoritative": True})
        request = self.request()
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "indeterminate")
        self.assertIsNone(receipt.completed_sequence)
        self.assertTrue(self.gateway.execute(request, lease=self.lease(request)).replayed)
        second = self.request("two")
        with self.assertRaisesRegex(CapabilityError, "audit_unavailable"):
            self.gateway.execute(second, lease=self.lease(second))
        self.assertEqual(self.calls, 1)

    def test_untrusted_enum_string_is_not_an_authority(self):
        self.register(lambda request: {})
        request = replace(self.request(), origin="untrusted")
        with self.assertRaisesRegex(CapabilityError, "request_invalid"):
            self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(self.calls, 0)

    def test_non_single_use_mutation_lease_is_rejected(self):
        self.register(lambda request: {})
        request = self.request()
        receipt = self.gateway.execute(request, lease=replace(self.lease(request), single_use=False))
        self.assertEqual(receipt.status, "denied")
        self.assertEqual(self.calls, 0)

    def test_arguments_are_snapshotted_before_provider_dispatch(self):
        observed = []
        def operation(request):
            self.release.wait(1)
            observed.append(request.arguments["title"])
            return {}
        self.gateway.maximum_wait_seconds = 1
        self.register(operation)
        request = self.request()
        lease = self.lease(request)
        worker = threading.Thread(target=lambda: self.gateway.execute(request, lease=lease))
        worker.start()
        self.assertTrue(self.entered.wait(1))
        request.arguments["title"] = "changed after admission"
        self.release.set()
        worker.join(1)
        self.assertEqual(observed, ["example"])

    def test_receipt_capacity_rejects_without_evicting_replay(self):
        self.gateway.maximum_receipts = 1
        self.register(lambda request: {})
        first, second = self.request(), self.request("two")
        self.gateway.execute(first, lease=self.lease(first))
        with self.assertRaisesRegex(CapabilityError, "receipt_capacity"):
            self.gateway.execute(second, lease=self.lease(second))
        self.assertTrue(self.gateway.execute(first, lease=self.lease(first)).replayed)
        self.assertEqual(self.calls, 1)

    def test_successful_authoritative_reconciliation_and_lease_reuse(self):
        def operation(request):
            raise IndeterminateEffect("external-1")
        self.register(operation, reconcile=lambda request, external_id: {"authoritative": True})
        first, second = self.request(), self.request("two")
        lease = self.lease(first)
        self.assertEqual(self.gateway.execute(first, lease=lease).status, "succeeded")
        self.assertEqual(self.gateway.execute(second, lease=lease).result["reason"], "decision_lease_consumed")

    def test_concurrent_duplicates_execute_once(self):
        self.register(lambda request: {})
        request = self.request()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: self.gateway.execute(request, lease=self.lease(request)), range(8)))
        self.assertEqual([receipt.status for receipt in receipts], ["succeeded"] * 8)
        self.assertEqual(self.calls, 1)


if __name__ == "__main__":
    unittest.main()
