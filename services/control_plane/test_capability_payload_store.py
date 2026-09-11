from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from services.control_plane.capability_payload_store import (
    CapabilityPayloadError,
    EncryptedCapabilityPayloadStore,
)


class Cipher:
    def __init__(self) -> None:
        self.keys = {
            "subject-a": {"key-a": b"a" * 32},
            "subject-b": {"key-b": b"b" * 32},
        }
        self.current = {"subject-a": "key-a", "subject-b": "key-b"}

    def current_key_id(self, *, subject: str) -> str:
        return self.current[subject]

    def encrypt(self, *, subject: str, key_id: str,
                plaintext: bytes, aad: bytes) -> bytes:
        key = self.keys[subject][key_id]
        stream = hashlib.sha256(key + aad).digest()
        body = bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(plaintext))
        return hmac.new(key, aad + body, hashlib.sha256).digest() + body

    def decrypt(self, *, subject: str, key_id: str,
                ciphertext: bytes, aad: bytes) -> bytes:
        key = self.keys[subject][key_id]
        tag, body = ciphertext[:32], ciphertext[32:]
        if not hmac.compare_digest(
                tag, hmac.new(key, aad + body, hashlib.sha256).digest()):
            raise ValueError("integrity")
        stream = hashlib.sha256(key + aad).digest()
        return bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(body))


class CapabilityPayloadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "payload.sqlite")
        self.now = 100
        self.store = EncryptedCapabilityPayloadStore(
            self.path,
            cipher=Cipher(),
            clock=lambda: self.now,
            maximum_readbacks=2,
        )
        self.addCleanup(self.store.close)
        self.lease = "1" * 64
        self.payload = {
            "title": "private meeting",
            "start_at": 500,
            "end_at": 800,
        }

    def prepare(self, *, operation_id: str = "operation-a",
                idempotency_key: str = "idem-a", subject: str = "subject-a"):
        return self.store.prepare(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            subject=subject,
            provider_id="google-calendar-a",
            payload=self.payload,
            lease_digest=self.lease,
            deadline=400,
        )

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(CapabilityPayloadError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_prepare_is_exactly_idempotent_and_conflicts_fail(self) -> None:
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first, second)
        self.assert_code(
            "capability_payload_idempotency_conflict",
            lambda: self.store.prepare(
                operation_id="operation-other",
                idempotency_key="idem-a",
                subject="subject-a",
                provider_id="google-calendar-a",
                payload=self.payload,
                lease_digest=self.lease,
                deadline=400,
            ),
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM capability_payload_operations"
            ).fetchone()[0],
            1,
        )

    def test_dispatch_claim_is_single_use_and_revalidates_authority(self) -> None:
        self.prepare()
        checks = []
        claim = self.store.claim_dispatch(
            operation_id="operation-a",
            subject="subject-a",
            lease_digest=self.lease,
            authorize=lambda: checks.append("checked"),
        )
        self.assertEqual(dict(claim.payload), self.payload)
        self.assertEqual(claim.generation, 2)
        self.assertEqual(checks, ["checked", "checked"])
        self.assert_code(
            "capability_payload_not_dispatchable",
            lambda: self.store.claim_dispatch(
                operation_id="operation-a",
                subject="subject-a",
                lease_digest=self.lease,
                authorize=lambda: None,
            ),
        )

    def test_post_dispatch_loss_requires_readback_not_retry(self) -> None:
        self.prepare()
        claim = self.store.claim_dispatch(
            operation_id="operation-a",
            subject="subject-a",
            lease_digest=self.lease,
            authorize=lambda: None,
        )
        self.store.mark_indeterminate(
            operation_id=claim.operation_id,
            generation=claim.generation,
        )
        self.assertEqual(
            self.store.recovery_inventory(subject="subject-a")[0].state,
            "indeterminate",
        )
        recovered = self.store.claim_readback(
            operation_id="operation-a",
            subject="subject-a",
            authorize=lambda: None,
        )
        self.assertEqual(dict(recovered.payload), self.payload)
        result = self.store.commit_observation(
            operation_id="operation-a",
            generation=claim.generation,
            provider_id=claim.provider_id,
            argument_digest=claim.argument_digest,
            disposition="applied",
            terminal=True,
            external_id="calendar-event-a",
        )
        self.assertEqual(result.state, "applied")
        self.assertEqual(self.store.recovery_inventory(subject="subject-a"), [])

    def test_unknown_readback_remains_indeterminate_and_budget_is_bounded(self) -> None:
        self.prepare()
        claim = self.store.claim_dispatch(
            operation_id="operation-a",
            subject="subject-a",
            lease_digest=self.lease,
            authorize=lambda: None,
        )
        self.store.mark_indeterminate(
            operation_id="operation-a", generation=claim.generation
        )
        for _ in range(2):
            self.store.claim_readback(
                operation_id="operation-a",
                subject="subject-a",
                authorize=lambda: None,
            )
            item = self.store.commit_observation(
                operation_id="operation-a",
                generation=claim.generation,
                provider_id=claim.provider_id,
                argument_digest=claim.argument_digest,
                disposition="unknown",
                terminal=False,
            )
            self.assertEqual(item.state, "indeterminate")
        self.assert_code(
            "capability_payload_readback_exhausted",
            lambda: self.store.claim_readback(
                operation_id="operation-a",
                subject="subject-a",
                authorize=lambda: None,
            ),
        )

    def test_subject_revoke_denies_prepared_and_recovery_paths(self) -> None:
        self.prepare()
        self.store.revoke_subject(subject="subject-a")
        self.assert_code(
            "capability_payload_not_dispatchable",
            lambda: self.store.claim_dispatch(
                operation_id="operation-a",
                subject="subject-a",
                lease_digest=self.lease,
                authorize=lambda: None,
            ),
        )
        self.assert_code(
            "capability_payload_subject_revoked",
            lambda: self.prepare(operation_id="operation-b", idempotency_key="idem-b"),
        )

    def test_cross_tenant_recovery_is_denied(self) -> None:
        self.prepare()
        claim = self.store.claim_dispatch(
            operation_id="operation-a",
            subject="subject-a",
            lease_digest=self.lease,
            authorize=lambda: None,
        )
        self.store.mark_indeterminate(
            operation_id="operation-a", generation=claim.generation
        )
        self.assertEqual(self.store.recovery_inventory(subject="subject-b"), [])
        self.assert_code(
            "capability_payload_not_recoverable",
            lambda: self.store.claim_readback(
                operation_id="operation-a",
                subject="subject-b",
                authorize=lambda: None,
            ),
        )

    def test_restart_preserves_indeterminate_custody(self) -> None:
        self.prepare()
        claim = self.store.claim_dispatch(
            operation_id="operation-a",
            subject="subject-a",
            lease_digest=self.lease,
            authorize=lambda: None,
        )
        self.store.mark_indeterminate(
            operation_id="operation-a", generation=claim.generation
        )
        cipher = self.store.cipher
        self.store.close()
        self.store = EncryptedCapabilityPayloadStore(
            self.path,
            cipher=cipher,
            clock=lambda: self.now,
            maximum_readbacks=2,
        )
        items = self.store.recovery_inventory(subject="subject-a")
        self.assertEqual([(item.operation_id, item.state) for item in items],
                         [("operation-a", "indeterminate")])
        recovered = self.store.claim_readback(
            operation_id="operation-a",
            subject="subject-a",
            authorize=lambda: None,
        )
        self.assertEqual(dict(recovered.payload), self.payload)

    def test_plaintext_payload_is_not_persisted(self) -> None:
        self.prepare()
        self.store.checkpoint()
        raw = Path(self.path).read_bytes()
        self.assertNotIn(b"private meeting", raw)
        digest = self.store.canonical_digest(self.payload)
        self.assertIn(digest.encode("ascii"), raw)

    def test_ciphertext_or_binding_tamper_fails_closed(self) -> None:
        self.prepare()
        row = self.store.db.execute(
            "SELECT ciphertext FROM capability_payload_operations WHERE "
            "operation_id='operation-a'"
        ).fetchone()
        corrupted = bytearray(row[0])
        corrupted[-1] ^= 1
        self.store.db.execute(
            "UPDATE capability_payload_operations SET ciphertext=? WHERE "
            "operation_id='operation-a'",
            (bytes(corrupted),),
        )
        self.assert_code(
            "capability_payload_integrity_invalid",
            lambda: self.store.claim_dispatch(
                operation_id="operation-a",
                subject="subject-a",
                lease_digest=self.lease,
                authorize=lambda: None,
            ),
        )


if __name__ == "__main__":
    unittest.main()
