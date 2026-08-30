from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Mapping, Any

from services.control_plane.capabilities import (
    AuditJournal,
    CapabilityError,
    CapabilityGateway,
    CapabilityRequest,
    CapabilitySpec,
    DecisionLease,
    InMemoryReminderAdapter,
    RiskTier,
    TrustClass,
    canonical_digest,
)


class CapabilityGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000
        self.journal = AuditJournal()
        self.adapter = InMemoryReminderAdapter()
        self.gateway = self.gateway_for(self.journal, self.adapter)

    def gateway_for(
        self,
        journal: AuditJournal,
        adapter: object,
    ) -> CapabilityGateway:
        gateway = CapabilityGateway(
            journal=journal,
            clock=lambda: self.now,
        )
        gateway.register(
            CapabilitySpec(
                name="reminder.create",
                risk=RiskTier.R2,
                mutating=True,
                required_fields=frozenset({"title"}),
                optional_fields=frozenset({"due_at"}),
                reconciliation_supported=True,
            ),
            adapter,  # type: ignore[arg-type]
        )
        return gateway

    def request(self, **updates: object) -> CapabilityRequest:
        values: dict[str, object] = {
            "request_id": "request-1",
            "task_id": "task-1",
            "subject": "user-1",
            "device_id": "g1-001",
            "name": "reminder.create",
            "arguments": {"title": "Stand up"},
            "idempotency_key": "idem-1",
            "deadline": self.now + 60,
            "origin": TrustClass.USER,
            "human_confirmation_digest": canonical_digest({"title": "Stand up"}),
        }
        values.update(updates)
        return CapabilityRequest(**values)  # type: ignore[arg-type]

    def lease(self, request: CapabilityRequest, **updates: object) -> DecisionLease:
        values: dict[str, object] = {
            "lease_id": "lease-1",
            "subject": request.subject,
            "device_id": request.device_id,
            "task_id": request.task_id,
            "action": request.name,
            "argument_digest": canonical_digest(dict(request.arguments)),
            "expires_at": self.now + 60,
            "biometric_verified": False,
        }
        values.update(updates)
        return DecisionLease(**values)  # type: ignore[arg-type]

    def test_journal_before_effect_and_exact_replay(self) -> None:
        request = self.request()
        receipt = self.gateway.execute(request, lease=self.lease(request))
        replay = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "succeeded")
        self.assertTrue(replay.replayed)
        self.assertEqual(self.adapter.execute_count, 1)
        events = [entry["event"] for entry in self.journal.entries]
        self.assertLess(
            events.index("capability.prepared"),
            events.index("capability.completed"),
        )
        self.journal.verify()

    def test_receipt_and_lease_consumption_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.sqlite3"
            first_journal = AuditJournal(path)
            first_adapter = InMemoryReminderAdapter()
            first_gateway = self.gateway_for(first_journal, first_adapter)
            request = self.request()
            receipt = first_gateway.execute(request, lease=self.lease(request))
            self.assertEqual(receipt.status, "succeeded")
            first_journal.close()

            second_journal = AuditJournal(path)
            second_adapter = InMemoryReminderAdapter()
            second_gateway = self.gateway_for(second_journal, second_adapter)
            replay = second_gateway.execute(request, lease=self.lease(request))
            self.assertTrue(replay.replayed)
            self.assertEqual(replay.result, receipt.result)
            self.assertEqual(second_adapter.execute_count, 0)

            new_request = self.request(
                request_id="request-2",
                idempotency_key="idem-2",
            )
            denied = second_gateway.execute(
                new_request,
                lease=self.lease(new_request),
            )
            self.assertEqual(denied.status, "denied")
            self.assertEqual(denied.result["reason"], "decision_lease_consumed")
            second_journal.verify()
            second_journal.close()

    def test_concurrent_retry_never_dispatches_adapter_twice(self) -> None:
        class BlockingAdapter:
            def __init__(self) -> None:
                self.entered = threading.Event()
                self.release = threading.Event()
                self.execute_count = 0
                self.lock = threading.Lock()

            def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
                with self.lock:
                    self.execute_count += 1
                self.entered.set()
                self.release.wait(timeout=5)
                return {
                    "authoritative": True,
                    "external_id": f"reminder:{request.idempotency_key}",
                }

            def reconcile(
                self,
                request: CapabilityRequest,
                external_id: str,
            ) -> Mapping[str, Any]:
                return {"authoritative": True, "external_id": external_id}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.sqlite3"
            adapter = BlockingAdapter()
            journal_one = AuditJournal(path)
            journal_two = AuditJournal(path)
            gateway_one = self.gateway_for(journal_one, adapter)
            gateway_two = self.gateway_for(journal_two, adapter)
            request = self.request()
            receipts: list[object] = []

            thread = threading.Thread(
                target=lambda: receipts.append(
                    gateway_one.execute(request, lease=self.lease(request))
                )
            )
            thread.start()
            self.assertTrue(adapter.entered.wait(timeout=5))
            retry = gateway_two.execute(request, lease=self.lease(request))
            self.assertEqual(retry.status, "indeterminate")
            self.assertEqual(
                retry.result["reason"],
                "prepared_effect_outcome_unknown",
            )
            adapter.release.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(adapter.execute_count, 1)
            self.assertEqual(receipts[0].status, "succeeded")  # type: ignore[attr-defined]
            journal_one.close()
            journal_two.close()

    def test_process_loss_after_prepare_fails_closed_on_retry(self) -> None:
        class CrashAdapter:
            def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
                raise SystemExit("simulated process loss")

            def reconcile(
                self,
                request: CapabilityRequest,
                external_id: str,
            ) -> Mapping[str, Any]:
                return {"authoritative": False, "external_id": external_id}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capabilities.sqlite3"
            first_journal = AuditJournal(path)
            request = self.request()
            with self.assertRaises(SystemExit):
                self.gateway_for(first_journal, CrashAdapter()).execute(
                    request,
                    lease=self.lease(request),
                )
            first_journal.close()

            second_journal = AuditJournal(path)
            second_adapter = InMemoryReminderAdapter()
            retry = self.gateway_for(second_journal, second_adapter).execute(
                request,
                lease=self.lease(request),
            )
            self.assertEqual(retry.status, "indeterminate")
            self.assertTrue(retry.replayed)
            self.assertEqual(second_adapter.execute_count, 0)
            second_journal.close()

    def test_timeout_like_indeterminate_effect_is_reconciled(self) -> None:
        request = self.request()
        self.adapter.indeterminate_once = True
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "succeeded")
        self.assertTrue(receipt.reconciled)
        self.assertTrue(receipt.result["authoritative"])

    def test_untrusted_content_cannot_authorize_mutation(self) -> None:
        request = self.request(
            origin=TrustClass.UNTRUSTED,
            human_confirmation_digest=None,
        )
        receipt = self.gateway.execute(request, lease=self.lease(request))
        self.assertEqual(receipt.status, "denied")
        self.assertEqual(
            receipt.result["reason"],
            "untrusted_content_cannot_authorize_mutation",
        )

    def test_lease_and_confirmation_are_exact_argument_bound(self) -> None:
        request = self.request(arguments={"title": "Different"})
        mismatched = self.lease(
            request,
            argument_digest=canonical_digest({"title": "Stand up"}),
        )
        receipt = self.gateway.execute(request, lease=mismatched)
        self.assertEqual(receipt.result["reason"], "decision_lease_binding_mismatch")

    def test_idempotency_key_cannot_be_reused_for_different_request(self) -> None:
        first = self.request()
        self.gateway.execute(first, lease=self.lease(first))
        conflicting = self.request(
            request_id="request-2",
            arguments={"title": "Drink water"},
        )
        with self.assertRaises(CapabilityError) as raised:
            self.gateway.execute(conflicting, lease=self.lease(conflicting))
        self.assertEqual(raised.exception.code, "idempotency_conflict")


if __name__ == "__main__":
    unittest.main()
