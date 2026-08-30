from __future__ import annotations

import unittest

from services.skills.memory import MemoryConsent, MemoryError, MemoryStore


class MemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100
        ids = iter(["memory-1", "memory-2", "memory-3", "memory-4"])
        self.store = MemoryStore(
            clock=lambda: self.now,
            id_factory=lambda: next(ids),
        )

    def consent(self) -> None:
        self.store.grant_consent(
            MemoryConsent(
                subject="user-1",
                purpose="assistant-preferences",
                allowed_data_classes=frozenset({"personal"}),
                expires_at=1_000,
            )
        )

    def test_memory_requires_consent_and_supports_export_delete(self) -> None:
        with self.assertRaises(MemoryError):
            self.store.remember(
                subject="user-1",
                purpose="assistant-preferences",
                data_class="personal",
                value="concise answers",
                ttl_seconds=100,
            )
        self.consent()
        record = self.store.remember(
            subject="user-1",
            purpose="assistant-preferences",
            data_class="personal",
            value="concise answers",
            ttl_seconds=100,
        )
        self.assertEqual(len(self.store.export(subject="user-1")), 1)
        self.assertTrue(
            self.store.delete(subject="user-1", memory_id=record.memory_id)
        )
        self.assertEqual(self.store.export(subject="user-1"), [])

    def test_secret_and_raw_audio_classes_are_forbidden(self) -> None:
        with self.assertRaises(MemoryError):
            self.store.grant_consent(
                MemoryConsent(
                    subject="user-1",
                    purpose="assistant-preferences",
                    allowed_data_classes=frozenset({"raw_audio"}),
                    expires_at=1_000,
                )
            )

    def test_consent_narrowing_deletes_disallowed_records_and_clamps_expiry(self) -> None:
        self.store.grant_consent(
            MemoryConsent(
                subject="user-1",
                purpose="assistant-preferences",
                allowed_data_classes=frozenset({"personal", "sensitive"}),
                expires_at=1_000,
            )
        )
        personal = self.store.remember(
            subject="user-1",
            purpose="assistant-preferences",
            data_class="personal",
            value="concise answers",
            ttl_seconds=800,
        )
        sensitive = self.store.remember(
            subject="user-1",
            purpose="assistant-preferences",
            data_class="sensitive",
            value="private preference",
            ttl_seconds=800,
        )

        self.store.grant_consent(
            MemoryConsent(
                subject="user-1",
                purpose="assistant-preferences",
                allowed_data_classes=frozenset({"personal"}),
                expires_at=300,
            )
        )
        results = self.store.search(
            subject="user-1", purpose="assistant-preferences"
        )
        self.assertEqual([record.memory_id for record in results], [personal.memory_id])
        self.assertEqual(results[0].expires_at, 300)
        exported_ids = {
            record["memory_id"] for record in self.store.export(subject="user-1")
        }
        self.assertNotIn(sensitive.memory_id, exported_ids)
        self.assertEqual(self.store.audit[-1]["deleted_count"], 1)
        self.assertEqual(self.store.audit[-1]["clamped_count"], 1)

    def test_expired_consent_removes_bound_records_from_search_and_export(self) -> None:
        self.consent()
        self.store.remember(
            subject="user-1",
            purpose="assistant-preferences",
            data_class="personal",
            value="preference",
            ttl_seconds=800,
        )
        self.now = 1_000
        self.assertEqual(
            self.store.search(
                subject="user-1", purpose="assistant-preferences"
            ),
            [],
        )
        self.assertEqual(self.store.export(subject="user-1"), [])

    def test_revoke_purpose_deletes_bound_records(self) -> None:
        self.consent()
        self.store.remember(
            subject="user-1",
            purpose="assistant-preferences",
            data_class="personal",
            value="preference",
            ttl_seconds=100,
        )
        self.assertEqual(
            self.store.revoke_purpose(
                subject="user-1", purpose="assistant-preferences"
            ),
            1,
        )
        self.assertEqual(
            self.store.search(
                subject="user-1", purpose="assistant-preferences"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
