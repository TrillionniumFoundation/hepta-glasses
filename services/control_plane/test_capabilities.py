from __future__ import annotations

import unittest

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
        self.gateway = CapabilityGateway(
            journal=self.journal,
            clock=lambda: self.now,
        )
        self.gateway.register(
            CapabilitySpec(
                name="reminder.create",
                risk=RiskTier.R2,
                mutating=True,
                required_fields=frozenset({"title"}),
                optional_fields=frozenset({"due_at"}),
                reconciliation_supported=True,
            ),
            self.adapter,
        )

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
        events = [entry["event"] for entry in self.journal.entries]
        self.assertLess(events.index("capability.prepared"), events.index("capability.completed"))
        self.journal.verify()

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
