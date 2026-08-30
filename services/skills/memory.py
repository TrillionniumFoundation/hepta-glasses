"""User-approved, purpose-bound memory with export, expiry, and deletion."""

from __future__ import annotations

import hashlib
import secrets
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
    """In-memory reference implementation; production storage must be encrypted."""

    FORBIDDEN_CLASSES = frozenset({"secret", "raw_audio", "credential"})

    def __init__(
        self,
        *,
        clock: Callable[[], int],
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.clock = clock
        self.id_factory = id_factory or (lambda: secrets.token_urlsafe(16))
        self._consents: dict[tuple[str, str], MemoryConsent] = {}
        self._records: dict[str, MemoryRecord] = {}
        self.audit: list[dict[str, object]] = []

    def grant_consent(self, consent: MemoryConsent) -> None:
        now = self.clock()
        if consent.expires_at <= now or not consent.allowed_data_classes:
            raise MemoryError("memory_consent_invalid")
        if consent.allowed_data_classes & self.FORBIDDEN_CLASSES:
            raise MemoryError("memory_class_forbidden")
        key = (consent.subject, consent.purpose)
        previous = self._consents.get(key)
        self._consents[key] = consent

        deleted_count = 0
        clamped_count = 0
        for memory_id, record in list(self._records.items()):
            if (record.subject, record.purpose) != key:
                continue
            if record.data_class not in consent.allowed_data_classes:
                del self._records[memory_id]
                deleted_count += 1
            elif record.expires_at > consent.expires_at:
                self._records[memory_id] = replace(
                    record,
                    expires_at=consent.expires_at,
                )
                clamped_count += 1
        self._purge_ineligible(now)
        self.audit.append(
            {
                "allowed_data_classes": sorted(consent.allowed_data_classes),
                "clamped_count": clamped_count,
                "deleted_count": deleted_count,
                "event": (
                    "memory.consent_updated"
                    if previous is not None
                    else "memory.consent_granted"
                ),
                "expires_at": consent.expires_at,
                "purpose": consent.purpose,
                "subject": consent.subject,
            }
        )

    def remember(
        self,
        *,
        subject: str,
        purpose: str,
        data_class: str,
        value: str,
        ttl_seconds: int,
    ) -> MemoryRecord:
        now = self.clock()
        self._purge_ineligible(now)
        if not value or ttl_seconds < 1:
            raise MemoryError("memory_value_invalid")
        if data_class in self.FORBIDDEN_CLASSES:
            raise MemoryError("memory_class_forbidden")
        consent = self._consents.get((subject, purpose))
        if consent is None or consent.expires_at <= now:
            raise MemoryError("memory_consent_missing")
        if data_class not in consent.allowed_data_classes:
            raise MemoryError("memory_data_class_not_consented")
        expires_at = min(now + ttl_seconds, consent.expires_at)
        record = MemoryRecord(
            memory_id=self.id_factory(),
            subject=subject,
            purpose=purpose,
            data_class=data_class,
            value=value,
            value_digest=hashlib.sha256(value.encode("utf-8")).hexdigest(),
            created_at=now,
            expires_at=expires_at,
        )
        self._records[record.memory_id] = record
        self.audit.append(
            {
                "data_class": data_class,
                "event": "memory.created",
                "memory_id": record.memory_id,
                "purpose": purpose,
                "subject": subject,
                "value_digest": record.value_digest,
            }
        )
        return record

    def search(
        self,
        *,
        subject: str,
        purpose: str,
        data_classes: Iterable[str] = (),
    ) -> list[MemoryRecord]:
        now = self.clock()
        self._purge_ineligible(now)
        consent = self._consents.get((subject, purpose))
        if consent is None or consent.expires_at <= now:
            return []
        allowed = frozenset(data_classes)
        return sorted(
            [
                record
                for record in self._records.values()
                if record.subject == subject
                and record.purpose == purpose
                and record.data_class in consent.allowed_data_classes
                and (not allowed or record.data_class in allowed)
            ],
            key=lambda record: (record.created_at, record.memory_id),
        )

    def export(self, *, subject: str) -> list[dict[str, object]]:
        self._purge_ineligible(self.clock())
        return [
            {
                "created_at": record.created_at,
                "data_class": record.data_class,
                "expires_at": record.expires_at,
                "memory_id": record.memory_id,
                "purpose": record.purpose,
                "value": record.value,
            }
            for record in sorted(
                self._records.values(), key=lambda item: item.memory_id
            )
            if record.subject == subject
        ]

    def delete(self, *, subject: str, memory_id: str) -> bool:
        record = self._records.get(memory_id)
        if record is None or record.subject != subject:
            return False
        del self._records[memory_id]
        self.audit.append(
            {
                "event": "memory.deleted",
                "memory_id": memory_id,
                "subject": subject,
            }
        )
        return True

    def revoke_purpose(self, *, subject: str, purpose: str) -> int:
        self._consents.pop((subject, purpose), None)
        targets = [
            memory_id
            for memory_id, record in self._records.items()
            if record.subject == subject and record.purpose == purpose
        ]
        for memory_id in targets:
            del self._records[memory_id]
        self.audit.append(
            {
                "deleted_count": len(targets),
                "event": "memory.purpose_revoked",
                "purpose": purpose,
                "subject": subject,
            }
        )
        return len(targets)

    def delete_all(self, *, subject: str) -> int:
        targets = [
            memory_id
            for memory_id, record in self._records.items()
            if record.subject == subject
        ]
        for memory_id in targets:
            del self._records[memory_id]
        for key in [key for key in self._consents if key[0] == subject]:
            del self._consents[key]
        self.audit.append(
            {
                "deleted_count": len(targets),
                "event": "memory.subject_deleted",
                "subject": subject,
            }
        )
        return len(targets)

    def _purge_ineligible(self, now: int) -> None:
        for key, consent in list(self._consents.items()):
            if consent.expires_at <= now:
                del self._consents[key]
        for memory_id, record in list(self._records.items()):
            consent = self._consents.get((record.subject, record.purpose))
            if (
                record.expires_at <= now
                or consent is None
                or consent.expires_at <= now
                or record.data_class not in consent.allowed_data_classes
            ):
                del self._records[memory_id]
