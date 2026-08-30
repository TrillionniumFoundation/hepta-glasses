"""Capability adapters, prompt-boundary rules, durable idempotency, and reconciliation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol


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


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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

    def document(self) -> dict[str, Any]:
        return {
            "arguments": dict(self.arguments),
            "deadline": self.deadline,
            "device_id": self.device_id,
            "human_confirmation_digest": self.human_confirmation_digest,
            "idempotency_key": self.idempotency_key,
            "name": self.name,
            "origin": self.origin.value,
            "request_id": self.request_id,
            "subject": self.subject,
            "task_id": self.task_id,
        }


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

    def document(self) -> dict[str, Any]:
        return {
            "completed_sequence": self.completed_sequence,
            "idempotency_key": self.idempotency_key,
            "prepared_sequence": self.prepared_sequence,
            "reconciled": self.reconciled,
            "request_id": self.request_id,
            "result": dict(self.result),
            "status": self.status,
        }

    @classmethod
    def from_document(cls, value: Mapping[str, Any]) -> "CapabilityReceipt":
        result = value.get("result")
        if not isinstance(result, Mapping):
            raise CapabilityError("capability_receipt_invalid")
        return cls(
            request_id=str(value["request_id"]),
            idempotency_key=str(value["idempotency_key"]),
            status=str(value["status"]),
            result=dict(result),
            prepared_sequence=(
                int(value["prepared_sequence"])
                if value.get("prepared_sequence") is not None
                else None
            ),
            completed_sequence=int(value["completed_sequence"]),
            reconciled=bool(value["reconciled"]),
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
    """SQLite-backed metadata-only hash chain shared with capability state."""

    def __init__(self, path: str | Path | None = None) -> None:
        database = ":memory:" if path is None else str(path)
        if database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database,
            check_same_thread=False,
            isolation_level=None,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if database != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_journal (
                    sequence INTEGER PRIMARY KEY,
                    event TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    hash TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_operations (
                    idempotency_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    receipt_json TEXT,
                    prepared_sequence INTEGER,
                    lease_id TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_consumed_leases (
                    lease_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    consumed_at INTEGER NOT NULL
                )
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def append(self, event: str, payload: Mapping[str, Any]) -> int:
        with self.transaction() as connection:
            return self.append_locked(connection, event, payload)

    def append_locked(
        self,
        connection: sqlite3.Connection,
        event: str,
        payload: Mapping[str, Any],
    ) -> int:
        row = connection.execute(
            "SELECT sequence, hash FROM capability_journal ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = str(row["hash"]) if row is not None else ""
        sequence = int(row["sequence"]) + 1 if row is not None else 1
        body = {
            "event": event,
            "payload": dict(payload),
            "previous_hash": previous,
            "sequence": sequence,
        }
        digest = canonical_digest(body)
        connection.execute(
            """
            INSERT INTO capability_journal
                (sequence, event, payload_json, previous_hash, hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sequence, event, _canonical_json(dict(payload)), previous, digest),
        )
        return sequence

    @property
    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT sequence, event, payload_json, previous_hash, hash
                FROM capability_journal ORDER BY sequence
                """
            ).fetchall()
        return [
            {
                "event": str(row["event"]),
                "hash": str(row["hash"]),
                "payload": json.loads(str(row["payload_json"])),
                "previous_hash": str(row["previous_hash"]),
                "sequence": int(row["sequence"]),
            }
            for row in rows
        ]

    def verify(self) -> None:
        previous = ""
        for index, entry in enumerate(self.entries, start=1):
            if entry["sequence"] != index or entry["previous_hash"] != previous:
                raise CapabilityError("capability_journal_invalid")
            body = {key: value for key, value in entry.items() if key != "hash"}
            if canonical_digest(body) != entry["hash"]:
                raise CapabilityError("capability_journal_invalid")
            previous = entry["hash"]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class CapabilityGateway:
    """Sole authority for cloud/phone capability effects."""

    def __init__(self, *, journal: AuditJournal, clock: Callable[[], int]) -> None:
        self.journal = journal
        self.clock = clock
        self._specs: dict[str, CapabilitySpec] = {}
        self._adapters: dict[str, CapabilityAdapter] = {}

    def register(self, spec: CapabilitySpec, adapter: CapabilityAdapter) -> None:
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
        now = self.clock()
        with self.journal.transaction() as connection:
            existing = connection.execute(
                """
                SELECT fingerprint, state, receipt_json, prepared_sequence
                FROM capability_operations WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["fingerprint"]) != request.fingerprint:
                    raise CapabilityError("idempotency_conflict")
                if existing["receipt_json"] is not None:
                    return CapabilityReceipt.from_document(
                        json.loads(str(existing["receipt_json"]))
                    ).as_replay()
                sequence = self.journal.append_locked(
                    connection,
                    "capability.retry_blocked",
                    {
                        "idempotency_key": request.idempotency_key,
                        "reason": "prepared_effect_outcome_unknown",
                        "request_id": request.request_id,
                    },
                )
                return CapabilityReceipt(
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    status="indeterminate",
                    result={"reason": "prepared_effect_outcome_unknown"},
                    prepared_sequence=(
                        int(existing["prepared_sequence"])
                        if existing["prepared_sequence"] is not None
                        else None
                    ),
                    completed_sequence=sequence,
                    reconciled=False,
                    replayed=True,
                )

            spec = self._specs.get(request.name)
            adapter = self._adapters.get(request.name)
            if spec is None or adapter is None:
                return self._deny_locked(
                    connection, request, "capability_unknown", now
                )
            if now >= request.deadline:
                return self._deny_locked(
                    connection, request, "capability_deadline_expired", now
                )
            if spec.risk is RiskTier.R4:
                return self._deny_locked(connection, request, "r4_disabled", now)
            fields = set(request.arguments)
            if not spec.required_fields.issubset(fields):
                return self._deny_locked(
                    connection, request, "capability_fields_missing", now
                )
            if fields - spec.required_fields - spec.optional_fields:
                return self._deny_locked(
                    connection, request, "capability_fields_unknown", now
                )
            if spec.mutating:
                denial = self._validate_mutation_locked(
                    connection, request, spec, lease, now
                )
                if denial is not None:
                    return self._deny_locked(connection, request, denial, now)

            self.journal.append_locked(
                connection,
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
                prepared_sequence = self.journal.append_locked(
                    connection,
                    "capability.prepared",
                    {
                        "argument_digest": canonical_digest(dict(request.arguments)),
                        "idempotency_key": request.idempotency_key,
                        "lease_id": lease.lease_id if lease else None,
                        "request_id": request.request_id,
                    },
                )
                if lease is not None and lease.single_use:
                    connection.execute(
                        """
                        INSERT INTO capability_consumed_leases
                            (lease_id, idempotency_key, consumed_at)
                        VALUES (?, ?, ?)
                        """,
                        (lease.lease_id, request.idempotency_key, now),
                    )
            connection.execute(
                """
                INSERT INTO capability_operations
                    (idempotency_key, fingerprint, request_json, state,
                     receipt_json, prepared_sequence, lease_id, updated_at)
                VALUES (?, ?, ?, 'prepared', NULL, ?, ?, ?)
                """,
                (
                    request.idempotency_key,
                    request.fingerprint,
                    _canonical_json(request.document()),
                    prepared_sequence,
                    lease.lease_id if lease else None,
                    now,
                ),
            )

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

        return self._complete(
            request=request,
            status=status,
            result=result,
            prepared_sequence=prepared_sequence,
            reconciled=reconciled,
        )

    def reconcile_prepared(
        self,
        request: CapabilityRequest,
        *,
        external_id: str,
    ) -> CapabilityReceipt:
        spec = self._specs.get(request.name)
        adapter = self._adapters.get(request.name)
        if spec is None or adapter is None or not spec.reconciliation_supported:
            raise CapabilityError("capability_reconciliation_unsupported")
        with self.journal.transaction() as connection:
            row = connection.execute(
                """
                SELECT fingerprint, receipt_json, prepared_sequence
                FROM capability_operations WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                raise CapabilityError("capability_prepared_unknown")
            if str(row["fingerprint"]) != request.fingerprint:
                raise CapabilityError("idempotency_conflict")
            if row["receipt_json"] is not None:
                return CapabilityReceipt.from_document(
                    json.loads(str(row["receipt_json"]))
                ).as_replay()
            prepared_sequence = (
                int(row["prepared_sequence"])
                if row["prepared_sequence"] is not None
                else None
            )

        result = dict(adapter.reconcile(request, external_id))
        status = "succeeded" if result.get("authoritative") else "indeterminate"
        return self._complete(
            request=request,
            status=status,
            result=result,
            prepared_sequence=prepared_sequence,
            reconciled=True,
        )

    def _complete(
        self,
        *,
        request: CapabilityRequest,
        status: str,
        result: Mapping[str, Any],
        prepared_sequence: int | None,
        reconciled: bool,
    ) -> CapabilityReceipt:
        with self.journal.transaction() as connection:
            row = connection.execute(
                """
                SELECT fingerprint, receipt_json
                FROM capability_operations WHERE idempotency_key = ?
                """,
                (request.idempotency_key,),
            ).fetchone()
            if row is None or str(row["fingerprint"]) != request.fingerprint:
                raise CapabilityError("capability_prepared_state_lost")
            if row["receipt_json"] is not None:
                return CapabilityReceipt.from_document(
                    json.loads(str(row["receipt_json"]))
                ).as_replay()
            completed_sequence = self.journal.append_locked(
                connection,
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
                result=dict(result),
                prepared_sequence=prepared_sequence,
                completed_sequence=completed_sequence,
                reconciled=reconciled,
            )
            connection.execute(
                """
                UPDATE capability_operations
                SET state = 'completed', receipt_json = ?, updated_at = ?
                WHERE idempotency_key = ? AND receipt_json IS NULL
                """,
                (
                    _canonical_json(receipt.document()),
                    self.clock(),
                    request.idempotency_key,
                ),
            )
            return receipt

    def _validate_mutation_locked(
        self,
        connection: sqlite3.Connection,
        request: CapabilityRequest,
        spec: CapabilitySpec,
        lease: DecisionLease | None,
        now: int,
    ) -> str | None:
        if request.origin is TrustClass.UNTRUSTED and not request.human_confirmation_digest:
            return "untrusted_content_cannot_authorize_mutation"
        if lease is None:
            return "decision_lease_required"
        if lease.single_use:
            consumed = connection.execute(
                "SELECT idempotency_key FROM capability_consumed_leases WHERE lease_id = ?",
                (lease.lease_id,),
            ).fetchone()
            if consumed is not None:
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

    def _deny_locked(
        self,
        connection: sqlite3.Connection,
        request: CapabilityRequest,
        reason: str,
        now: int,
    ) -> CapabilityReceipt:
        sequence = self.journal.append_locked(
            connection,
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
        connection.execute(
            """
            INSERT INTO capability_operations
                (idempotency_key, fingerprint, request_json, state,
                 receipt_json, prepared_sequence, lease_id, updated_at)
            VALUES (?, ?, ?, 'completed', ?, NULL, NULL, ?)
            """,
            (
                request.idempotency_key,
                request.fingerprint,
                _canonical_json(request.document()),
                _canonical_json(receipt.document()),
                now,
            ),
        )
        return receipt


class InMemoryReminderAdapter:
    """Deterministic OAuth-adapter stand-in with authoritative reconciliation."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self.indeterminate_once = False
        self.execute_count = 0

    def execute(self, request: CapabilityRequest) -> Mapping[str, Any]:
        self.execute_count += 1
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
