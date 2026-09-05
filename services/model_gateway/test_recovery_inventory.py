"""Recovery inventory tests use real SQLite and inert local provider fixtures."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.model_gateway.production import (
    ModelExecutionError,
    ProductionModelGateway,
    ProviderResult,
    digest,
)
from services.model_gateway.recovery_inventory import (
    ModelRecoveryPage,
    recoverable_page,
)


class Provider:
    def __init__(self) -> None:
        self.calls = 0
        self.reads = 0

    def generate(self, **kwargs):
        self.calls += 1
        return ProviderResult("inert answer", "req", "resp", kwargs["request_key"])

    def reconcile(self, **kwargs):
        self.reads += 1
        return None


class RecoveryInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Provider()
        self.gateway = ProductionModelGateway(
            str(Path(self.temp.name) / "model.sqlite"),
            provider=self.provider,
            provider_binding="fixture",
            clock=lambda: 1000,
            maximum_entries=1000,
        )
        self.addCleanup(self.gateway.close)

    def insert(self, key: str, *, subject: str = "user",
               state: str = "indeterminate", readbacks: int = 0) -> None:
        request_key = digest((subject + ":" + key).encode())
        with self.gateway.storage.transaction() as db:
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (subject, key, digest(key.encode()), "session", 0, state, 1100,
                 request_key, "claim", 0, readbacks, None, None, None),
            )

    def error(self, code: str, callback) -> None:
        with self.assertRaises(ModelExecutionError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_all_rows_can_be_traversed_beyond_legacy_first_page(self):
        expected = [f"key-{index:03d}" for index in range(205)]
        for key in reversed(expected):
            self.insert(key)
        found, after = [], ""
        while True:
            page = recoverable_page(self.gateway, subject="user", after=after)
            self.assertIsInstance(page, ModelRecoveryPage)
            self.assertIsInstance(page.records, tuple)
            found.extend(record.idempotency_key for record in page.records)
            if page.next_after is None:
                break
            after = page.next_after
        self.assertEqual(found, expected)
        self.assertEqual(len(found), len(set(found)))

    def test_subject_scope_and_terminal_rows_are_excluded(self):
        self.insert("a", subject="user", state="prepared")
        self.insert("b", subject="user", state="committed")
        self.insert("c", subject="other", state="indeterminate")
        page = recoverable_page(self.gateway, subject="user", limit=10)
        self.assertEqual([row.idempotency_key for row in page.records], ["a"])
        self.assertIsNone(page.next_after)

    def test_exact_page_has_no_false_continuation_and_extra_row_does(self):
        for key in ("a", "b"):
            self.insert(key)
        exact = recoverable_page(self.gateway, subject="user", limit=2)
        self.assertIsNone(exact.next_after)
        self.insert("c")
        first = recoverable_page(self.gateway, subject="user", limit=2)
        self.assertEqual(first.next_after, "b")
        self.assertEqual([r.idempotency_key for r in
                          recoverable_page(self.gateway, subject="user",
                                           after=first.next_after, limit=2).records], ["c"])

    def test_cursor_limit_subject_and_gateway_validation(self):
        for after in (True, " ", "a/b", "a\n", "x" * 129, "界"):
            self.error("model_inventory_cursor_invalid", lambda value=after:
                       recoverable_page(self.gateway, subject="user", after=value))
        for limit in (True, 0, 101, "1"):
            self.error("model_inventory_limit_invalid", lambda value=limit:
                       recoverable_page(self.gateway, subject="user", limit=value))
        self.error("model_binding_invalid", lambda:
                   recoverable_page(self.gateway, subject="bad subject"))
        self.error("model_inventory_gateway_invalid", lambda:
                   recoverable_page(object(), subject="user"))

    def test_listing_never_claims_readback_or_calls_provider(self):
        self.insert("a", readbacks=2)
        before = tuple(self.gateway.db.execute(
            "SELECT state,claim,claim_until,readbacks FROM requests"))
        events = self.gateway.db.execute("SELECT COUNT(*) FROM model_events").fetchone()[0]
        recoverable_page(self.gateway, subject="user", limit=1)
        after = tuple(self.gateway.db.execute(
            "SELECT state,claim,claim_until,readbacks FROM requests"))
        self.assertEqual(before, after)
        self.assertEqual(events, self.gateway.db.execute(
            "SELECT COUNT(*) FROM model_events").fetchone()[0])
        self.assertEqual((self.provider.calls, self.provider.reads), (0, 0))

    def test_insertions_after_cursor_are_seen_without_duplicate(self):
        for key in ("b", "d"):
            self.insert(key)
        first = recoverable_page(self.gateway, subject="user", limit=1)
        self.assertEqual(first.next_after, "b")
        self.insert("c")
        second = recoverable_page(self.gateway, subject="user",
                                  after=first.next_after, limit=10)
        self.assertEqual([r.idempotency_key for r in second.records], ["c", "d"])
        # A concurrent key inserted before the cursor is intentionally found by
        # a new scan, not silently claimed as part of the prior snapshot.
        self.insert("a")
        self.assertEqual([r.idempotency_key for r in
                          recoverable_page(self.gateway, subject="user", limit=10).records],
                         ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()
