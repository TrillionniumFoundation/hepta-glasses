"""Deterministic worker-exhaustion tests; fixture provider is not live evidence."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from services.model_gateway.production import (
    ModelExecutionError,
    ProductionModelGateway,
    ProviderResult,
)


class BlockingProvider:
    binding_id = "blocking-fixture"

    def __init__(self, workers: int) -> None:
        self.workers = workers
        self.condition = threading.Condition()
        self.release = threading.Event()
        self.entered = 0
        self.exited = 0
        self.request_keys: list[str] = []

    def generate(self, **kwargs) -> ProviderResult:
        with self.condition:
            self.entered += 1
            self.request_keys.append(kwargs["request_key"])
            self.condition.notify_all()
        if not self.release.wait(10):
            raise AssertionError("test did not release blocked provider workers")
        with self.condition:
            self.exited += 1
            self.condition.notify_all()
        return ProviderResult(
            "late-answer-fixture",
            "late-request-fixture",
            "late-receipt-fixture",
            kwargs["request_key"],
        )

    def reconcile(self, **kwargs) -> ProviderResult | None:
        raise AssertionError("new request unexpectedly entered reconciliation")

    def wait_for(self, attribute: str, expected: int, timeout: float = 10) -> None:
        with self.condition:
            if not self.condition.wait_for(
                lambda: getattr(self, attribute) == expected,
                timeout=timeout,
            ):
                raise AssertionError(
                    f"{attribute}={getattr(self, attribute)}; expected {expected}"
                )


class DeterministicWorkerExhaustionTests(unittest.TestCase):
    def test_four_timed_out_workers_fence_the_fifth_without_late_commit(self) -> None:
        provider = BlockingProvider(workers=4)
        with tempfile.TemporaryDirectory() as directory:
            gateway = ProductionModelGateway(
                str(Path(directory) / "model.sqlite"),
                provider=provider,
                provider_binding=provider.binding_id,
                clock=lambda: 1_000,
                maximum_workers=4,
            )
            errors: dict[str, str] = {}

            def call(index: int, timeout: float) -> None:
                key = f"request-{index}"
                try:
                    gateway.execute(
                        subject="user",
                        session_id="session",
                        idempotency_key=key,
                        question="bounded worker fixture",
                        context={"index": index},
                        expires_at=1_100,
                        timeout_seconds=timeout,
                    )
                except ModelExecutionError as exc:
                    errors[key] = exc.code

            callers = [
                threading.Thread(target=call, args=(index, 0.5), daemon=False)
                for index in range(4)
            ]
            try:
                for caller in callers:
                    caller.start()
                provider.wait_for("entered", 4)
                for caller in callers:
                    caller.join(timeout=3)
                    self.assertFalse(caller.is_alive())
                self.assertEqual(
                    errors,
                    {
                        "request-0": "model_effect_indeterminate",
                        "request-1": "model_effect_indeterminate",
                        "request-2": "model_effect_indeterminate",
                        "request-3": "model_effect_indeterminate",
                    },
                )

                call(4, 0.5)
                self.assertEqual(errors["request-4"], "model_effect_indeterminate")
                self.assertEqual(provider.entered, 4)
                self.assertEqual(len(set(provider.request_keys)), 4)
                self.assertEqual(
                    gateway.db.execute(
                        "SELECT COUNT(*) FROM requests WHERE state='committed'"
                    ).fetchone()[0],
                    0,
                )

                provider.release.set()
                provider.wait_for("exited", 4)
                self.assertEqual(
                    gateway.db.execute(
                        "SELECT COUNT(*) FROM requests WHERE state='committed'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    gateway.db.execute(
                        "SELECT COUNT(*) FROM requests WHERE state='indeterminate'"
                    ).fetchone()[0],
                    5,
                )
            finally:
                provider.release.set()
                for caller in callers:
                    caller.join(timeout=3)
                gateway.close()


if __name__ == "__main__":
    unittest.main()
