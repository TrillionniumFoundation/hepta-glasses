"""Bounded caller latency and worker count, not a process isolation boundary."""
from __future__ import annotations
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CallOutcome:
    state: str
    value: Any = None
    error_type: str | None = None


class BoundedCalls:
    """A timed-out call retains its worker permit until the actual work exits.

    Python threads cannot safely kill an arbitrary provider call. The caller is
    bounded and excess work fails closed; a hung provider exhausts a finite pool
    instead of spawning unbounded threads. Production adapters still need socket
    deadlines, cooperative cancellation and process/service isolation.
    """
    def __init__(self, maximum_active: int = 4) -> None:
        if type(maximum_active) is not int or maximum_active < 1:
            raise ValueError("maximum_active must be a positive integer")
        self._permits = threading.BoundedSemaphore(maximum_active)

    def run(self, operation: Callable[[], Any], *, timeout_seconds: float) -> CallOutcome:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            return CallOutcome("not_started", error_type="DeadlineExpired")
        if not self._permits.acquire(blocking=False):
            return CallOutcome("not_started", error_type="WorkerCapacityExceeded")
        deadline = time.monotonic() + timeout_seconds
        done = threading.Event()
        outcome: list[CallOutcome] = []

        def worker() -> None:
            try:
                if time.monotonic() >= deadline:
                    outcome.append(CallOutcome("not_started", error_type="DeadlineExpired"))
                else:
                    try:
                        outcome.append(CallOutcome("completed", value=operation()))
                    except BaseException as error:
                        outcome.append(CallOutcome("error", error_type=type(error).__name__))
            finally:
                self._permits.release()
                done.set()

        try:
            threading.Thread(target=worker, name="hepta-capability", daemon=True).start()
        except Exception as error:
            self._permits.release()
            return CallOutcome("not_started", error_type=type(error).__name__)
        if not done.wait(max(0.0, deadline - time.monotonic())):
            return CallOutcome("timeout", error_type="AdapterDeadlineExceeded")
        return outcome[0]
