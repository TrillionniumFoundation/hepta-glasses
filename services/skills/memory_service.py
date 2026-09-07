"""Authenticated product Memory service and remote-deletion reconciliation.

The underlying ``DurableMemoryStore`` owns ciphertext-only record custody.  This
module adds a server-side identity boundary, atomic/idempotent legacy migration,
subject-filtered deletion delivery and a local hash chain of exact terminal
remote receipts.  A local receipt is custody evidence, not proof from an
independent privacy authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from services.skills.durable_memory import (
    DurableMemoryConsent,
    DurableMemoryError,
    DurableMemoryRecord,
    DurableMemoryStore,
)

DEFAULT_AUDIENCE = "hepta-memory"
CONSENT_SCOPE = "memory.consent"
WRITE_SCOPE = "memory.write"
READ_SCOPE = "memory.read"
DELETE_SCOPE = "memory.delete"
MIGRATE_SCOPE = "memory.migrate"
RECONCILE_SCOPE = "memory.reconcile"
_MAX_TIME = 253_402_300_799
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_OPAQUE_IDENTIFIER = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.:-]{0,255}\Z")


class MemoryServiceError(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class MemoryPrincipal:
    subject: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    expires_at: int


class MemoryIdentityVerifier(Protocol):
    def verify(
        self, *, bearer_token: str, audience: str, required_scope: str
    ) -> MemoryPrincipal: ...


@dataclass(frozen=True)
class LegacyMemoryRecord:
    legacy_id: str
    purpose: str
    data_class: str
    value: str
    expires_at: int


@dataclass(frozen=True)
class MemoryDeletionReceipt:
    event_id: str
    subject: str
    memory_id: str
    disposition: str
    terminal: bool
    receipt_id: str
    observed_at: int


class MemoryDeletionSink(Protocol):
    def delete(
        self,
        *,
        event: dict[str, object],
        idempotency_key: str,
        timeout_seconds: float,
    ) -> MemoryDeletionReceipt: ...


class AuthenticatedMemoryService:
    def __init__(
        self,
        *,
        store: DurableMemoryStore,
        identity: MemoryIdentityVerifier,
        clock: Callable[[], int],
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        if (
            not isinstance(store, DurableMemoryStore)
            or not callable(getattr(identity, "verify", None))
            or not callable(clock)
            or type(audience) is not str
            or _IDENTIFIER.fullmatch(audience) is None
        ):
            raise MemoryServiceError("memory_service_configuration_invalid", 500)
        self.store = store
        self.identity = identity
        self.clock = clock
        self.audience = audience
        self._ensure_service_schema()

    def _ensure_service_schema(self) -> None:
        with self.store._tx():
            self.store.db.execute(
                "CREATE TABLE IF NOT EXISTS memory_migrations("
                "subject TEXT NOT NULL,legacy_id TEXT NOT NULL,memory_id TEXT NOT NULL "
                "UNIQUE,fingerprint TEXT NOT NULL,created_at INTEGER NOT NULL,"
                "PRIMARY KEY(subject,legacy_id))"
            )
            self.store.db.execute(
                "CREATE TABLE IF NOT EXISTS memory_remote_receipts("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT "
                "NULL,subject TEXT NOT NULL,memory_id TEXT NOT NULL,receipt_digest TEXT "
                "NOT NULL,previous_hash TEXT NOT NULL,chain_hash TEXT NOT NULL UNIQUE,"
                "observed_at INTEGER NOT NULL)"
            )
            self.store.db.execute(
                "CREATE TABLE IF NOT EXISTS memory_key_retirements("
                "subject TEXT NOT NULL,key_id TEXT NOT NULL,state TEXT NOT NULL CHECK(" 
                "state IN ('pending','acknowledged')),created_at INTEGER NOT NULL,"
                "PRIMARY KEY(subject,key_id))"
            )

    @staticmethod
    def _bearer(value: object) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise MemoryServiceError("memory_service_unauthorized", 401)
        token = value[7:]
        if (
            not 16 <= len(token.encode("utf-8")) <= 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in token)
        ):
            raise MemoryServiceError("memory_service_unauthorized", 401)
        return token

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise MemoryServiceError("memory_service_clock_invalid", 503) from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise MemoryServiceError("memory_service_clock_invalid", 503)
        return value

    @staticmethod
    def _identifier(value: object, code: str = "memory_service_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise MemoryServiceError(code)
        return value

    @staticmethod
    def _opaque_identifier(
        value: object, code: str = "memory_service_binding_invalid"
    ) -> str:
        if type(value) is not str or _OPAQUE_IDENTIFIER.fullmatch(value) is None:
            raise MemoryServiceError(code)
        return value

    def _principal(self, authorization: str | None, scope: str) -> MemoryPrincipal:
        token = self._bearer(authorization)
        try:
            principal = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=scope,
            )
        except Exception:
            raise MemoryServiceError("memory_service_unauthorized", 401) from None
        now = self._now()
        if (
            type(principal) is not MemoryPrincipal
            or _IDENTIFIER.fullmatch(principal.subject) is None
            or _IDENTIFIER.fullmatch(principal.session_id) is None
            or principal.audience != self.audience
            or type(principal.scopes) is not tuple
            or scope not in principal.scopes
            or type(principal.expires_at) is not int
            or principal.expires_at <= now
        ):
            raise MemoryServiceError("memory_service_unauthorized", 401)
        return principal

    @staticmethod
    def _map(error: DurableMemoryError) -> MemoryServiceError:
        status = 409 if error.code in {
            "durable_memory_consent_missing",
            "durable_memory_migration_conflict",
            "durable_memory_migration_duplicate",
        } else 403 if error.code in {
            "durable_memory_data_class_not_consented",
            "durable_memory_consent_invalid",
        } else 503 if error.code.endswith(("_failed", "_unavailable")) else 400
        return MemoryServiceError(error.code, status)

    def grant_consent(
        self,
        *,
        authorization: str | None,
        purpose: str,
        allowed_data_classes: Iterable[str],
        expires_at: int,
    ) -> None:
        principal = self._principal(authorization, CONSENT_SCOPE)
        if type(expires_at) is not int or type(expires_at) is bool:
            raise MemoryServiceError("memory_consent_invalid")
        bounded = min(expires_at, principal.expires_at)
        try:
            self.store.grant_consent(
                DurableMemoryConsent(
                    principal.subject,
                    self._identifier(purpose),
                    frozenset(allowed_data_classes),
                    bounded,
                )
            )
        except DurableMemoryError as error:
            raise self._map(error) from None

    def remember(
        self,
        *,
        authorization: str | None,
        purpose: str,
        data_class: str,
        value: str,
        ttl_seconds: int,
    ) -> DurableMemoryRecord:
        principal = self._principal(authorization, WRITE_SCOPE)
        now = self._now()
        if type(ttl_seconds) is not int or type(ttl_seconds) is bool or ttl_seconds < 1:
            raise MemoryServiceError("memory_value_invalid")
        ttl_seconds = min(ttl_seconds, principal.expires_at - now)
        if ttl_seconds < 1:
            raise MemoryServiceError("memory_service_unauthorized", 401)
        try:
            return self.store.remember(
                subject=principal.subject,
                purpose=self._identifier(purpose),
                data_class=data_class,
                value=value,
                ttl_seconds=ttl_seconds,
            )
        except DurableMemoryError as error:
            raise self._map(error) from None

    def search(
        self,
        *,
        authorization: str | None,
        purpose: str,
        data_classes: Iterable[str] = (),
    ) -> list[DurableMemoryRecord]:
        principal = self._principal(authorization, READ_SCOPE)
        try:
            return self.store.search(
                subject=principal.subject,
                purpose=self._identifier(purpose),
                data_classes=data_classes,
            )
        except DurableMemoryError as error:
            raise self._map(error) from None

    def export(self, *, authorization: str | None) -> list[dict[str, object]]:
        principal = self._principal(authorization, READ_SCOPE)
        try:
            return self.store.export(subject=principal.subject)
        except DurableMemoryError as error:
            raise self._map(error) from None

    def delete(self, *, authorization: str | None, memory_id: str) -> bool:
        principal = self._principal(authorization, DELETE_SCOPE)
        try:
            return self.store.delete(
                subject=principal.subject,
                memory_id=self._opaque_identifier(memory_id),
            )
        except DurableMemoryError as error:
            raise self._map(error) from None

    def revoke_purpose(
        self, *, authorization: str | None, purpose: str
    ) -> int:
        principal = self._principal(authorization, DELETE_SCOPE)
        try:
            return self.store.revoke_purpose(
                subject=principal.subject, purpose=self._identifier(purpose)
            )
        except DurableMemoryError as error:
            raise self._map(error) from None

    def delete_all(self, *, authorization: str | None) -> int:
        principal = self._principal(authorization, DELETE_SCOPE)
        try:
            return self.store.delete_all(subject=principal.subject)
        except DurableMemoryError as error:
            raise self._map(error) from None

    @staticmethod
    def _legacy_fingerprint(record: LegacyMemoryRecord) -> str:
        try:
            encoded = json.dumps(
                [
                    record.legacy_id,
                    record.purpose,
                    record.data_class,
                    record.value,
                    record.expires_at,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise MemoryServiceError("memory_migration_invalid") from None
        return hashlib.sha256(encoded).hexdigest()

    def migrate_legacy(
        self,
        *,
        authorization: str | None,
        records: Iterable[LegacyMemoryRecord],
    ) -> list[DurableMemoryRecord]:
        principal = self._principal(authorization, MIGRATE_SCOPE)
        try:
            snapshot = tuple(records)
        except TypeError:
            raise MemoryServiceError("memory_migration_invalid") from None
        if not snapshot or len(snapshot) > 10_000:
            raise MemoryServiceError("memory_migration_invalid")
        identifiers: set[str] = set()
        checked: list[tuple[LegacyMemoryRecord, str, str]] = []
        for record in snapshot:
            if type(record) is not LegacyMemoryRecord:
                raise MemoryServiceError("memory_migration_invalid")
            legacy_id = self._identifier(record.legacy_id, "memory_migration_invalid")
            if legacy_id in identifiers:
                raise MemoryServiceError("durable_memory_migration_duplicate", 409)
            identifiers.add(legacy_id)
            purpose = self._identifier(record.purpose, "memory_migration_invalid")
            if (
                type(record.value) is not str
                or not record.value
                or type(record.expires_at) is not int
                or type(record.expires_at) is bool
                or not self._now() < record.expires_at <= principal.expires_at
            ):
                raise MemoryServiceError("memory_migration_invalid")
            checked.append((record, purpose, self._legacy_fingerprint(record)))
        results: list[DurableMemoryRecord] = []
        try:
            with self.store._tx():
                now = self.store._now()
                self.store._purge_locked(now)
                if self.store.db.execute(
                    "SELECT COUNT(*) FROM memory_records"
                ).fetchone()[0] + len(checked) > self.store.maximum_records:
                    raise DurableMemoryError("durable_memory_capacity_exhausted")
                for record, purpose, fingerprint in checked:
                    migration = self.store.db.execute(
                        "SELECT * FROM memory_migrations WHERE subject=? AND legacy_id=?",
                        (principal.subject, record.legacy_id),
                    ).fetchone()
                    if migration is not None:
                        if migration["fingerprint"] != fingerprint:
                            raise DurableMemoryError("durable_memory_migration_conflict")
                        existing = self.store.db.execute(
                            "SELECT * FROM memory_records WHERE memory_id=?",
                            (migration["memory_id"],),
                        ).fetchone()
                        if existing is None:
                            raise DurableMemoryError("durable_memory_migration_conflict")
                        results.append(self.store._decode(existing))
                        continue
                    consent = self.store.db.execute(
                        "SELECT * FROM memory_consents WHERE subject=? AND purpose=?",
                        (principal.subject, purpose),
                    ).fetchone()
                    if consent is None or consent["expires_at"] <= now:
                        raise DurableMemoryError("durable_memory_consent_missing")
                    allowed = frozenset(json.loads(consent["classes"]))
                    classes = self.store._classes([record.data_class])
                    data_class = next(iter(classes))
                    if data_class not in allowed:
                        raise DurableMemoryError(
                            "durable_memory_data_class_not_consented"
                        )
                    expires_at = min(record.expires_at, consent["expires_at"])
                    if expires_at <= now:
                        raise DurableMemoryError("durable_memory_authority_expired")
                    memory_id = "legacy." + hashlib.sha256(
                        json.dumps(
                            [principal.subject, record.legacy_id],
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()[:32]
                    key_id = self.store._key_id(principal.subject)
                    raw = record.value.encode("utf-8")
                    if len(raw) > self.store.maximum_value_bytes:
                        raise DurableMemoryError("durable_memory_value_too_large")
                    aad = self.store._aad(
                        memory_id,
                        principal.subject,
                        purpose,
                        data_class,
                        now,
                        expires_at,
                    )
                    try:
                        ciphertext = self.store.cipher.encrypt(
                            subject=principal.subject,
                            key_id=key_id,
                            plaintext=raw,
                            aad=aad,
                        )
                    except Exception:
                        raise DurableMemoryError(
                            "durable_memory_encrypt_failed"
                        ) from None
                    digest = hashlib.sha256(raw).hexdigest()
                    self.store.db.execute(
                        "INSERT INTO memory_records VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            memory_id,
                            principal.subject,
                            purpose,
                            data_class,
                            bytes(ciphertext),
                            digest,
                            now,
                            expires_at,
                            key_id,
                        ),
                    )
                    self.store.db.execute(
                        "INSERT INTO memory_migrations VALUES(?,?,?,?,?)",
                        (
                            principal.subject,
                            record.legacy_id,
                            memory_id,
                            fingerprint,
                            now,
                        ),
                    )
                    results.append(
                        DurableMemoryRecord(
                            memory_id,
                            principal.subject,
                            purpose,
                            data_class,
                            record.value,
                            digest,
                            now,
                            expires_at,
                            key_id,
                        )
                    )
                final = self.store._final_time(now)
                if final >= principal.expires_at or any(
                    item.expires_at <= final for item in results
                ):
                    raise DurableMemoryError("durable_memory_authority_expired")
        except DurableMemoryError as error:
            raise self._map(error) from None
        return results

    def rotate_subject_key(self, *, authorization: str | None) -> int:
        principal = self._principal(authorization, WRITE_SCOPE)
        with self.store.lock:
            old_ids = {
                row[0]
                for row in self.store.db.execute(
                    "SELECT DISTINCT key_id FROM memory_records WHERE subject=?",
                    (principal.subject,),
                )
            }
        try:
            changed = self.store.rotate_subject_key(subject=principal.subject)
        except DurableMemoryError as error:
            raise self._map(error) from None
        with self.store._tx():
            now = self.store._now()
            current = self.store._key_id(principal.subject)
            for key_id in old_ids - {current}:
                self.store.db.execute(
                    "INSERT INTO memory_key_retirements VALUES(?,?,'pending',?) "
                    "ON CONFLICT(subject,key_id) DO NOTHING",
                    (principal.subject, key_id, now),
                )
        return changed

    def pending_key_retirements(
        self, *, authorization: str | None
    ) -> tuple[str, ...]:
        principal = self._principal(authorization, RECONCILE_SCOPE)
        with self.store.lock:
            return tuple(
                row[0]
                for row in self.store.db.execute(
                    "SELECT key_id FROM memory_key_retirements WHERE subject=? AND "
                    "state='pending' ORDER BY key_id",
                    (principal.subject,),
                )
            )

    def acknowledge_key_retirement(
        self, *, authorization: str | None, key_id: str
    ) -> None:
        principal = self._principal(authorization, RECONCILE_SCOPE)
        key_id = self._identifier(key_id)
        with self.store._tx():
            changed = self.store.db.execute(
                "UPDATE memory_key_retirements SET state='acknowledged' WHERE "
                "subject=? AND key_id=? AND state='pending'",
                (principal.subject, key_id),
            ).rowcount
            if changed != 1:
                raise MemoryServiceError("memory_key_retirement_unknown", 409)


class MemoryDeletionReconciler:
    def __init__(
        self,
        *,
        store: DurableMemoryStore,
        identity: MemoryIdentityVerifier,
        sink: MemoryDeletionSink,
        clock: Callable[[], int],
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        if not callable(getattr(sink, "delete", None)):
            raise MemoryServiceError("memory_deletion_sink_invalid", 500)
        self.service = AuthenticatedMemoryService(
            store=store, identity=identity, clock=clock, audience=audience
        )
        self.store = store
        self.sink = sink
        self.clock = clock

    def _events(self, subject: str, limit: int) -> list[dict[str, object]]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise MemoryServiceError("memory_deletion_page_invalid")
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT event_id,subject,memory_id,reason,created_at FROM "
                "memory_deletions WHERE subject=? AND state='pending' ORDER BY "
                "created_at,event_id LIMIT ?",
                (subject, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _receipt(value: object, event: dict[str, object], now: int) -> MemoryDeletionReceipt:
        if (
            type(value) is not MemoryDeletionReceipt
            or value.event_id != event["event_id"]
            or value.subject != event["subject"]
            or value.memory_id != event["memory_id"]
            or value.disposition != "deleted"
            or value.terminal is not True
            or _IDENTIFIER.fullmatch(value.receipt_id) is None
            or type(value.observed_at) is not int
            or not event["created_at"] <= value.observed_at <= now
        ):
            raise MemoryServiceError("memory_deletion_receipt_invalid", 503)
        return value

    def deliver(
        self,
        *,
        authorization: str | None,
        limit: int = 100,
        timeout_seconds: float = 8,
    ) -> int:
        principal = self.service._principal(authorization, RECONCILE_SCOPE)
        if (
            type(timeout_seconds) not in (int, float)
            or type(timeout_seconds) is bool
            or not 0.01 <= float(timeout_seconds) <= 60
        ):
            raise MemoryServiceError("memory_deletion_timeout_invalid")
        delivered = 0
        for event in self._events(principal.subject, limit):
            try:
                result = self.sink.delete(
                    event=dict(event),
                    idempotency_key=str(event["event_id"]),
                    timeout_seconds=float(timeout_seconds),
                )
            except Exception:
                raise MemoryServiceError(
                    "memory_deletion_indeterminate", 503
                ) from None
            now = self.service._now()
            receipt = self._receipt(result, event, now)
            body = json.dumps(
                [
                    receipt.event_id,
                    receipt.subject,
                    receipt.memory_id,
                    receipt.disposition,
                    receipt.receipt_id,
                    receipt.observed_at,
                ],
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
            receipt_digest = hashlib.sha256(body).hexdigest()
            with self.store._tx():
                current = self.store.db.execute(
                    "SELECT 1 FROM memory_deletions WHERE event_id=? AND subject=? "
                    "AND state='pending'",
                    (receipt.event_id, principal.subject),
                ).fetchone()
                if current is None:
                    raise MemoryServiceError("memory_deletion_custody_conflict", 409)
                previous = self.store.db.execute(
                    "SELECT chain_hash FROM memory_remote_receipts ORDER BY sequence "
                    "DESC LIMIT 1"
                ).fetchone()
                previous_hash = "" if previous is None else previous[0]
                chain_hash = hashlib.sha256(
                    (previous_hash + receipt_digest).encode("ascii")
                ).hexdigest()
                self.store.db.execute(
                    "INSERT INTO memory_remote_receipts(event_id,subject,memory_id,"
                    "receipt_digest,previous_hash,chain_hash,observed_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        receipt.event_id,
                        receipt.subject,
                        receipt.memory_id,
                        receipt_digest,
                        previous_hash,
                        chain_hash,
                        receipt.observed_at,
                    ),
                )
                self.store.db.execute(
                    "DELETE FROM memory_deletions WHERE event_id=? AND subject=? AND "
                    "state='pending'",
                    (receipt.event_id, principal.subject),
                )
            delivered += 1
        return delivered

    def verify_receipt_chain(self) -> int:
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT * FROM memory_remote_receipts ORDER BY sequence"
            ).fetchall()
            previous = ""
            for expected, row in enumerate(rows, start=1):
                if (
                    row["sequence"] != expected
                    or row["previous_hash"] != previous
                    or hashlib.sha256(
                        (previous + row["receipt_digest"]).encode("ascii")
                    ).hexdigest()
                    != row["chain_hash"]
                ):
                    raise MemoryServiceError("memory_receipt_chain_invalid", 503)
                previous = row["chain_hash"]
            return len(rows)
