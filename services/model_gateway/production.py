"""Durable model request custody on a trusted local host, not an auth service.

Schema/API v2 rejects the unversioned predecessor instead of forgetting its
requests. Only the caller commits results; a late provider worker cannot commit.
Model answers never grant tool, device, or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from services.control_plane.bounded_calls import BoundedCalls
from services.control_plane.durable_state import DurableDatabase, deadline, timestamp

MAX_CONTEXT_BYTES = 32768
MAX_ANSWER_BYTES = 65536


class ModelExecutionError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fail(code: str) -> None:
    raise ModelExecutionError(code)


def identifier(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        fail("model_binding_invalid")
    return value


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def context_bytes(value: object) -> bytes:
    """Bound ordinary JSON before serialization; never invoke custom mappings."""
    if type(value) is not dict:
        fail("model_context_invalid")
    stack, remaining = [(value, 0)], 2048
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0 or depth > 8:
            fail("model_context_limit")
        if type(item) is dict:
            if len(item) > 256:
                fail("model_context_limit")
            for key, child in item.items():
                if type(key) is not str or not 1 <= len(key) <= 128:
                    fail("model_context_invalid")
                stack.append((child, depth + 1))
        elif type(item) is list:
            if len(item) > 256:
                fail("model_context_limit")
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if len(item) > MAX_CONTEXT_BYTES:
                fail("model_context_limit")
        elif type(item) is float:
            if not math.isfinite(item):
                fail("model_context_invalid")
        elif type(item) is int:
            if abs(item) > 9007199254740991:
                fail("model_context_invalid")
        elif item is not None and type(item) is not bool:
            fail("model_context_invalid")
    try:
        encoded = canonical(value)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ModelExecutionError("model_context_invalid") from None
    if len(encoded) > MAX_CONTEXT_BYTES:
        fail("model_context_limit")
    return encoded


@dataclass(frozen=True)
class ProviderResult:
    answer: str
    request_id: str
    receipt_id: str
    request_key: str


class ModelProvider(Protocol):
    def generate(self, *, question: str, context: Mapping[str, object], request_key: str,
                 timeout_seconds: float) -> ProviderResult: ...
    def reconcile(self, *, request_key: str, timeout_seconds: float) -> ProviderResult | None: ...


@dataclass(frozen=True)
class ModelReceipt:
    idempotency_key: str
    fingerprint: str
    subject: str
    session_id: str
    state: str
    answer_digest: str | None
    provider_request_id: str | None  # SHA-256, not an unfiltered provider string
    provider_receipt_id: str | None  # SHA-256, not an independent attestation
    expires_at: int
    readbacks: int
    delivery_revoked: bool
    remote_cancellation_confirmed: bool = False


class ProductionModelGateway:
    """Explicit host clock/provider binding; host authenticates every entry point.

    No automatic migration, implicit provider retries, plaintext answer cache,
    external cancellation confirmation, encryption, or privileged ingress.
    """
    def __init__(self, path: str, *, provider: ModelProvider, provider_binding: str,
                 clock: Callable[[], int], daily_request_limit: int = 1000,
                 maximum_question_chars: int = 8000, maximum_entries: int = 4096,
                 maximum_readbacks: int = 3, maximum_workers: int = 4) -> None:
        identifier(provider_binding)
        for value, maximum in ((daily_request_limit, 10000), (maximum_question_chars, 8000),
                               (maximum_entries, 10000), (maximum_readbacks, 8), (maximum_workers, 16)):
            if type(value) is not int or not 1 <= value <= maximum:
                fail("model_configuration_invalid")
        if not callable(clock) or any(not callable(getattr(provider, m, None)) for m in ("generate", "reconcile")):
            fail("model_configuration_invalid")
        if getattr(provider, "binding_id", provider_binding) != provider_binding:
            fail("model_provider_configuration_binding_mismatch")
        checked_generate = getattr(provider, "generate_authorized", None)
        if checked_generate is not None and not callable(checked_generate):
            fail("model_provider_configuration_invalid")
        self._provider, self.clock = provider, clock
        self._provider_binding = provider_binding
        self.daily_request_limit = daily_request_limit
        self.maximum_question_chars = maximum_question_chars
        self.maximum_entries, self.maximum_readbacks = maximum_entries, maximum_readbacks
        self._calls = BoundedCalls(maximum_workers)
        self.storage = DurableDatabase(path)
        self.db, self.lock = self.storage.db, self.storage.lock
        policy = canonical({"provider": provider_binding, "daily_requests": daily_request_limit,
                            "question_chars": maximum_question_chars, "entries": maximum_entries,
                            "readbacks": maximum_readbacks, "workers": maximum_workers})
        try:
            with self.storage.transaction() as db:
                unmarked = self.storage.version("model_gateway", 2)
                owned = ("requests", "revoked_sessions", "model_policy", "model_cancellations", "model_events")
                existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if unmarked and existing.intersection(owned):
                    fail("model_unversioned_migration_required")
                if not unmarked and not set(owned) <= existing:
                    fail("model_schema_integrity_invalid")
                if not unmarked and db.execute("SELECT COUNT(*) FROM model_policy WHERE id=1").fetchone()[0] != 1:
                    fail("model_schema_integrity_invalid")
                for statement in (
                    "CREATE TABLE IF NOT EXISTS model_policy(id INTEGER PRIMARY KEY CHECK(id=1),policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS requests(subject TEXT NOT NULL,idempotency_key TEXT NOT NULL,fingerprint TEXT NOT NULL,session_id TEXT NOT NULL,day INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN ('prepared','indeterminate','committed','cancelled')),expires_at INTEGER NOT NULL,request_key TEXT UNIQUE NOT NULL,claim TEXT NOT NULL,claim_until INTEGER NOT NULL,readbacks INTEGER NOT NULL,answer_digest TEXT,provider_request_id TEXT,provider_receipt_id TEXT,PRIMARY KEY(subject,idempotency_key))",
                    "CREATE TABLE IF NOT EXISTS revoked_sessions(subject TEXT NOT NULL,session_id TEXT NOT NULL,PRIMARY KEY(subject,session_id))",
                    "CREATE TABLE IF NOT EXISTS model_cancellations(subject TEXT NOT NULL,idempotency_key TEXT NOT NULL,PRIMARY KEY(subject,idempotency_key))",
                    "CREATE TABLE IF NOT EXISTS model_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,request_key TEXT NOT NULL,observed_at INTEGER NOT NULL)",
                    "CREATE INDEX IF NOT EXISTS model_quota ON requests(subject,day)",
                ):
                    db.execute(statement)
                old = db.execute("SELECT policy FROM model_policy WHERE id=1").fetchone()
                if old and bytes(old[0]) != policy:
                    fail("model_policy_migration_required")
                db.execute("INSERT OR IGNORE INTO model_policy VALUES(1,?,?,0)", (policy, self._now()))
                self.storage.mark_version("model_gateway", 2)
        except BaseException:
            self.storage.close()
            raise

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    @property
    def provider_binding(self) -> str:
        return self._provider_binding

    def _require_provider(self, expected: ModelProvider | None = None) -> None:
        if ((expected is not None and self.provider is not expected)
                or getattr(self.provider, "binding_id", self.provider_binding) != self.provider_binding):
            fail("model_provider_configuration_binding_mismatch")

    def close(self) -> None:
        self.storage.close()

    def _now(self) -> int:
        now = self.clock()
        if not timestamp(now):
            fail("model_clock_invalid")
        return now

    @contextmanager
    def _transaction(self, *, expiry: int | None = None, stop: float | None = None, denial: bool = False):
        with self.storage.transaction() as db:
            last = db.execute("SELECT last_time FROM model_policy WHERE id=1").fetchone()[0]
            now = last if denial else self._now()
            if now < last:
                fail("model_clock_rollback")
            yield db, now
            final = now if denial else self._now()
            if final < now:
                fail("model_clock_rollback")
            if expiry is not None and final >= expiry:
                fail("model_authority_expired")
            if stop is not None and time.monotonic() >= stop:
                fail("model_deadline_expired")
            db.execute("UPDATE model_policy SET last_time=? WHERE id=1", (final,))

    def _event(self, db, event: str, key: str, now: int) -> None:
        db.execute("INSERT INTO model_events(event,request_key,observed_at) VALUES(?,?,?)", (event, key, now))

    def _denied(self, db, subject: str, session: str, key: str) -> bool:
        return bool(db.execute("SELECT suspended FROM model_policy WHERE id=1").fetchone()[0]
                    or db.execute("SELECT 1 FROM revoked_sessions WHERE subject=? AND session_id=?", (subject, session)).fetchone()
                    or db.execute("SELECT 1 FROM model_cancellations WHERE subject=? AND idempotency_key=?", (subject, key)).fetchone())

    def _authority(self, db, subject: str, session: str, key: str, expiry: int, now: int) -> None:
        if self._denied(db, subject, session, key):
            fail("model_delivery_revoked")
        if now >= expiry:
            fail("model_authority_expired")

    def _receipt(self, db, row) -> ModelReceipt:
        return ModelReceipt(row["idempotency_key"], row["fingerprint"], row["subject"], row["session_id"],
                            row["state"], row["answer_digest"], row["provider_request_id"], row["provider_receipt_id"],
                            row["expires_at"], row["readbacks"], self._denied(db, row["subject"], row["session_id"], row["idempotency_key"]))

    def execute(self, *, subject: str, session_id: str, idempotency_key: str,
                question: str, context: Mapping[str, object], expires_at: int,
                timeout_seconds: float = 15) -> tuple[str, ModelReceipt]:
        for value in (subject, session_id, idempotency_key):
            identifier(value)
        if not deadline(timeout_seconds) or not timestamp(expires_at):
            fail("model_deadline_invalid")
        if type(question) is not str or not question.strip() or len(question) > self.maximum_question_chars:
            fail("model_question_invalid")
        encoded_context = context_bytes(context)
        try:
            fingerprint = digest(canonical({"question": question, "context": json.loads(encoded_context),
                "subject": subject, "session": session_id, "provider": self.provider_binding, "expires_at": expires_at}))
        except UnicodeError:
            raise ModelExecutionError("model_question_invalid") from None
        self._require_provider()
        provider = self.provider
        stop, claim = time.monotonic() + timeout_seconds, uuid.uuid4().hex
        with self._transaction(expiry=expires_at, stop=stop) as (db, now):
            self._authority(db, subject, session_id, idempotency_key, expires_at, now)
            if expires_at - now > 300:
                fail("model_authority_lifetime_invalid")
            row = db.execute("SELECT * FROM requests WHERE subject=? AND idempotency_key=?", (subject, idempotency_key)).fetchone()
            readback = row is not None
            until = min(expires_at, now + math.ceil(timeout_seconds) + 1)
            if row:
                if row["fingerprint"] != fingerprint:
                    fail("model_idempotency_conflict")
                if row["state"] == "committed":
                    fail("model_duplicate_committed")
                if row["state"] == "cancelled":
                    fail("model_delivery_revoked")
                if row["claim_until"] > now:
                    fail("model_request_in_progress")
                if row["readbacks"] >= self.maximum_readbacks:
                    fail("model_readback_budget_exhausted")
                request_key = row["request_key"]
                db.execute("UPDATE requests SET state='indeterminate',claim=?,claim_until=?,readbacks=readbacks+1 WHERE subject=? AND idempotency_key=?", (claim, until, subject, idempotency_key))
                self._event(db, "readback_reserved", request_key, now)
            else:
                if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= self.maximum_entries:
                    fail("model_capacity_exhausted")
                day = now // 86400
                if db.execute("SELECT COUNT(*) FROM requests WHERE subject=? AND day=?", (subject, day)).fetchone()[0] >= self.daily_request_limit:
                    fail("model_quota_exhausted")
                request_key = digest(canonical(["hepta-model-v2", subject, idempotency_key, fingerprint]))
                db.execute("INSERT INTO requests VALUES(?,?,?,?,?,'prepared',?,?,?,?,0,NULL,NULL,NULL)",
                           (subject, idempotency_key, fingerprint, session_id, day, expires_at, request_key, claim, until))
                self._event(db, "dispatch_reserved", request_key, now)

        def authorize() -> None:
            # Trusted transport invokes this after credential/TLS preparation,
            # immediately before sending prompt bytes. No provider I/O holds
            # this transaction. Re-check the original claim, never renew it.
            with self._transaction(expiry=expires_at, stop=stop) as (db, now):
                self._require_provider(provider)
                current = db.execute("SELECT claim,state FROM requests WHERE request_key=?", (request_key,)).fetchone()
                self._authority(db, subject, session_id, idempotency_key, expires_at, now)
                if current is None or current["claim"] != claim or current["state"] not in {"prepared", "indeterminate"}:
                    fail("model_attempt_fenced")

        def operation():
            authorize()
            remaining = stop - time.monotonic()
            if remaining <= 0:
                fail("model_deadline_expired")
            if readback:
                return provider.reconcile(request_key=request_key, timeout_seconds=remaining)
            checked_generate = getattr(provider, "generate_authorized", None)
            if checked_generate is not None:
                if not callable(checked_generate):
                    fail("model_provider_configuration_invalid")
                return checked_generate(question=question, context=json.loads(encoded_context),
                    request_key=request_key, timeout_seconds=remaining, authorize=authorize)
            # Legacy trusted adapters keep their previous pre-call guarantee;
            # they do not acquire post-credential admission checks implicitly.
            return provider.generate(question=question, context=json.loads(encoded_context),
                                     request_key=request_key, timeout_seconds=remaining)

        outcome = self._calls.run(operation, timeout_seconds=max(0.0, stop - time.monotonic()))
        if outcome.state != "completed" or outcome.value is None:
            self._uncertain(request_key, claim, release=outcome.state != "timeout")
            fail("model_effect_indeterminate")
        try:
            self._require_provider(provider)
            return self._commit(request_key, claim, outcome.value, stop, provider=provider)
        except BaseException:
            self._uncertain(request_key, claim, release=True)
            raise

    def _uncertain(self, key: str, claim: str, *, release: bool) -> None:
        # No provider payload/error text is persisted. Terminal denial wins any race.
        with self._transaction(denial=True) as (db, _):
            db.execute("UPDATE requests SET state='indeterminate',claim_until=CASE WHEN ? THEN 0 ELSE claim_until END WHERE request_key=? AND claim=? AND state IN ('prepared','indeterminate')", (release, key, claim))

    def _commit(self, key: str, claim: str, result: ProviderResult, stop: float, *,
                provider: ModelProvider) -> tuple[str, ModelReceipt]:
        if type(result) is not ProviderResult or result.request_key != key:
            fail("model_provider_binding_invalid")
        if type(result.answer) is not str or not result.answer.strip() or len(result.answer) > MAX_ANSWER_BYTES:
            fail("model_provider_response_invalid")
        try:
            answer = result.answer.encode("utf-8")
        except UnicodeError:
            raise ModelExecutionError("model_provider_response_invalid") from None
        if len(answer) > MAX_ANSWER_BYTES:
            fail("model_provider_response_invalid")
        for value in (result.request_id, result.receipt_id):
            identifier(value)
        # First lookup is only to obtain the persisted expiry; final authority is checked below.
        with self.storage.transaction() as db:
            row = db.execute("SELECT expires_at FROM requests WHERE request_key=?", (key,)).fetchone()
            if row is None:
                fail("model_attempt_fenced")
            expiry = row[0]
        with self._transaction(expiry=expiry, stop=stop) as (db, now):
            self._require_provider(provider)
            row = db.execute("SELECT * FROM requests WHERE request_key=?", (key,)).fetchone()
            if row is None or row["claim"] != claim or row["state"] not in {"prepared", "indeterminate"}:
                fail("model_attempt_fenced")
            self._authority(db, row["subject"], row["session_id"], row["idempotency_key"], row["expires_at"], now)
            db.execute("UPDATE requests SET state='committed',claim_until=0,answer_digest=?,provider_request_id=?,provider_receipt_id=? WHERE request_key=?",
                       (digest(answer), digest(result.request_id.encode()), digest(result.receipt_id.encode()), key))
            self._event(db, "committed", key, now)
            saved = db.execute("SELECT * FROM requests WHERE request_key=?", (key,)).fetchone()
            self._require_provider(provider)
            return result.answer, self._receipt(db, saved)

    def _deny(self, subject: str, target: str, *, session: bool) -> dict:
        identifier(subject)
        identifier(target)
        table, column = ("revoked_sessions", "session_id") if session else ("model_cancellations", "idempotency_key")
        with self._transaction(denial=True) as (db, now):
            if not db.execute(f"SELECT 1 FROM {table} WHERE subject=? AND {column}=?", (subject, target)).fetchone():
                count = sum(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("revoked_sessions", "model_cancellations"))
                if count >= self.maximum_entries:
                    if not db.execute("SELECT suspended FROM model_policy WHERE id=1").fetchone()[0]:
                        db.execute("UPDATE model_policy SET suspended=1 WHERE id=1")
                        self._event(db, "registry_suspended", "", now)
                else:
                    db.execute(f"INSERT INTO {table} VALUES(?,?)", (subject, target))
                    self._event(db, "session_revoked" if session else "request_cancelled", digest(canonical([subject, target])), now)
                db.execute(f"UPDATE requests SET state='cancelled',claim_until=0 WHERE subject=? AND {column}=? AND state IN ('prepared','indeterminate')", (subject, target))
            return {"local_delivery_revoked": True, "remote_cancellation_confirmed": False,
                    "registry_suspended": bool(db.execute("SELECT suspended FROM model_policy WHERE id=1").fetchone()[0])}

    def cancel(self, *, subject: str, idempotency_key: str) -> dict:
        return self._deny(subject, idempotency_key, session=False)

    def revoke_session(self, session_id: str, *, subject: str) -> dict:
        return self._deny(subject, session_id, session=True)

    def status(self, *, subject: str, idempotency_key: str) -> ModelReceipt:
        identifier(subject)
        identifier(idempotency_key)
        with self._transaction(denial=True) as (db, _):
            row = db.execute("SELECT * FROM requests WHERE subject=? AND idempotency_key=?", (subject, idempotency_key)).fetchone()
            if row is None:
                fail("model_request_unknown")
            return self._receipt(db, row)

    def recoverable(self, *, subject: str, limit: int = 100) -> tuple[ModelReceipt, ...]:
        identifier(subject)
        if type(limit) is not int or not 1 <= limit <= 100:
            fail("model_inventory_limit_invalid")
        with self._transaction(denial=True) as (db, _):
            return tuple(self._receipt(db, row) for row in db.execute(
                "SELECT * FROM requests WHERE subject=? AND state IN ('prepared','indeterminate') ORDER BY idempotency_key LIMIT ?", (subject, limit)))
