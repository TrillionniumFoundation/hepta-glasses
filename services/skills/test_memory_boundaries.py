import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from .memory import MemoryConsent, MemoryError, MemoryStore


class MemoryBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.store = MemoryStore(clock=lambda: self.now)
        self.consent = MemoryConsent("user", "purpose", frozenset({"personal", "sensitive"}), 1000)
        self.store.grant_consent(self.consent)

    def remember(self, data_class="personal", value="fixture"):
        return self.store.remember(subject="user", purpose="purpose", data_class=data_class,
                                   value=value, ttl_seconds=500)

    def test_narrowing_consent_deletes_disallowed_records(self):
        self.remember("sensitive")
        self.remember("personal")
        self.store.grant_consent(replace(self.consent, allowed_data_classes=frozenset({"personal"})))
        self.assertEqual([item["data_class"] for item in self.store.export(subject="user")], ["personal"])
        self.assertEqual(self.store.search(subject="user", purpose="purpose", data_classes=["sensitive"]), [])

    def test_shorter_consent_caps_existing_ttl(self):
        self.remember()
        self.store.grant_consent(replace(self.consent, expires_at=101))
        self.now = 102
        self.assertEqual(self.store.export(subject="user"), [])
        self.assertEqual(self.store.search(subject="user", purpose="purpose"), [])

    def test_expiry_then_reconsent_does_not_resurrect_content(self):
        self.remember()
        self.now = 1001
        self.store.grant_consent(replace(self.consent, expires_at=2000))
        self.assertEqual(self.store.export(subject="user"), [])

    def test_identifier_collision_cannot_overwrite_record(self):
        self.store.id_factory = lambda: "same"
        self.remember(value="first")
        with self.assertRaisesRegex(MemoryError, "memory_id_conflict"):
            self.remember(value="second")
        self.assertEqual(self.store.export(subject="user")[0]["value"], "first")

    def test_revocation_is_atomic_with_concurrent_writers(self):
        def operation(_):
            try:
                self.remember()
            except MemoryError as error:
                self.assertEqual(error.code, "memory_consent_missing")
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = [pool.submit(operation, i) for i in range(40)]
            self.store.revoke_purpose(subject="user", purpose="purpose")
            for task in tasks:
                task.result()
        self.assertEqual(self.store.export(subject="user"), [])

    def test_value_and_record_capacity_are_enforced(self):
        self.store.maximum_value_bytes = 4
        with self.assertRaisesRegex(MemoryError, "memory_value_too_large"):
            self.remember(value="12345")
        self.store.maximum_records = 1
        self.remember(value="1234")
        with self.assertRaisesRegex(MemoryError, "memory_capacity_exhausted"):
            self.remember(value="1234")

    def test_diagnostic_ring_is_bounded_but_deletion_always_works(self):
        self.store.maximum_audit_entries = 2
        for _ in range(4):
            self.remember()
        self.assertEqual(len(self.store.audit), 2)
        self.assertEqual(self.store.delete_all(subject="user"), 4)
        self.assertEqual(self.store.export(subject="user"), [])
        self.assertEqual(len(self.store.audit), 2)
        self.assertNotIn("fixture", str(self.store.audit))

    def test_invalid_class_and_boolean_ttl_fail(self):
        with self.assertRaises(MemoryError):
            self.remember("Secret")
        with self.assertRaises(MemoryError):
            self.store.remember(subject="user", purpose="purpose", data_class="personal", value="x", ttl_seconds=True)

    def test_cross_subject_delete_cannot_remove_another_record(self):
        record = self.remember()
        self.assertFalse(self.store.delete(subject="different", memory_id=record.memory_id))
        self.assertEqual(len(self.store.export(subject="user")), 1)


if __name__ == "__main__":
    unittest.main()
