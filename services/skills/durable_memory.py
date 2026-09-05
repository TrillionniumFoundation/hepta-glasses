"""Encrypted durable Memory custody with explicit external per-subject keys.

The store never persists plaintext values or key material. A deployment-supplied
cipher owns actual key custody and authenticated encryption. Local deletion
outbox rows are propagation custody, not proof that another system deleted data.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from services.skills.durable_memory_schema import ensure_memory_schema


class DurableMemoryError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class MemoryCipher(Protocol):
    def current_key_id(self, *, subject: str) -> str: ...
    def encrypt(self, *, subject: str, key_id: str, plaintext: bytes, aad: bytes) -> bytes: ...
    def decrypt(self, *, subject: str, key_id: str, ciphertext: bytes, aad: bytes) -> bytes: ...


@dataclass(frozen=True)
class DurableMemoryConsent:
    subject: str
    purpose: str
    allowed_data_classes: frozenset[str]
    expires_at: int


@dataclass(frozen=True)
class DurableMemoryRecord:
    memory_id: str
    subject: str
    purpose: str
    data_class: str
    value: str
    value_digest: str
    created_at: int
    expires_at: int
    key_id: str


class DurableMemoryStore:
    VERSION = 1
    ALLOWED_CLASSES = frozenset({"public", "personal", "sensitive"})
    FORBIDDEN_CLASSES = frozenset({"secret", "raw_audio", "credential"})

    def __init__(self, path: str, *, cipher: MemoryCipher, clock: Callable[[], int],
                 maximum_records: int = 100000, maximum_value_bytes: int = 65536) -> None:
        if not isinstance(path, str) or not path or not callable(clock):
            raise ValueError("durable_memory_configuration_invalid")
        if type(maximum_records) is not int or not 1 <= maximum_records <= 1000000:
            raise ValueError("durable_memory_configuration_invalid")
        if type(maximum_value_bytes) is not int or not 1 <= maximum_value_bytes <= 1048576:
            raise ValueError("durable_memory_configuration_invalid")
        self.cipher = cipher
        self.clock = clock
        self.maximum_records = maximum_records
        self.maximum_value_bytes = maximum_value_bytes
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA secure_delete=ON")
        try:
            with self._tx():
                ensure_memory_schema(self.db, version=self.VERSION)
        except BaseException:
            self.db.close()
            raise

    class _Tx:
        def __init__(self, owner: "DurableMemoryStore") -> None: self.owner = owner
        def __enter__(self):
            self.owner.lock.acquire()
            try:
                self.owner.db.execute("BEGIN IMMEDIATE")
            except BaseException:
                # __exit__ is not invoked when __enter__ raises. Release the
                # process lock here so a transient SQLite lock error cannot
                # permanently deadlock this store for other threads.
                self.owner.lock.release()
                raise
            return self.owner.db
        def __exit__(self, typ, value, tb):
            try: self.owner.db.execute("ROLLBACK" if typ else "COMMIT")
            finally: self.owner.lock.release()
    def _tx(self): return self._Tx(self)
    def close(self) -> None: self.db.close()

    def _now(self) -> int:
        try: value = self.clock()
        except Exception: raise DurableMemoryError("durable_memory_clock_invalid") from None
        if type(value) is not int or not 0 <= value <= 253402300799:
            raise DurableMemoryError("durable_memory_clock_invalid")
        return value

    def _final_time(self, earliest: int) -> int:
        value = self._now()
        if value < earliest:
            raise DurableMemoryError("durable_memory_clock_rollback")
        return value

    @staticmethod
    def _binding(value: object, code: str = "durable_memory_binding_invalid") -> str:
        if type(value) is not str or not 1 <= len(value) <= 256 or not value.strip(): raise DurableMemoryError(code)
        return value

    def _classes(self, values: Iterable[str]) -> frozenset[str]:
        result = frozenset(values)
        if not result or result & self.FORBIDDEN_CLASSES or not result <= self.ALLOWED_CLASSES:
            raise DurableMemoryError("durable_memory_data_class_invalid")
        return result

    @staticmethod
    def _aad(memory_id: str, subject: str, purpose: str, data_class: str, created_at: int, expires_at: int) -> bytes:
        return json.dumps([memory_id, subject, purpose, data_class, created_at, expires_at], separators=(",", ":"), ensure_ascii=True).encode()

    def _key_id(self, subject: str) -> str:
        try: key_id = self.cipher.current_key_id(subject=subject)
        except Exception: raise DurableMemoryError("durable_memory_key_unavailable") from None
        return self._binding(key_id, "durable_memory_key_invalid")

    def grant_consent(self, consent: DurableMemoryConsent) -> None:
        subject, purpose = self._binding(consent.subject), self._binding(consent.purpose)
        classes = self._classes(consent.allowed_data_classes)
        if type(consent.expires_at) is not int or not 0 <= consent.expires_at <= 253402300799:
            raise DurableMemoryError("durable_memory_consent_invalid")
        with self._tx():
            now = self._now()  # sample after write-lock waiting
            if consent.expires_at <= now:
                raise DurableMemoryError("durable_memory_consent_invalid")
            self._purge_locked(now)
            self.db.execute("INSERT INTO memory_consents VALUES(?,?,?,?) ON CONFLICT(subject,purpose) DO UPDATE SET classes=excluded.classes,expires_at=excluded.expires_at", (subject, purpose, json.dumps(sorted(classes), separators=(",", ":")), consent.expires_at))
            for row in self.db.execute("SELECT memory_id,data_class,expires_at FROM memory_records WHERE subject=? AND purpose=?", (subject, purpose)).fetchall():
                if row["data_class"] not in classes: self._delete_locked(subject, row["memory_id"], "consent_narrowed", now)
                elif row["expires_at"] > consent.expires_at: self._rebind_expiry_locked(row["memory_id"], consent.expires_at)
            if self._final_time(now) >= consent.expires_at:
                raise DurableMemoryError("durable_memory_consent_invalid")

    def remember(self, *, subject: str, purpose: str, data_class: str, value: str, ttl_seconds: int) -> DurableMemoryRecord:
        subject, purpose = self._binding(subject), self._binding(purpose); data_class = next(iter(self._classes([data_class])))
        if type(value) is not str or not value or type(ttl_seconds) is not int or ttl_seconds < 1: raise DurableMemoryError("durable_memory_value_invalid")
        try: raw = value.encode("utf-8")
        except UnicodeError: raise DurableMemoryError("durable_memory_value_invalid") from None
        if len(raw) > self.maximum_value_bytes: raise DurableMemoryError("durable_memory_value_too_large")
        memory_id = secrets.token_urlsafe(18)
        with self._tx():
            now = self._now()  # sample after write-lock waiting
            self._purge_locked(now)
            consent = self.db.execute("SELECT * FROM memory_consents WHERE subject=? AND purpose=?", (subject, purpose)).fetchone()
            if consent is None or consent["expires_at"] <= now: raise DurableMemoryError("durable_memory_consent_missing")
            if data_class not in frozenset(json.loads(consent["classes"])): raise DurableMemoryError("durable_memory_data_class_not_consented")
            if self.db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] >= self.maximum_records: raise DurableMemoryError("durable_memory_capacity_exhausted")
            expires_at = min(now + ttl_seconds, consent["expires_at"]); key_id = self._key_id(subject)
            aad = self._aad(memory_id, subject, purpose, data_class, now, expires_at)
            try: ciphertext = self.cipher.encrypt(subject=subject, key_id=key_id, plaintext=raw, aad=aad)
            except Exception: raise DurableMemoryError("durable_memory_encrypt_failed") from None
            if not isinstance(ciphertext, (bytes, bytearray)) or not ciphertext: raise DurableMemoryError("durable_memory_encrypt_failed")
            if self._final_time(now) >= expires_at:
                raise DurableMemoryError("durable_memory_authority_expired")
            digest = hashlib.sha256(raw).hexdigest()
            self.db.execute("INSERT INTO memory_records VALUES(?,?,?,?,?,?,?,?,?)", (memory_id, subject, purpose, data_class, bytes(ciphertext), digest, now, expires_at, key_id))
            if self._final_time(now) >= expires_at:
                raise DurableMemoryError("durable_memory_authority_expired")
            return DurableMemoryRecord(memory_id, subject, purpose, data_class, value, digest, now, expires_at, key_id)

    def _decode(self, row: sqlite3.Row) -> DurableMemoryRecord:
        aad = self._aad(row["memory_id"], row["subject"], row["purpose"], row["data_class"], row["created_at"], row["expires_at"])
        try: raw = self.cipher.decrypt(subject=row["subject"], key_id=row["key_id"], ciphertext=bytes(row["ciphertext"]), aad=aad)
        except Exception: raise DurableMemoryError("durable_memory_decrypt_failed") from None
        if hashlib.sha256(raw).hexdigest() != row["value_digest"]: raise DurableMemoryError("durable_memory_integrity_invalid")
        try: value = raw.decode("utf-8")
        except UnicodeError: raise DurableMemoryError("durable_memory_integrity_invalid") from None
        return DurableMemoryRecord(row["memory_id"], row["subject"], row["purpose"], row["data_class"], value, row["value_digest"], row["created_at"], row["expires_at"], row["key_id"])

    def search(self, *, subject: str, purpose: str, data_classes: Iterable[str] = ()) -> list[DurableMemoryRecord]:
        subject, purpose = self._binding(subject), self._binding(purpose); requested = frozenset(data_classes)
        if requested and (requested & self.FORBIDDEN_CLASSES or not requested <= self.ALLOWED_CLASSES): raise DurableMemoryError("durable_memory_data_class_invalid")
        with self._tx():
            now = self._now(); self._purge_locked(now)
            consent = self.db.execute("SELECT * FROM memory_consents WHERE subject=? AND purpose=?", (subject, purpose)).fetchone()
            if consent is None: return []
            allowed = frozenset(json.loads(consent["classes"])); allowed = allowed & requested if requested else allowed
            records = [self._decode(row) for row in self.db.execute("SELECT * FROM memory_records WHERE subject=? AND purpose=? ORDER BY created_at,memory_id", (subject, purpose)).fetchall() if row["data_class"] in allowed]
            final = self._final_time(now)
            if final >= consent["expires_at"] or any(record.expires_at <= final for record in records):
                self._purge_locked(final)
                records = [record for record in records if record.expires_at > final and consent["expires_at"] > final]
            return records

    def export(self, *, subject: str) -> list[dict[str, object]]:
        subject = self._binding(subject)
        with self._tx():
            now = self._now(); self._purge_locked(now)
            rows = self.db.execute("SELECT * FROM memory_records WHERE subject=? ORDER BY memory_id", (subject,)).fetchall()
            records = list(map(self._decode, rows)); final = self._final_time(now)
            if any(record.expires_at <= final for record in records):
                self._purge_locked(final)
                records = [record for record in records if record.expires_at > final]
            return [{"memory_id": r.memory_id, "purpose": r.purpose, "data_class": r.data_class, "value": r.value, "created_at": r.created_at, "expires_at": r.expires_at} for r in records]

    def delete(self, *, subject: str, memory_id: str) -> bool:
        subject, memory_id = self._binding(subject), self._binding(memory_id)
        with self._tx(): return self._delete_locked(subject, memory_id, "user_delete", self._now())

    def revoke_purpose(self, *, subject: str, purpose: str) -> int:
        subject, purpose = self._binding(subject), self._binding(purpose)
        with self._tx():
            now = self._now(); ids = [r[0] for r in self.db.execute("SELECT memory_id FROM memory_records WHERE subject=? AND purpose=?", (subject, purpose))]
            for memory_id in ids: self._delete_locked(subject, memory_id, "purpose_revoked", now)
            self.db.execute("DELETE FROM memory_consents WHERE subject=? AND purpose=?", (subject, purpose)); return len(ids)

    def delete_all(self, *, subject: str) -> int:
        subject = self._binding(subject)
        with self._tx():
            now = self._now(); ids = [r[0] for r in self.db.execute("SELECT memory_id FROM memory_records WHERE subject=?", (subject,))]
            for memory_id in ids: self._delete_locked(subject, memory_id, "subject_deleted", now)
            self.db.execute("DELETE FROM memory_consents WHERE subject=?", (subject,)); return len(ids)

    def _delete_locked(self, subject: str, memory_id: str, reason: str, now: int) -> bool:
        row = self.db.execute("SELECT subject FROM memory_records WHERE memory_id=?", (memory_id,)).fetchone()
        if row is None or row[0] != subject: return False
        self.db.execute("DELETE FROM memory_records WHERE memory_id=?", (memory_id,))
        self.db.execute("INSERT INTO memory_deletions(event_id,subject,memory_id,reason,created_at,state) VALUES(?,?,?,?,?,'pending')", (secrets.token_urlsafe(18), subject, memory_id, reason, now)); return True

    def _purge_locked(self, now: int) -> None:
        for row in self.db.execute("SELECT memory_id,subject FROM memory_records WHERE expires_at<=?", (now,)).fetchall(): self._delete_locked(row["subject"], row["memory_id"], "expired", now)
        self.db.execute("DELETE FROM memory_consents WHERE expires_at<=?", (now,))

    def _rebind_expiry_locked(self, memory_id: str, expires_at: int) -> None:
        row = self.db.execute("SELECT * FROM memory_records WHERE memory_id=?", (memory_id,)).fetchone(); record = self._decode(row)
        aad = self._aad(row["memory_id"], row["subject"], row["purpose"], row["data_class"], row["created_at"], expires_at)
        try: ciphertext = self.cipher.encrypt(subject=row["subject"], key_id=row["key_id"], plaintext=record.value.encode(), aad=aad)
        except Exception: raise DurableMemoryError("durable_memory_encrypt_failed") from None
        self.db.execute("UPDATE memory_records SET ciphertext=?,expires_at=? WHERE memory_id=?", (bytes(ciphertext), expires_at, memory_id))

    def rotate_subject_key(self, *, subject: str) -> int:
        subject = self._binding(subject)
        with self._tx():
            current = self._key_id(subject)
            rows = self.db.execute("SELECT * FROM memory_records WHERE subject=? ORDER BY memory_id", (subject,)).fetchall(); changed = 0
            for row in rows:
                if row["key_id"] == current: continue
                record = self._decode(row); aad = self._aad(row["memory_id"], row["subject"], row["purpose"], row["data_class"], row["created_at"], row["expires_at"])
                try: ciphertext = self.cipher.encrypt(subject=subject, key_id=current, plaintext=record.value.encode(), aad=aad)
                except Exception: raise DurableMemoryError("durable_memory_encrypt_failed") from None
                self.db.execute("UPDATE memory_records SET ciphertext=?,key_id=? WHERE memory_id=?", (bytes(ciphertext), current, row["memory_id"])); changed += 1
            return changed

    def pending_deletions(self, *, after_seq: int = 0, limit: int = 100) -> list[dict[str, object]]:
        if type(after_seq) is not int or after_seq < 0 or type(limit) is not int or not 1 <= limit <= 1000: raise DurableMemoryError("durable_memory_deletion_page_invalid")
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT seq,event_id,subject,memory_id,reason,created_at FROM memory_deletions WHERE state='pending' AND seq>? ORDER BY seq LIMIT ?", (after_seq, limit)).fetchall()]

    def acknowledge_deletion(self, *, event_id: str) -> None:
        event_id = self._binding(event_id)
        with self._tx():
            if self.db.execute("UPDATE memory_deletions SET state='completed' WHERE event_id=? AND state='pending'", (event_id,)).rowcount != 1: raise DurableMemoryError("durable_memory_deletion_unknown")

    def storage_policy(self) -> dict[str, object]:
        return {"plaintext_values_persisted": False, "key_material_persisted": False, "external_backup_exclusion_required": True, "external_key_provider_required": True, "deletion_ack_is_external_fact": True}
