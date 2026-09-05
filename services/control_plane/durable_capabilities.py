"""Durable effect custody, not an OAuth service or an authentication boundary.

Only trusted service composition may construct leases/register adapters. No raw
arguments, provider responses, OAuth tokens or credentials are persisted here.
A dispatch reservation survives restart and can never be dispatched twice.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .bounded_calls import BoundedCalls
from .capability_suspension import CONTROL_TABLE, VERSION, control_status, create_control, suspend
from .capabilities import (
    CapabilityError, CapabilityReceipt, CapabilityRequest, CapabilitySpec,
    DecisionLease, RiskTier, TrustClass, canonical_digest,
)
from .durable_state import DurableDatabase, deadline, identifier, timestamp


_TERMINAL = frozenset({"succeeded", "failed", "denied"})
_OPAQUE = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")


@dataclass(frozen=True)
class ProviderObservation:
    """Adapter-verified observation, bound to one provider operation.

    terminal/not_applied means the provider guarantees that this operation
    cannot later apply; mere absence or an eventually consistent 404 is unknown.
    This value is not a signature and must never be accepted from client JSON.
    """
    operation_id: str
    provider_id: str
    argument_digest: str
    disposition: str  # applied, not_applied, unknown
    terminal: bool = False
    external_id: str | None = None


class DurableCapabilityAdapter(Protocol):
    def execute(self, request: CapabilityRequest, operation_id: str) -> ProviderObservation: ...
    def readback(self, request: CapabilityRequest, operation_id: str,
                 external_id: str | None) -> ProviderObservation: ...


@dataclass(frozen=True)
class _Registration:
    spec: CapabilitySpec
    provider_id: str
    digest: str
    adapter: DurableCapabilityAdapter


class DurableCapabilityGateway:
    """SQLite intent ledger + single-use lease consumption + readback inventory.

    No automatic dispatch on recovery. A process failure after reservation is
    conservatively uncertain, even if the network call had not actually begun.
    All network work runs outside transactions. Timed-out workers retain their
    bounded pool permit; socket/process deadlines remain an adapter obligation.
    """
    def __init__(self, path: str, *, clock: Callable[[], int],
                 maximum_wait_seconds: float = 10, maximum_active_calls: int = 4,
                 maximum_operations: int = 4096, maximum_readbacks: int = 8) -> None:
        if not deadline(maximum_wait_seconds):
            raise ValueError("capability_wait_invalid")
        if (type(maximum_operations) is not int or not 1 <= maximum_operations <= 1000000
                or type(maximum_readbacks) is not int or not 1 <= maximum_readbacks <= 32):
            raise ValueError("capability_capacity_invalid")
        self.clock = clock
        self.maximum_wait_seconds = maximum_wait_seconds
        self.maximum_operations = maximum_operations
        self.maximum_readbacks = maximum_readbacks
        self._calls = BoundedCalls(maximum_active_calls)
        self._registrations: dict[str, _Registration] = {}
        self._registration_lock = threading.RLock()
        self.store = DurableDatabase(path)
        try:
            with self.store.transaction() as db:
                unmarked = self.store.version("durable_capabilities", VERSION)
                if unmarked and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name LIKE 'hg_capability_%'"
                ).fetchone():
                    raise ValueError("capability_unmarked_schema_rejected")
                required_tables = {
                    "hg_capability_operations", "hg_capability_leases",
                    "hg_capability_revoked", "hg_capability_events", CONTROL_TABLE,
                }
                if not unmarked:
                    actual_tables = {row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )}
                    if not required_tables <= actual_tables:
                        raise ValueError("capability_schema_integrity_invalid")
                statements = (
                    "CREATE TABLE IF NOT EXISTS hg_capability_operations ("
                    "key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, subject TEXT NOT NULL, "
                    "operation_id TEXT UNIQUE NOT NULL, provider_id TEXT NOT NULL, "
                    "argument_digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN "
                    "('dispatching','indeterminate','succeeded','failed','denied')), "
                    "reason TEXT NOT NULL, external_id TEXT, prepared_sequence INTEGER, "
                    "completed_sequence INTEGER, reconciled INTEGER NOT NULL DEFAULT 0, "
                    "readbacks INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS hg_capability_leases ("
                    "lease_hash TEXT PRIMARY KEY, operation_key TEXT UNIQUE NOT NULL "
                    "REFERENCES hg_capability_operations(key))",
                    "CREATE TABLE IF NOT EXISTS hg_capability_revoked ("
                    "subject TEXT PRIMARY KEY, revoked_at INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS hg_capability_events ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_key TEXT NOT NULL "
                    "REFERENCES hg_capability_operations(key), event TEXT NOT NULL, "
                    "created_at INTEGER NOT NULL)",
                    "CREATE INDEX IF NOT EXISTS hg_capability_pending "
                    "ON hg_capability_operations(subject,state,operation_id)",
                )
                for statement in statements:
                    db.execute(statement)
                if unmarked:
                    create_control(db)
                control_status(db)
                self.store.mark_version("durable_capabilities", VERSION)
        except BaseException:
            self.store.close()
            raise

    def close(self) -> None:
        self.store.close()

    def register(self, spec: CapabilitySpec, *, provider_id: str,
                 adapter: DurableCapabilityAdapter) -> None:
        if (not isinstance(spec, CapabilitySpec) or not identifier(spec.name)
                or not isinstance(spec.risk, RiskTier) or spec.mutating is not True
                or not identifier(provider_id, 128)
                or not isinstance(spec.required_fields, (set, frozenset))
                or not isinstance(spec.optional_fields, (set, frozenset))
                or any(not identifier(field, 128) for field in
                       spec.required_fields | spec.optional_fields)
                or spec.required_fields & spec.optional_fields
                or not callable(getattr(adapter, "execute", None))
                or not callable(getattr(adapter, "readback", None))):
            raise CapabilityError("durable_capability_spec_invalid")
        # Concrete adapters may pin the exact provider namespace and public
        # capability contract. Registration must not silently relabel them.
        if (getattr(adapter, "provider_id", provider_id) != provider_id
                or getattr(adapter, "capability_spec", spec) != spec
                or (hasattr(adapter, "execute_authorized")
                    and not callable(adapter.execute_authorized))):
            raise CapabilityError("capability_adapter_binding_mismatch")
        spec = replace(spec, required_fields=frozenset(spec.required_fields),
                       optional_fields=frozenset(spec.optional_fields))
        digest = canonical_digest({"name": spec.name, "risk": spec.risk.value,
            "required": sorted(spec.required_fields), "optional": sorted(spec.optional_fields),
            "provider": provider_id, "contract": "durable-capability-v1"})
        with self._registration_lock:
            if spec.name in self._registrations:
                raise CapabilityError("capability_already_registered")
            self._registrations[spec.name] = _Registration(spec, provider_id, digest, adapter)

    def _now(self) -> int:
        now = self.clock()
        if not timestamp(now):
            raise CapabilityError("capability_clock_invalid")
        return now

    def _snapshot(self, request: CapabilityRequest) -> tuple[CapabilityRequest, _Registration, str, str]:
        if (not isinstance(request, CapabilityRequest)
                or any(not identifier(value) for value in (request.request_id, request.task_id,
                    request.subject, request.device_id, request.name, request.idempotency_key))
                or not timestamp(request.deadline) or not isinstance(request.origin, TrustClass)
                or (request.human_confirmation_digest is not None and
                    (not isinstance(request.human_confirmation_digest, str) or
                     not re.fullmatch(r"[0-9a-f]{64}", request.human_confirmation_digest)))):
            raise CapabilityError("capability_request_invalid")
        try:
            # Reject non-string keys before JSON can silently coerce/collide them.
            def keys(value: object) -> None:
                if isinstance(value, dict):
                    if any(not isinstance(key, str) for key in value):
                        raise ValueError("non-string key")
                    for child in value.values():
                        keys(child)
                elif isinstance(value, (list, tuple)):
                    for child in value:
                        keys(child)
            arguments = dict(request.arguments)
            keys(arguments)
            encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 65536:
                raise ValueError("oversized arguments")
            request = replace(request, arguments=json.loads(encoded))
        except (TypeError, ValueError, UnicodeError, RecursionError) as error:
            raise CapabilityError("capability_arguments_invalid") from error
        with self._registration_lock:
            registration = self._registrations.get(request.name)
        if registration is None:
            raise CapabilityError("capability_unknown")
        key = canonical_digest({"subject": request.subject, "key": request.idempotency_key})
        fingerprint = canonical_digest({"request": request.fingerprint,
            "origin": request.origin.value, "confirmation": request.human_confirmation_digest,
            "deadline": request.deadline, "registration": registration.digest})
        return request, registration, key, fingerprint

    def _denial(self, db: sqlite3.Connection, request: CapabilityRequest,
                spec: CapabilitySpec, lease: DecisionLease | None, now: int) -> str | None:
        if db.execute("SELECT 1 FROM hg_capability_revoked WHERE subject=?",
                      (canonical_digest({"subject": request.subject}),)).fetchone():
            return "subject_revoked"
        if now >= request.deadline:
            return "capability_deadline_expired"
        if spec.risk is RiskTier.R4:
            return "r4_disabled"
        if not spec.required_fields.issubset(request.arguments):
            return "capability_fields_missing"
        if set(request.arguments) - spec.required_fields - spec.optional_fields:
            return "capability_fields_unknown"
        if request.origin is TrustClass.UNTRUSTED and not request.human_confirmation_digest:
            return "untrusted_content_cannot_authorize_mutation"
        if lease is None:
            return "decision_lease_required"
        if (not isinstance(lease, DecisionLease) or not identifier(lease.lease_id)
                or not timestamp(lease.expires_at) or lease.single_use is not True
                or type(lease.biometric_verified) is not bool):
            return "decision_lease_invalid"
        if now >= lease.expires_at:
            return "decision_lease_expired"
        if (lease.subject != request.subject or lease.device_id != request.device_id
                or lease.task_id != request.task_id or lease.action != request.name
                or lease.argument_digest != canonical_digest(dict(request.arguments))):
            return "decision_lease_binding_mismatch"
        if spec.risk is RiskTier.R3 and not lease.biometric_verified:
            return "biometric_confirmation_required"
        if (request.human_confirmation_digest is not None
                and request.human_confirmation_digest != lease.argument_digest):
            return "confirmation_digest_mismatch"
        if db.execute("SELECT 1 FROM hg_capability_leases WHERE lease_hash=?",
                      (canonical_digest({"lease": lease.lease_id}),)).fetchone():
            return "decision_lease_consumed"
        return None

    def _event(self, db: sqlite3.Connection, key: str, event: str) -> int:
        return db.execute("INSERT INTO hg_capability_events(operation_key,event,created_at) "
                          "VALUES(?,?,?)", (key, event, self._now())).lastrowid

    @staticmethod
    def _receipt(request: CapabilityRequest, row: sqlite3.Row, *, replayed: bool = False) -> CapabilityReceipt:
        state = row["state"]
        return CapabilityReceipt(request.request_id, request.idempotency_key,
            "indeterminate" if state == "dispatching" else state,
            {"operation_id": row["operation_id"], "provider_id": row["provider_id"],
             "external_id": row["external_id"], "reason": row["reason"],
             "effect_may_have_occurred": state in {"dispatching", "indeterminate", "succeeded"},
             "retry_safe": False},  # a new effect always needs a new decision
            row["prepared_sequence"], row["completed_sequence"], bool(row["reconciled"]), replayed)

    @staticmethod
    def _existing(db: sqlite3.Connection, key: str, fingerprint: str) -> sqlite3.Row | None:
        row = db.execute("SELECT * FROM hg_capability_operations WHERE key=?", (key,)).fetchone()
        if row is not None and row["fingerprint"] != fingerprint:
            raise CapabilityError("idempotency_conflict")
        return row

    def execute(self, request: CapabilityRequest, *, lease: DecisionLease | None = None) -> CapabilityReceipt:
        request, registration, key, fingerprint = self._snapshot(request)
        until = time.monotonic() + self.maximum_wait_seconds
        with self.store.transaction() as db:
            existing = self._existing(db, key, fingerprint)
            if existing is not None:
                return self._receipt(request, existing, replayed=True)
            if control_status(db)["suspended"]:
                raise CapabilityError("capability_dispatch_suspended")
            if db.execute("SELECT COUNT(*) FROM hg_capability_operations").fetchone()[0] >= self.maximum_operations:
                raise CapabilityError("capability_receipt_capacity_exhausted")
            now = self._now()
            reason = self._denial(db, request, registration.spec, lease, now)
            operation_id = uuid.uuid4().hex
            db.execute("INSERT INTO hg_capability_operations "
                "(key,fingerprint,subject,operation_id,provider_id,argument_digest,state,reason,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)", (key, fingerprint,
                canonical_digest({"subject": request.subject}), operation_id,
                registration.provider_id, canonical_digest(dict(request.arguments)),
                "denied" if reason else "dispatching", reason or "dispatch_reserved", now))
            sequence = self._event(db, key, "denied" if reason else "prepared")
            db.execute("UPDATE hg_capability_operations SET prepared_sequence=?,completed_sequence=? WHERE key=?",
                       (None if reason else sequence, sequence if reason else None, key))
            if not reason:
                assert lease is not None
                db.execute("INSERT INTO hg_capability_leases VALUES(?,?)",
                           (canonical_digest({"lease": lease.lease_id}), key))
            row = self._existing(db, key, fingerprint)
        # COMMIT of intent, audit and consumed lease precedes ANY provider effect.
        if reason:
            return self._receipt(request, row)
        assert lease is not None

        def dispatch() -> ProviderObservation | None:
            # Recheck immediately before network admission; revocation committed
            # after this point cannot prove the remote effect was cancelled.
            with self.store.transaction() as db:
                current = self._existing(db, key, fingerprint)
                if current["state"] != "dispatching":
                    return None
                now = self._now()
                revoked = db.execute("SELECT 1 FROM hg_capability_revoked WHERE subject=?",
                                     (current["subject"],)).fetchone()
                if (control_status(db)["suspended"] or revoked
                        or now >= min(request.deadline, lease.expires_at) or time.monotonic() >= until):
                    self._finish(db, key, "failed", "dispatch_authority_expired", None, False)
                    return None
            checked_execute = getattr(registration.adapter, "execute_authorized", None)
            if checked_execute is not None:
                def authorize() -> None:
                    # Called after credential acquisition/TLS, immediately before
                    # the concrete mutation. Never hold the DB lock during I/O.
                    with self.store.transaction() as db:
                        current = self._existing(db, key, fingerprint)
                        if (current is None or current["state"] != "dispatching"
                                or control_status(db)["suspended"]
                                or db.execute("SELECT 1 FROM hg_capability_revoked WHERE subject=?",
                                              (current["subject"],)).fetchone()):
                            raise CapabilityError("capability_dispatch_fenced")
                        if (self._now() >= min(request.deadline, lease.expires_at)
                                or time.monotonic() >= until):
                            raise CapabilityError("capability_dispatch_expired")
                return checked_execute(request, operation_id, authorize=authorize)
            return registration.adapter.execute(request, operation_id)

        outcome = self._calls.run(dispatch, timeout_seconds=min(
            max(0.0, until - time.monotonic()),
            max(0.0, min(request.deadline, lease.expires_at) - self._now())))
        with self.store.transaction() as db:
            row = self._existing(db, key, fingerprint)
            if row["state"] not in _TERMINAL and row["reason"] != "provider_terminal_conflict":
                if outcome.state == "not_started":
                    self._finish(db, key, "failed", "dispatch_not_started", None, False)
                else:
                    self._observe(db, row, outcome.value if outcome.state == "completed" else None,
                                  reconciled=False)
            elif outcome.state == "completed":
                self._record_conflict(db, row, outcome.value)
            return self._receipt(request, self._existing(db, key, fingerprint))

    def _finish(self, db: sqlite3.Connection, key: str, state: str, reason: str,
                external_id: str | None, reconciled: bool) -> None:
        sequence = self._event(db, key, state)
        db.execute("UPDATE hg_capability_operations SET state=?,reason=?,external_id=COALESCE(?,external_id),"
                   "completed_sequence=?,reconciled=MAX(reconciled,?) WHERE key=?",
                   (state, reason, external_id, sequence, int(reconciled), key))

    def _observe(self, db: sqlite3.Connection, row: sqlite3.Row,
                 observation: object, *, reconciled: bool) -> None:
        valid = (isinstance(observation, ProviderObservation)
            and observation.operation_id == row["operation_id"]
            and observation.provider_id == row["provider_id"]
            and observation.argument_digest == row["argument_digest"]
            and isinstance(observation.disposition, str)
            and observation.disposition in {"applied", "not_applied", "unknown"}
            and type(observation.terminal) is bool
            and (observation.external_id is None or
                 (isinstance(observation.external_id, str) and _OPAQUE.fullmatch(observation.external_id)))
            and (row["external_id"] is None or observation.external_id in (None, row["external_id"])))
        state, reason, external_id = "indeterminate", "provider_observation_unavailable", None
        if valid:
            external_id = observation.external_id
            if observation.terminal and observation.disposition == "applied":
                state, reason = "succeeded", "provider_terminal_applied"
            elif observation.terminal and observation.disposition == "not_applied":
                state, reason = "failed", "provider_terminal_not_applied"
            else:
                reason = "provider_nonterminal_observation"
        self._finish(db, row["key"], state, reason, external_id, reconciled)

    def _record_conflict(self, db: sqlite3.Connection, row: sqlite3.Row, observation: object) -> None:
        # A late contradictory terminal observation is evidence of a broken
        # provider contract, not permission to erase an effect or dispatch again.
        if (isinstance(observation, ProviderObservation)
                and observation.operation_id == row["operation_id"]
                and observation.provider_id == row["provider_id"]
                and observation.argument_digest == row["argument_digest"]
                and observation.terminal is True
                and ((row["state"] == "failed" and observation.disposition == "applied")
                     or (row["state"] == "succeeded" and observation.disposition == "not_applied"))):
            self._finish(db, row["key"], "indeterminate", "provider_terminal_conflict", None, True)

    def reconcile(self, request: CapabilityRequest) -> CapabilityReceipt:
        request, registration, key, fingerprint = self._snapshot(request)
        with self.store.transaction() as db:
            row = self._existing(db, key, fingerprint)
            if row is None:
                raise CapabilityError("capability_operation_unknown")
            if row["reason"] == "provider_terminal_conflict":
                raise CapabilityError("capability_receipt_conflict")
            if row["state"] in _TERMINAL:
                return self._receipt(request, row, replayed=True)
            if row["readbacks"] >= self.maximum_readbacks:
                raise CapabilityError("capability_readback_capacity_exhausted")
            # Reserve before I/O: process death cannot restore the attempt budget.
            db.execute("UPDATE hg_capability_operations SET readbacks=readbacks+1 WHERE key=?", (key,))
        outcome = self._calls.run(lambda: registration.adapter.readback(
            request, row["operation_id"], row["external_id"]), timeout_seconds=self.maximum_wait_seconds)
        with self.store.transaction() as db:
            current = self._existing(db, key, fingerprint)
            if current["state"] not in _TERMINAL and current["reason"] != "provider_terminal_conflict":
                self._observe(db, current, outcome.value if outcome.state == "completed" else None,
                              reconciled=True)
            elif outcome.state == "completed":
                self._record_conflict(db, current, outcome.value)
            return self._receipt(request, self._existing(db, key, fingerprint))

    def revoke_subject(self, subject: str) -> None:
        """Persist exact subject denial, or suspend before reporting its failure.

        Preserve the existing capacity error API. It is raised only AFTER the
        fallback suspension transaction commits, never from inside that
        transaction. No new dispatch may proceed after failed emergency denial.
        Already-admitted remote effects and authorized readback remain truthful.
        """
        if not identifier(subject):
            raise CapabilityError("capability_subject_invalid")
        digest = canonical_digest({"subject": subject})
        reason = None
        with self.store.transaction() as db:
            state = control_status(db)
            if state["suspended"]:
                reason = state["reason"]
            elif db.execute("SELECT 1 FROM hg_capability_revoked WHERE subject=?", (digest,)).fetchone():
                return
            elif db.execute("SELECT COUNT(*) FROM hg_capability_revoked").fetchone()[0] >= self.maximum_operations:
                reason = suspend(db, "revocation_capacity")["reason"]
            else:
                try:
                    now = self._now()
                except Exception:
                    # No invented timestamp or private clock error is recorded.
                    reason = suspend(db, "clock_unavailable")["reason"]
                else:
                    db.execute("INSERT INTO hg_capability_revoked VALUES(?,?)", (digest, now))
        if reason is not None:
            code = ("capability_revocation_capacity_exhausted" if reason == "revocation_capacity"
                    else "capability_clock_invalid")
            raise CapabilityError(code)

    def suspension_status(self) -> dict[str, object]:
        """Local control-state snapshot, not a current request's execution lease."""
        with self.store.transaction() as db:
            return control_status(db)

    def pending(self, subject: str, *, limit: int = 100, after: str = "") -> list[dict[str, object]]:
        if (not identifier(subject) or type(limit) is not int or not 1 <= limit <= 100
                or not isinstance(after, str) or (after and not re.fullmatch(r"[0-9a-f]{32}", after))):
            raise CapabilityError("capability_inventory_query_invalid")
        with self.store.transaction() as db:
            rows = db.execute("SELECT operation_id,provider_id,state,reason,readbacks,created_at "
                "FROM hg_capability_operations WHERE subject=? AND state IN ('dispatching','indeterminate') "
                "AND operation_id>? ORDER BY operation_id LIMIT ?",
                (canonical_digest({"subject": subject}), after, limit)).fetchall()
        return [dict(row) for row in rows]
