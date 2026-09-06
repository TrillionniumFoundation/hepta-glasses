"""Reference capability authority with bounded calls and conservative effect receipts.

State remains process-local. Production requires durable idempotency, an outbox,
trusted identity/lease ingress, provider deadlines and authoritative readback.
"""
from __future__ import annotations
import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from .bounded_calls import BoundedCalls


class CapabilityError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RiskTier(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


class TrustClass(str, Enum):
    SYSTEM = "system"
    USER = "user"
    UNTRUSTED = "untrusted"


def canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    risk: RiskTier
    mutating: bool
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()
    reconciliation_supported: bool = False


@dataclass(frozen=True)
class CapabilityRequest:
    request_id: str
    task_id: str
    subject: str
    device_id: str
    name: str
    arguments: Mapping[str, Any]
    idempotency_key: str
    deadline: int
    origin: TrustClass
    human_confirmation_digest: str | None = None

    @property
    def fingerprint(self) -> str:
        return canonical_digest({"arguments": dict(self.arguments), "device_id": self.device_id,
            "name": self.name, "request_id": self.request_id, "subject": self.subject, "task_id": self.task_id})


@dataclass(frozen=True)
class DecisionLease:
    lease_id: str
    subject: str
    device_id: str
    task_id: str
    action: str
    argument_digest: str
    expires_at: int
    biometric_verified: bool
    single_use: bool = True


@dataclass(frozen=True)
class CapabilityReceipt:
    request_id: str
    idempotency_key: str
    status: str
    result: Mapping[str, Any]
    prepared_sequence: int | None
    completed_sequence: int | None
    reconciled: bool
    replayed: bool = False

    def as_replay(self) -> CapabilityReceipt:
        return replace(self, replayed=True)


class IndeterminateEffect(RuntimeError):
    def __init__(self, external_id: str):
        super().__init__(external_id)
        self.external_id = external_id


class CapabilityAdapter(Protocol):
    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]: ...
    def reconcile(self, request: CapabilityRequest, external_id: str) -> Mapping[str, Any]: ...


class AuditJournal:
    """Thread-safe process-memory journal; not durable production evidence."""
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def append(self, event: str, payload: Mapping[str, Any]) -> int:
        with self._lock:
            body = {"event": event, "payload": dict(payload),
                "previous_hash": self.entries[-1]["hash"] if self.entries else "",
                "sequence": len(self.entries) + 1}
            body["hash"] = canonical_digest(body)
            self.entries.append(body)
            return body["sequence"]

    def verify(self) -> None:
        with self._lock:
            previous = ""
            for index, entry in enumerate(self.entries, start=1):
                if entry["sequence"] != index or entry["previous_hash"] != previous:
                    raise CapabilityError("capability_journal_invalid")
                if canonical_digest({key: value for key, value in entry.items() if key != "hash"}) != entry["hash"]:
                    raise CapabilityError("capability_journal_invalid")
                previous = entry["hash"]


@dataclass
class _InFlightCapability:
    fingerprint: str
    done: threading.Event
    error_code: str | None = None


class CapabilityGateway:
    """Single-process authority; post-dispatch uncertainty never permits replay."""
    def __init__(self, *, journal: AuditJournal, clock: Callable[[], int],
                 maximum_wait_seconds: float = 30.0, maximum_active_calls: int = 4,
                 maximum_receipts: int = 4096) -> None:
        if not math.isfinite(maximum_wait_seconds) or maximum_wait_seconds <= 0:
            raise ValueError("maximum_wait_seconds must be finite and positive")
        if type(maximum_receipts) is not int or maximum_receipts < 1:
            raise ValueError("maximum_receipts must be a positive integer")
        self.journal = journal
        self.clock = clock
        self.maximum_wait_seconds = maximum_wait_seconds
        self.maximum_receipts = maximum_receipts
        self._calls = BoundedCalls(maximum_active_calls)
        self._journal_healthy = True
        self._specs: dict[str, CapabilitySpec] = {}
        self._adapters: dict[str, CapabilityAdapter] = {}
        self._receipts: dict[str, CapabilityReceipt] = {}
        self._fingerprints: dict[str, str] = {}
        self._consumed_leases: set[str] = set()
        self._in_flight: dict[str, _InFlightCapability] = {}
        self._lock = threading.RLock()

    def register(self, spec: CapabilitySpec, adapter: CapabilityAdapter) -> None:
        if not spec.name or not isinstance(spec.risk, RiskTier) or type(spec.mutating) is not bool:
            raise CapabilityError("capability_spec_invalid")
        with self._lock:
            if spec.name in self._specs:
                raise CapabilityError("capability_already_registered")
            self._specs[spec.name] = spec
            self._adapters[spec.name] = adapter

    def execute(self, request: CapabilityRequest, *, lease: DecisionLease | None = None) -> CapabilityReceipt:
        identifiers = (request.request_id, request.task_id, request.subject,
                       request.device_id, request.name, request.idempotency_key)
        if (any(not isinstance(value, str) or not value or len(value) > 256 for value in identifiers)
                or type(request.deadline) is not int or not isinstance(request.origin, TrustClass)):
            raise CapabilityError("capability_request_invalid")
        try:
            payload = json.dumps(dict(request.arguments), ensure_ascii=False, allow_nan=False)
            if len(payload.encode("utf-8")) > 65536:
                raise ValueError("oversized arguments")
            request = replace(request, arguments=json.loads(payload))
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise CapabilityError("capability_arguments_invalid") from error
        key, fingerprint = request.idempotency_key, request.fingerprint
        wait = min(self.maximum_wait_seconds, max(0.0, request.deadline - self.clock()))
        wait_until = time.monotonic() + wait
        with self._lock:
            existing = self._receipts.get(key)
            if existing is not None:
                if self._fingerprints[key] != fingerprint:
                    raise CapabilityError("idempotency_conflict")
                return existing.as_replay()
            if not self._journal_healthy:
                raise CapabilityError("capability_audit_unavailable")
            active = self._in_flight.get(key)
            if active is not None:
                if active.fingerprint != fingerprint:
                    raise CapabilityError("idempotency_conflict")
                owner = False
            else:
                if len(self._receipts) + len(self._in_flight) >= self.maximum_receipts:
                    raise CapabilityError("capability_receipt_capacity_exhausted")
                active = _InFlightCapability(fingerprint, threading.Event())
                self._in_flight[key] = active
                owner = True
        if not owner:
            # Timing out a waiter never clears or replaces the execution owner.
            if not active.done.wait(max(0.0, wait_until - time.monotonic())):
                raise CapabilityError("capability_in_flight_deadline_exceeded")
            with self._lock:
                existing = self._receipts.get(key)
                if existing is not None:
                    return existing.as_replay()
                raise CapabilityError(active.error_code or "capability_execution_aborted")
        try:
            receipt = self._execute_once(request, lease=lease, wait_until=wait_until)
            with self._lock:
                self._fingerprints[key] = fingerprint
                self._receipts[key] = receipt
            return receipt
        except BaseException as error:
            with self._lock:
                active.error_code = error.code if isinstance(error, CapabilityError) else "capability_execution_aborted"
            raise
        finally:
            with self._lock:
                self._in_flight.pop(key, None)
                active.done.set()

    def _execute_once(self, request: CapabilityRequest, *, lease: DecisionLease | None,
                      wait_until: float) -> CapabilityReceipt:
        with self._lock:
            if not self._journal_healthy:
                raise CapabilityError("capability_audit_unavailable")
            now = self.clock()
            spec, adapter = self._specs.get(request.name), self._adapters.get(request.name)
            if spec is None or adapter is None:
                return self._deny(request, "capability_unknown")
            if now >= request.deadline:
                return self._deny(request, "capability_deadline_expired")
            if spec.risk is RiskTier.R4:
                return self._deny(request, "r4_disabled")
            fields = set(request.arguments)
            if not spec.required_fields.issubset(fields):
                return self._deny(request, "capability_fields_missing")
            if fields - spec.required_fields - spec.optional_fields:
                return self._deny(request, "capability_fields_unknown")
            if spec.mutating:
                denial = self._validate_mutation(request, spec, lease, now)
                if denial is not None:
                    return self._deny(request, denial)
            self.journal.append("capability.decision", {"action": request.name,
                "idempotency_key": request.idempotency_key, "request_id": request.request_id,
                "risk": spec.risk.value})
            prepared_sequence = None
            if spec.mutating:
                prepared_sequence = self.journal.append("capability.prepared", {
                    "argument_digest": canonical_digest(dict(request.arguments)),
                    "idempotency_key": request.idempotency_key, "lease_id": lease.lease_id if lease else None,
                    "request_id": request.request_id})
                if lease is not None and lease.single_use:
                    self._consumed_leases.add(lease.lease_id)

        def invoke() -> tuple[str, dict[str, Any], bool]:
            try:
                return "succeeded", dict(adapter.execute(request)), False
            except IndeterminateEffect as error:
                if not spec.reconciliation_supported:
                    return "indeterminate", {"external_id": error.external_id}, False
                try:
                    result = dict(adapter.reconcile(request, error.external_id))
                    return ("succeeded" if result.get("authoritative") is True else "indeterminate"), result, True
                except Exception as reconcile_error:
                    return "indeterminate", {"external_id": error.external_id,
                        "error_type": type(reconcile_error).__name__, "reason": "reconciliation_unavailable"}, True

        outcome = self._calls.run(invoke, timeout_seconds=min(
            max(0.0, wait_until - time.monotonic()), max(0.0, request.deadline - self.clock()),
            max(0.0, lease.expires_at - self.clock()) if lease is not None else self.maximum_wait_seconds))
        if outcome.state == "completed":
            status, result, reconciled = outcome.value
        else:
            possible = spec.mutating and outcome.state != "not_started"
            status = "indeterminate" if possible else "failed"
            result = {"error_type": outcome.error_type, "effect_may_have_occurred": possible,
                      "retry_safe": not possible}
            reconciled = False
        try:
            completed_sequence = self.journal.append("capability.completed", {
                "idempotency_key": request.idempotency_key, "reconciled": reconciled,
                "request_id": request.request_id, "status": status})
        except Exception:
            # Preserve the possibly committed effect in memory; forbid NEW work.
            # None truthfully means no terminal audit record was committed.
            with self._lock:
                self._journal_healthy = False
            completed_sequence = None
            status = "indeterminate" if spec.mutating else "failed"
            result = {"reason": "terminal_audit_unavailable", "effect_may_have_occurred": spec.mutating,
                      "retry_safe": not spec.mutating}
        return CapabilityReceipt(request.request_id, request.idempotency_key, status,
            result, prepared_sequence, completed_sequence, reconciled)

    def _validate_mutation(self, request: CapabilityRequest, spec: CapabilitySpec,
                           lease: DecisionLease | None, now: int) -> str | None:
        if request.origin is TrustClass.UNTRUSTED and not request.human_confirmation_digest:
            return "untrusted_content_cannot_authorize_mutation"
        if lease is None:
            return "decision_lease_required"
        if (not isinstance(lease.lease_id, str) or not lease.lease_id or
                type(lease.expires_at) is not int or lease.single_use is not True):
            return "decision_lease_invalid"
        if lease.lease_id in self._consumed_leases:
            return "decision_lease_consumed"
        if now >= lease.expires_at:
            return "decision_lease_expired"
        if (lease.subject != request.subject or lease.device_id != request.device_id or
                lease.task_id != request.task_id or lease.action != request.name or
                lease.argument_digest != canonical_digest(dict(request.arguments))):
            return "decision_lease_binding_mismatch"
        if spec.risk is RiskTier.R3 and lease.biometric_verified is not True:
            return "biometric_confirmation_required"
        if request.human_confirmation_digest is not None and request.human_confirmation_digest != lease.argument_digest:
            return "confirmation_digest_mismatch"
        return None

    def _deny(self, request: CapabilityRequest, reason: str) -> CapabilityReceipt:
        sequence = self.journal.append("capability.denied", {"action": request.name,
            "idempotency_key": request.idempotency_key, "reason": reason, "request_id": request.request_id})
        return CapabilityReceipt(request.request_id, request.idempotency_key, "denied",
            {"reason": reason}, None, sequence, False)


class InMemoryReminderAdapter:
    """Deterministic OAuth-adapter stand-in with authoritative reconciliation."""
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self.indeterminate_once = False
        self.execution_count = 0
        self._lock = threading.RLock()

    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
        external_id = f"reminder:{request.idempotency_key}"
        with self._lock:
            self.execution_count += 1
            record = self._records.setdefault(external_id, {"authoritative": True,
                "external_id": external_id,
                "title_hash": hashlib.sha256(str(request.arguments["title"]).encode("utf-8")).hexdigest()})
            if self.indeterminate_once:
                self.indeterminate_once = False
                raise IndeterminateEffect(external_id)
            return dict(record)

    def reconcile(self, request: CapabilityRequest, external_id: str) -> Mapping[str, Any]:
        with self._lock:
            return dict(self._records.get(external_id, {"authoritative": False, "external_id": external_id}))
