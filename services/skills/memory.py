"""Bounded process-memory reference store with atomic purpose/consent decisions.

Not encrypted persistent storage. The bounded metadata ring is diagnostic only,
not a durable audit trail. Trusted service ingress must authenticate the subject.
"""
from __future__ import annotations
import hashlib
import secrets
import threading
from dataclasses import dataclass, replace
from typing import Callable, Iterable


class MemoryError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MemoryConsent:
    subject: str
    purpose: str
    allowed_data_classes: frozenset[str]
    expires_at: int


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    subject: str
    purpose: str
    data_class: str
    value: str
    value_digest: str
    created_at: int
    expires_at: int


class MemoryStore:
    FORBIDDEN_CLASSES = frozenset({"secret", "raw_audio", "credential"})
    ALLOWED_CLASSES = frozenset({"public", "personal", "sensitive"})

    def __init__(self, *, clock: Callable[[], int], id_factory: Callable[[], str] | None = None,
                 maximum_records: int = 10000, maximum_value_bytes: int = 65536,
                 maximum_consents: int = 10000, maximum_audit_entries: int = 4096) -> None:
        for value in (maximum_records, maximum_value_bytes, maximum_consents, maximum_audit_entries):
            if type(value) is not int or value < 1:
                raise ValueError("memory bounds must be positive integers")
        self.clock = clock
        self.id_factory = id_factory or (lambda: secrets.token_urlsafe(16))
        self.maximum_records = maximum_records
        self.maximum_value_bytes = maximum_value_bytes
        self.maximum_consents = maximum_consents
        self.maximum_audit_entries = maximum_audit_entries
        self._consents: dict[tuple[str, str], MemoryConsent] = {}
        self._records: dict[str, MemoryRecord] = {}
        self.audit: list[dict[str, object]] = []
        self._lock = threading.RLock()

    @staticmethod
    def _binding(subject: str, purpose: str | None = None) -> None:
        for value in (subject,) if purpose is None else (subject, purpose):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise MemoryError("memory_binding_invalid")

    def _audit(self, event: str, **payload: object) -> None:
        self.audit.append({"event": event, **payload})
        del self.audit[:-self.maximum_audit_entries]

    def grant_consent(self, consent: MemoryConsent) -> None:
        self._binding(consent.subject, consent.purpose)
        if not isinstance(consent.allowed_data_classes, frozenset):
            raise MemoryError("memory_consent_invalid")
        if consent.allowed_data_classes & self.FORBIDDEN_CLASSES:
            raise MemoryError("memory_class_forbidden")
        if not consent.allowed_data_classes or not consent.allowed_data_classes.issubset(self.ALLOWED_CLASSES):
            raise MemoryError("memory_data_class_invalid")
        with self._lock:
            now = self.clock()
            if type(consent.expires_at) is not int or consent.expires_at <= now:
                raise MemoryError("memory_consent_invalid")
            self._purge_expired(now)
            key = (consent.subject, consent.purpose)
            if key not in self._consents and len(self._consents) >= self.maximum_consents:
                raise MemoryError("memory_consent_capacity_exhausted")
            self._consents[key] = consent
            removed = 0
            for memory_id, record in list(self._records.items()):
                if (record.subject, record.purpose) != key:
                    continue
                if record.data_class not in consent.allowed_data_classes:
                    del self._records[memory_id]
                    removed += 1
                else:
                    self._records[memory_id] = replace(record, expires_at=min(record.expires_at, consent.expires_at))
            self._audit("memory.consent_granted", purpose=consent.purpose, subject=consent.subject,
                        removed_count=removed)

    def remember(self, *, subject: str, purpose: str, data_class: str, value: str,
                 ttl_seconds: int) -> MemoryRecord:
        self._binding(subject, purpose)
        if (not isinstance(value, str) or not value or type(ttl_seconds) is not int or ttl_seconds < 1):
            raise MemoryError("memory_value_invalid")
        try:
            encoded = value.encode("utf-8")
        except UnicodeError as error:
            raise MemoryError("memory_value_invalid") from error
        if len(encoded) > self.maximum_value_bytes:
            raise MemoryError("memory_value_too_large")
        if data_class in self.FORBIDDEN_CLASSES:
            raise MemoryError("memory_class_forbidden")
        if data_class not in self.ALLOWED_CLASSES:
            raise MemoryError("memory_data_class_invalid")
        with self._lock:
            now = self.clock()
            self._purge_expired(now)
            consent = self._consents.get((subject, purpose))
            if consent is None or consent.expires_at <= now:
                raise MemoryError("memory_consent_missing")
            if data_class not in consent.allowed_data_classes:
                raise MemoryError("memory_data_class_not_consented")
            if len(self._records) >= self.maximum_records:
                raise MemoryError("memory_capacity_exhausted")
            memory_id = self.id_factory()
            if not isinstance(memory_id, str) or not memory_id or len(memory_id) > 256:
                raise MemoryError("memory_id_invalid")
            if memory_id in self._records:
                raise MemoryError("memory_id_conflict")
            record = MemoryRecord(memory_id, subject, purpose, data_class, value,
                hashlib.sha256(encoded).hexdigest(), now, min(now + ttl_seconds, consent.expires_at))
            self._records[record.memory_id] = record
            self._audit("memory.created", data_class=data_class, memory_id=record.memory_id,
                        purpose=purpose, subject=subject, value_digest=record.value_digest)
            return record

    def search(self, *, subject: str, purpose: str, data_classes: Iterable[str] = ()) -> list[MemoryRecord]:
        self._binding(subject, purpose)
        requested = frozenset(data_classes)
        if not requested.issubset(self.ALLOWED_CLASSES):
            raise MemoryError("memory_data_class_invalid")
        with self._lock:
            self._purge_expired(self.clock())
            consent = self._consents.get((subject, purpose))
            if consent is None:
                return []
            allowed = consent.allowed_data_classes if not requested else requested & consent.allowed_data_classes
            return sorted([record for record in self._records.values()
                if record.subject == subject and record.purpose == purpose and record.data_class in allowed],
                key=lambda record: (record.created_at, record.memory_id))

    def export(self, *, subject: str) -> list[dict[str, object]]:
        self._binding(subject)
        with self._lock:
            self._purge_expired(self.clock())
            return [{"created_at": record.created_at, "data_class": record.data_class,
                "expires_at": record.expires_at, "memory_id": record.memory_id,
                "purpose": record.purpose, "value": record.value}
                for record in sorted(self._records.values(), key=lambda item: item.memory_id)
                if record.subject == subject]

    def delete(self, *, subject: str, memory_id: str) -> bool:
        self._binding(subject)
        with self._lock:
            record = self._records.get(memory_id)
            if record is None or record.subject != subject:
                return False
            del self._records[memory_id]
            self._audit("memory.deleted", memory_id=memory_id, subject=subject)
            return True

    def revoke_purpose(self, *, subject: str, purpose: str) -> int:
        self._binding(subject, purpose)
        with self._lock:
            self._consents.pop((subject, purpose), None)
            targets = [memory_id for memory_id, record in self._records.items()
                       if record.subject == subject and record.purpose == purpose]
            for memory_id in targets:
                del self._records[memory_id]
            self._audit("memory.purpose_revoked", deleted_count=len(targets), purpose=purpose, subject=subject)
            return len(targets)

    def delete_all(self, *, subject: str) -> int:
        self._binding(subject)
        with self._lock:
            targets = [memory_id for memory_id, record in self._records.items() if record.subject == subject]
            for memory_id in targets:
                del self._records[memory_id]
            for key in [key for key in self._consents if key[0] == subject]:
                del self._consents[key]
            self._audit("memory.subject_deleted", deleted_count=len(targets), subject=subject)
            return len(targets)

    def _purge_expired(self, now: int) -> None:
        for key in [key for key, consent in self._consents.items() if consent.expires_at <= now]:
            del self._consents[key]
        for memory_id, record in list(self._records.items()):
            consent = self._consents.get((record.subject, record.purpose))
            if record.expires_at <= now or consent is None or record.data_class not in consent.allowed_data_classes:
                del self._records[memory_id]
