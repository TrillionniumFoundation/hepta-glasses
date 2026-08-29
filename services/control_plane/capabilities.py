"""Capability adapters, prompt-boundary rules, idempotency, and reconciliation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol


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
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
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
        return canonical_digest(
            {
                "arguments": dict(self.arguments),
                "device_id": self.device_id,
                "name": self.name,
                "request_id": self.request_id,
                "subject": self.subject,
                "task_id": self.task_id,
            }
        )


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
    completed_sequence: int
    reconciled: bool
    replayed: bool = False

    def as_replay(self) -> "CapabilityReceipt":
        return CapabilityReceipt(
            request_id=self.request_id,
            idempotency_key=self.idempotency_key,
            status=self.status,
            result=self.result,
            prepared_sequence=self.prepared_sequence,
            completed_sequence=self.completed_sequence,
            reconciled=self.reconciled,
            replayed=True,
        )


class IndeterminateEffect(RuntimeError):
    def __init__(self, external_id: str):
        super().__init__(external_id)
        self.external_id = external_id


class CapabilityAdapter(Protocol):
    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]: ...

    def reconcile(
        self, request: CapabilityRequest, external_id: str
    ) -> Mapping[str, Any]: ...


class AuditJournal:
    """Metadata-only hash-chained journal."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append(self, event: str, payload: Mapping[str, Any]) -> int:
        previous = self.entries[-1]["hash"] if self.entries else ""
        sequence = len(self.entries) + 1
        body = {
            "event": event,
            "payload": dict(payload),
            "previous_hash": previous,
            "sequence": sequence,
        }
        body["hash"] = canonical_digest(body)
        self.entries.append(body)
        return sequence

    def verify(self) -> None:
        previous = ""
        for index, entry in enumerate(self.entries, start=1):
            if entry["sequence"] != index or entry["previous_hash"] != previous:
                raise CapabilityError("capability_journal_invalid")
            body = {key: value for key, value in entry.items() if key != "hash"}
            if canonical_digest(body) != entry["hash"]:
                raise CapabilityError("capability_journal_invalid")
            previous = entry["hash"]


class CapabilityGateway:
    """Sole authority for cloud/phone capability effects."""

    def __init__(self, *, journal: AuditJournal, clock: Callable[[], int]) -> None:
        self.journal = journal
        self.clock = clock
        self._specs: dict[str, CapabilitySpec] = {}
        self._adapters: dict[str, CapabilityAdapter] = {}
        self._receipts: dict[str, CapabilityReceipt] = {}
        self._fingerprints: dict[str, str] = {}
        self._consumed_leases: set[str] = set()

    def register(
        self, spec: CapabilitySpec, adapter: CapabilityAdapter
    ) -> None:
        if spec.name in self._specs:
            raise CapabilityError("capability_already_registered")
        self._specs[spec.name] = spec
        self._adapters[spec.name] = adapter

    def execute(
        self,
        request: CapabilityRequest,
        *,
        lease: DecisionLease | None = None,
    ) -> CapabilityReceipt:
        existing = self._receipts.get(request.idempotency_key)
        if existing is not None:
            if self._fingerprints[request.idempotency_key] != request.fingerprint:
                raise CapabilityError("idempotency_conflict")
            return existing.as_replay()

        now = self.clock()
        spec = self._specs.get(request.name)
        adapter = self._adapters.get(request.name)
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

        decision_sequence = self.journal.append(
            "capability.decision",
            {
                "action": request.name,
                "idempotency_key": request.idempotency_key,
                "request_id": request.request_id,
                "risk": spec.risk.value,
            },
        )
        prepared_sequence = None
        if spec.mutating:
            prepared_sequence = self.journal.append(
                "capability.prepared",
                {
                    "argument_digest": canonical_digest(dict(request.arguments)),
                    "idempotency_key": request.idempotency_key,
                    "lease_id": lease.lease_id if lease else None,
                    "request_id": request.request_id,
                },
            )
            if lease is not None and lease.single_use:
                self._consumed_leases.add(lease.lease_id)

        reconciled = False
        try:
            result = dict(adapter.execute(request))
            status = "succeeded"
        except IndeterminateEffect as error:
            if not spec.reconciliation_supported:
                result = {"external_id": error.external_id}
                status = "indeterminate"
            else:
                result = dict(adapter.reconcile(request, error.external_id))
                status = "succeeded" if result.get("authoritative") else "indeterminate"
                reconciled = True
        except Exception as error:  # noqa: BLE001 - stable external boundary
            result = {"error_type": type(error).__name__}
            status = "failed"

        completed_sequence = self.journal.append(
            "capability.completed",
            {
                "idempotency_key": request.idempotency_key,
                "reconciled": reconciled,
                "request_id": request.request_id,
                "status": status,
            },
        )
        receipt = CapabilityReceipt(
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            status=status,
            result=result,
            prepared_sequence=prepared_sequence,
            completed_sequence=completed_sequence,
            reconciled=reconciled,
        )
        self._fingerprints[request.idempotency_key] = request.fingerprint
        self._receipts[request.idempotency_key] = receipt
        return receipt

    def _validate_mutation(
        self,
        request: CapabilityRequest,
        spec: CapabilitySpec,
        lease: DecisionLease | None,
        now: int,
    ) -> str | None:
        if request.origin is TrustClass.UNTRUSTED and not request.human_confirmation_digest:
            return "untrusted_content_cannot_authorize_mutation"
        if lease is None:
            return "decision_lease_required"
        if lease.lease_id in self._consumed_leases:
            return "decision_lease_consumed"
        if now >= lease.expires_at:
            return "decision_lease_expired"
        if (
            lease.subject != request.subject
            or lease.device_id != request.device_id
            or lease.task_id != request.task_id
            or lease.action != request.name
            or lease.argument_digest != canonical_digest(dict(request.arguments))
        ):
            return "decision_lease_binding_mismatch"
        if spec.risk is RiskTier.R3 and not lease.biometric_verified:
            return "biometric_confirmation_required"
        if request.human_confirmation_digest is not None and (
            request.human_confirmation_digest != lease.argument_digest
        ):
            return "confirmation_digest_mismatch"
        return None

    def _deny(self, request: CapabilityRequest, reason: str) -> CapabilityReceipt:
        sequence = self.journal.append(
            "capability.denied",
            {
                "action": request.name,
                "idempotency_key": request.idempotency_key,
                "reason": reason,
                "request_id": request.request_id,
            },
        )
        receipt = CapabilityReceipt(
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            status="denied",
            result={"reason": reason},
            prepared_sequence=None,
            completed_sequence=sequence,
            reconciled=False,
        )
        self._fingerprints[request.idempotency_key] = request.fingerprint
        self._receipts[request.idempotency_key] = receipt
        return receipt


class InMemoryReminderAdapter:
    """Deterministic OAuth-adapter stand-in with authoritative reconciliation."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self.indeterminate_once = False

    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
        external_id = f"reminder:{request.idempotency_key}"
        record = self._records.setdefault(
            external_id,
            {
                "authoritative": True,
                "external_id": external_id,
                "title_hash": hashlib.sha256(
                    str(request.arguments["title"]).encode("utf-8")
                ).hexdigest(),
            },
        )
        if self.indeterminate_once:
            self.indeterminate_once = False
            raise IndeterminateEffect(external_id)
        return record

    def reconcile(
        self, request: CapabilityRequest, external_id: str
    ) -> Mapping[str, Any]:
        return self._records.get(
            external_id,
            {"authoritative": False, "external_id": external_id},
        )
