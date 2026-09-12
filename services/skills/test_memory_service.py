from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from services.skills.durable_memory import DurableMemoryStore
from services.skills.memory_service import (
    CONSENT_SCOPE,
    DEFAULT_AUDIENCE,
    DELETE_SCOPE,
    MIGRATE_SCOPE,
    READ_SCOPE,
    RECONCILE_SCOPE,
    WRITE_SCOPE,
    AuthenticatedMemoryService,
    LegacyMemoryRecord,
    MemoryDeletionReceipt,
    MemoryDeletionReconciler,
    MemoryPrincipal,
    MemoryServiceError,
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


class Identity:
    def __init__(self) -> None:
        self.subject = "subject-a"
        self.expires_at = 1_000
        self.failure = None
        self.calls = []

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> MemoryPrincipal:
        self.calls.append((bearer_token, audience, required_scope))
        if self.failure:
            raise self.failure
        return MemoryPrincipal(
            subject=self.subject,
            session_id="session-a",
            audience=DEFAULT_AUDIENCE,
            scopes=(required_scope,),
            expires_at=self.expires_at,
        )


class Sink:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.calls = []
        self.failure = None
        self.mutate = None

    def delete(self, *, event, idempotency_key, timeout_seconds):
        self.calls.append((dict(event), idempotency_key, timeout_seconds))
        if self.failure:
            raise self.failure
        receipt = MemoryDeletionReceipt(
            event_id=event["event_id"],
            subject=event["subject"],
            memory_id=event["memory_id"],
            disposition="deleted",
            terminal=True,
            receipt_id="remote-receipt-a",
            observed_at=self.clock(),
        )
        return receipt if self.mutate is None else self.mutate(receipt)


class AuthenticatedMemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "memory.sqlite")
        self.now = 100
        self.cipher = Cipher()
        self.store = DurableMemoryStore(
            self.path, cipher=self.cipher, clock=lambda: self.now
        )
        self.addCleanup(self.store.close)
        self.identity = Identity()
        self.service = AuthenticatedMemoryService(
            store=self.store,
            identity=self.identity,
            clock=lambda: self.now,
        )
        self.authorization = "Bearer account-session-token-123456"

    def assert_code(self, code: str, callback, status: int | None = None) -> None:
        with self.assertRaises(MemoryServiceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        if status is not None:
            self.assertEqual(raised.exception.status, status)

    def consent(self, *, purpose: str = "assistant") -> None:
        self.service.grant_consent(
            authorization=self.authorization,
            purpose=purpose,
            allowed_data_classes=("personal", "sensitive"),
            expires_at=900,
        )

    def test_subject_and_scope_come_only_from_current_identity(self) -> None:
        self.consent()
        record = self.service.remember(
            authorization=self.authorization,
            purpose="assistant",
            data_class="personal",
            value="subject-a-memory",
            ttl_seconds=100,
        )
        self.assertEqual(record.subject, "subject-a")
        self.assertEqual(
            self.service.export(authorization=self.authorization)[0]["value"],
            "subject-a-memory",
        )
        self.identity.subject = "subject-b"
        self.assertEqual(self.service.export(authorization=self.authorization), [])
        self.assertEqual(
            [entry[2] for entry in self.identity.calls],
            [CONSENT_SCOPE, WRITE_SCOPE, READ_SCOPE, READ_SCOPE],
        )

    def test_identity_expiry_caps_consent_and_record(self) -> None:
        self.identity.expires_at = 180
        self.service.grant_consent(
            authorization=self.authorization,
            purpose="assistant",
            allowed_data_classes=("personal",),
            expires_at=500,
        )
        record = self.service.remember(
            authorization=self.authorization,
            purpose="assistant",
            data_class="personal",
            value="bounded",
            ttl_seconds=500,
        )
        self.assertEqual(record.expires_at, 180)

    def test_invalid_identity_fails_before_storage(self) -> None:
        self.assert_code(
            "memory_service_unauthorized",
            lambda: self.service.export(authorization=None),
            401,
        )
        self.identity.failure = RuntimeError("sensitive verifier detail")
        self.assert_code(
            "memory_service_unauthorized",
            lambda: self.service.export(authorization=self.authorization),
            401,
        )
        self.identity.failure = None
        self.identity.expires_at = self.now
        self.assert_code(
            "memory_service_unauthorized",
            lambda: self.service.export(authorization=self.authorization),
            401,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0],
            0,
        )

    def test_legacy_migration_is_atomic_idempotent_and_conflict_safe(self) -> None:
        self.consent()
        records = (
            LegacyMemoryRecord("legacy-a", "assistant", "personal", "one", 500),
            LegacyMemoryRecord("legacy-b", "assistant", "sensitive", "two", 500),
        )
        first = self.service.migrate_legacy(
            authorization=self.authorization, records=records
        )
        second = self.service.migrate_legacy(
            authorization=self.authorization, records=records
        )
        self.assertEqual(
            [record.memory_id for record in first],
            [record.memory_id for record in second],
        )
        self.assertTrue(all(record.memory_id.startswith("legacy.") for record in first))
        before = self.store.db.execute(
            "SELECT COUNT(*) FROM memory_records"
        ).fetchone()[0]
        self.assert_code(
            "durable_memory_migration_conflict",
            lambda: self.service.migrate_legacy(
                authorization=self.authorization,
                records=(
                    LegacyMemoryRecord(
                        "new-record", "assistant", "personal", "new", 500
                    ),
                    LegacyMemoryRecord(
                        "legacy-a", "assistant", "personal", "changed", 500
                    ),
                ),
            ),
            409,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0],
            before,
        )
        self.assertEqual(self.identity.calls[-1][2], MIGRATE_SCOPE)

    def test_duplicate_or_outliving_migration_is_rejected(self) -> None:
        self.consent()
        duplicate = LegacyMemoryRecord(
            "same", "assistant", "personal", "value", 500
        )
        self.assert_code(
            "durable_memory_migration_duplicate",
            lambda: self.service.migrate_legacy(
                authorization=self.authorization,
                records=(duplicate, duplicate),
            ),
            409,
        )
        self.identity.expires_at = 300
        self.assert_code(
            "memory_migration_invalid",
            lambda: self.service.migrate_legacy(
                authorization=self.authorization,
                records=(LegacyMemoryRecord(
                    "future", "assistant", "personal", "value", 301
                ),),
            ),
        )

    def test_key_rotation_creates_explicit_retirement_custody(self) -> None:
        self.consent()
        self.service.remember(
            authorization=self.authorization,
            purpose="assistant",
            data_class="personal",
            value="rotate-me",
            ttl_seconds=100,
        )
        self.cipher.keys["subject-a"]["key-a2"] = b"z" * 32
        self.cipher.current["subject-a"] = "key-a2"
        self.assertEqual(
            self.service.rotate_subject_key(authorization=self.authorization), 1
        )
        self.assertEqual(
            self.service.pending_key_retirements(
                authorization=self.authorization
            ),
            ("key-a",),
        )
        self.service.acknowledge_key_retirement(
            authorization=self.authorization, key_id="key-a"
        )
        self.assertEqual(
            self.service.pending_key_retirements(
                authorization=self.authorization
            ),
            (),
        )
        self.assertEqual(self.identity.calls[-1][2], RECONCILE_SCOPE)

    def test_remote_deletion_receipt_is_exact_and_hash_chained(self) -> None:
        self.consent()
        ids = []
        for value in ("delete-one", "delete-two"):
            record = self.service.remember(
                authorization=self.authorization,
                purpose="assistant",
                data_class="personal",
                value=value,
                ttl_seconds=100,
            )
            ids.append(record.memory_id)
            self.assertTrue(self.service.delete(
                authorization=self.authorization, memory_id=record.memory_id
            ))
        sink = Sink(lambda: self.now)
        reconciler = MemoryDeletionReconciler(
            store=self.store,
            identity=self.identity,
            sink=sink,
            clock=lambda: self.now,
        )
        self.assertEqual(
            reconciler.deliver(authorization=self.authorization), 2
        )
        self.assertEqual(reconciler.verify_receipt_chain(), 2)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM memory_deletions WHERE state='pending'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            [call[1] for call in sink.calls],
            [call[0]["event_id"] for call in sink.calls],
        )
        self.assertEqual(self.identity.calls[-1][2], RECONCILE_SCOPE)

    def test_bad_or_failed_remote_receipt_remains_pending(self) -> None:
        self.consent()
        record = self.service.remember(
            authorization=self.authorization,
            purpose="assistant",
            data_class="personal",
            value="delete-me",
            ttl_seconds=100,
        )
        self.service.delete(
            authorization=self.authorization, memory_id=record.memory_id
        )
        sink = Sink(lambda: self.now)
        reconciler = MemoryDeletionReconciler(
            store=self.store,
            identity=self.identity,
            sink=sink,
            clock=lambda: self.now,
        )
        sink.mutate = lambda receipt: MemoryDeletionReceipt(
            event_id="wrong-event",
            subject=receipt.subject,
            memory_id=receipt.memory_id,
            disposition=receipt.disposition,
            terminal=True,
            receipt_id=receipt.receipt_id,
            observed_at=receipt.observed_at,
        )
        self.assert_code(
            "memory_deletion_receipt_invalid",
            lambda: reconciler.deliver(authorization=self.authorization),
            503,
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM memory_deletions WHERE state='pending'"
            ).fetchone()[0],
            1,
        )
        sink.mutate = None
        sink.failure = RuntimeError("provider detail")
        self.assert_code(
            "memory_deletion_indeterminate",
            lambda: reconciler.deliver(authorization=self.authorization),
            503,
        )

    def test_subject_filtered_deletion_pages_do_not_starve_tenant(self) -> None:
        for subject in ("subject-a", "subject-b"):
            self.identity.subject = subject
            self.consent()
            record = self.service.remember(
                authorization=self.authorization,
                purpose="assistant",
                data_class="personal",
                value=subject,
                ttl_seconds=100,
            )
            self.service.delete(
                authorization=self.authorization, memory_id=record.memory_id
            )
        self.identity.subject = "subject-b"
        sink = Sink(lambda: self.now)
        reconciler = MemoryDeletionReconciler(
            store=self.store,
            identity=self.identity,
            sink=sink,
            clock=lambda: self.now,
        )
        self.assertEqual(
            reconciler.deliver(authorization=self.authorization, limit=1), 1
        )
        self.assertEqual(sink.calls[0][0]["subject"], "subject-b")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM memory_deletions WHERE subject='subject-a'"
            ).fetchone()[0],
            1,
        )

    def test_urlsafe_memory_ids_may_start_with_urlsafe_punctuation(self) -> None:
        for memory_id in ("_legacy_urlsafe_id", "-legacy_urlsafe_id"):
            self.assertFalse(
                self.service.delete(
                    authorization=self.authorization,
                    memory_id=memory_id,
                )
            )

    def test_plaintext_and_bearer_are_not_persisted(self) -> None:
        self.consent()
        self.service.remember(
            authorization=self.authorization,
            purpose="assistant",
            data_class="personal",
            value="MEMORY-SERVICE-PLAINTEXT",
            ttl_seconds=100,
        )
        self.store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw = Path(self.path).read_bytes()
        self.assertNotIn(b"account-session-token-123456", raw)
        self.assertNotIn(b"MEMORY-SERVICE-PLAINTEXT", raw)


if __name__ == "__main__":
    unittest.main()
