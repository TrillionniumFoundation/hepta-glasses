"""Identity, device registration, revocation, and short-lived token contracts.

The implementation is dependency-free and suitable for deterministic tests and a
small control-plane service. Production deployments must inject keys from a KMS or
HSM; raw signing material never belongs in the mobile application or repository.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


class IdentityError(ValueError):
    """Stable fail-closed identity error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, base64.binascii.Error) as error:
        raise IdentityError("token_encoding_invalid") from error


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    subject: str
    attestation_digest: str
    status: str
    registered_at: int


class DeviceRegistry:
    """Authoritative binding with terminal lost/revoked state transitions."""

    VALID_STATUSES = {"active", "revoked", "lost"}
    TERMINAL_STATUSES = {"revoked", "lost"}

    def __init__(self) -> None:
        self._records: dict[str, DeviceRecord] = {}
        self._lock = threading.RLock()

    def register(
        self,
        *,
        device_id: str,
        subject: str,
        attestation_digest: str,
        now: int,
    ) -> DeviceRecord:
        if not device_id or not subject or not _is_sha256(attestation_digest):
            raise IdentityError("device_registration_invalid")
        with self._lock:
            existing = self._records.get(device_id)
            if existing is not None:
                if existing.subject != subject:
                    raise IdentityError("device_subject_conflict")
                if existing.status != "active":
                    raise IdentityError("device_reactivation_requires_recovery")
                if not hmac.compare_digest(
                    existing.attestation_digest, attestation_digest
                ):
                    raise IdentityError("device_attestation_conflict")
                return existing
            record = DeviceRecord(
                device_id=device_id,
                subject=subject,
                attestation_digest=attestation_digest,
                status="active",
                registered_at=now,
            )
            self._records[device_id] = record
            return record

    def set_status(self, device_id: str, status: str) -> DeviceRecord:
        if status not in self.VALID_STATUSES:
            raise IdentityError("device_status_invalid")
        with self._lock:
            current = self._records.get(device_id)
            if current is None:
                raise IdentityError("device_unknown")
            if current.status == status:
                return current
            if current.status in self.TERMINAL_STATUSES and status == "active":
                raise IdentityError("device_reactivation_requires_recovery")
            if current.status == "revoked":
                raise IdentityError("device_revocation_terminal")
            updated = DeviceRecord(
                device_id=current.device_id,
                subject=current.subject,
                attestation_digest=current.attestation_digest,
                status=status,
                registered_at=current.registered_at,
            )
            self._records[device_id] = updated
            return updated

    def require_active(self, *, device_id: str, subject: str) -> DeviceRecord:
        with self._lock:
            record = self._records.get(device_id)
            if record is None:
                raise IdentityError("device_unknown")
            if record.subject != subject:
                raise IdentityError("device_subject_mismatch")
            if record.status != "active":
                raise IdentityError(f"device_{record.status}")
            return record

    def get(self, device_id: str) -> DeviceRecord | None:
        with self._lock:
            return self._records.get(device_id)


@dataclass(frozen=True)
class AccessClaims:
    issuer: str
    subject: str
    audience: str
    device_id: str
    scopes: frozenset[str]
    issued_at: int
    expires_at: int
    token_id: str
    session_id: str
    key_id: str


class KeyRing:
    """Small key-id aware signing ring; production keys must come from a KMS."""

    def __init__(self, *, keys: Mapping[str, bytes], active_key_id: str) -> None:
        if active_key_id not in keys or not keys:
            raise IdentityError("active_signing_key_missing")
        if any(len(secret) < 32 for secret in keys.values()):
            raise IdentityError("signing_key_too_short")
        self._keys = dict(keys)
        self._active_key_id = active_key_id
        self._lock = threading.RLock()

    @property
    def active_key_id(self) -> str:
        with self._lock:
            return self._active_key_id

    def active_secret(self) -> bytes:
        with self._lock:
            return self._keys[self._active_key_id]

    def active_signer(self) -> tuple[str, bytes]:
        """Return one atomic key-id/secret snapshot for a signing operation."""
        with self._lock:
            return self._active_key_id, self._keys[self._active_key_id]

    def secret_for(self, key_id: str) -> bytes:
        with self._lock:
            try:
                return self._keys[key_id]
            except KeyError as error:
                raise IdentityError("signing_key_unknown") from error

    def rotate(self, *, key_id: str, secret: bytes, activate: bool = True) -> None:
        if not key_id or len(secret) < 32:
            raise IdentityError("signing_key_invalid")
        with self._lock:
            self._keys[key_id] = secret
            if activate:
                self._active_key_id = key_id

    def retire(self, key_id: str) -> None:
        with self._lock:
            if key_id == self._active_key_id:
                raise IdentityError("active_signing_key_cannot_retire")
            self._keys.pop(key_id, None)


class RevocationLedger:
    """Thread-safe token/session/device/subject revocation ledger."""

    def __init__(self) -> None:
        self._token_ids: set[str] = set()
        self._session_ids: set[str] = set()
        self._device_ids: set[str] = set()
        self._subjects: set[str] = set()
        self._lock = threading.RLock()

    def revoke_token(self, token_id: str) -> None:
        with self._lock:
            self._token_ids.add(token_id)

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._session_ids.add(session_id)

    def revoke_device(self, device_id: str) -> None:
        with self._lock:
            self._device_ids.add(device_id)

    def revoke_subject(self, subject: str) -> None:
        with self._lock:
            self._subjects.add(subject)

    def is_revoked(self, claims: AccessClaims) -> bool:
        with self._lock:
            return (
                claims.token_id in self._token_ids
                or claims.session_id in self._session_ids
                or claims.device_id in self._device_ids
                or claims.subject in self._subjects
            )


class SlidingWindowRateLimiter:
    """Deterministic per-key request limiter."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limiter values must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[int]] = defaultdict(deque)
        self._lock = threading.RLock()

    def consume(self, key: str, *, now: int) -> None:
        with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                raise IdentityError("rate_limit_exceeded")
            events.append(now)


class TokenService:
    """Issues and verifies compact HMAC tokens with exact device binding."""

    TOKEN_TYPE = "HGAT"

    def __init__(
        self,
        *,
        issuer: str,
        key_ring: KeyRing,
        devices: DeviceRegistry,
        revocations: RevocationLedger,
        maximum_ttl_seconds: int = 900,
        clock: Callable[[], int] | None = None,
        token_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not issuer or maximum_ttl_seconds < 1:
            raise ValueError("invalid token service configuration")
        self.issuer = issuer
        self.key_ring = key_ring
        self.devices = devices
        self.revocations = revocations
        self.maximum_ttl_seconds = maximum_ttl_seconds
        self._clock = clock or (lambda: int(time.time()))
        self._token_id_factory = token_id_factory or (lambda: secrets.token_urlsafe(18))

    def issue(
        self,
        *,
        subject: str,
        device_id: str,
        audience: str,
        scopes: Iterable[str],
        session_id: str,
        ttl_seconds: int,
        now: int | None = None,
    ) -> str:
        timestamp = self._clock() if now is None else now
        if ttl_seconds < 1 or ttl_seconds > self.maximum_ttl_seconds:
            raise IdentityError("token_ttl_invalid")
        if not audience or not session_id:
            raise IdentityError("token_binding_invalid")
        self.devices.require_active(device_id=device_id, subject=subject)
        normalized_scopes = sorted({scope for scope in scopes if scope})
        if not normalized_scopes:
            raise IdentityError("token_scope_empty")
        key_id, signing_secret = self.key_ring.active_signer()
        header = {
            "alg": "HS256",
            "kid": key_id,
            "typ": self.TOKEN_TYPE,
        }
        payload = {
            "aud": audience,
            "device_id": device_id,
            "exp": timestamp + ttl_seconds,
            "iat": timestamp,
            "iss": self.issuer,
            "jti": self._token_id_factory(),
            "scope": normalized_scopes,
            "session_id": session_id,
            "sub": subject,
        }
        encoded_header = _b64url_encode(_canonical_json(header))
        encoded_payload = _b64url_encode(_canonical_json(payload))
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(signing_secret, signing_input, hashlib.sha256).digest()
        return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"

    def verify(
        self,
        token: str,
        *,
        audience: str,
        required_scopes: Iterable[str] = (),
        now: int | None = None,
        maximum_clock_skew_seconds: int = 30,
    ) -> AccessClaims:
        timestamp = self._clock() if now is None else now
        parts = token.split(".")
        if len(parts) != 3:
            raise IdentityError("token_format_invalid")
        try:
            header = json.loads(_b64url_decode(parts[0]))
            payload = json.loads(_b64url_decode(parts[1]))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise IdentityError("token_json_invalid") from error
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise IdentityError("token_json_invalid")
        if header.get("alg") != "HS256" or header.get("typ") != self.TOKEN_TYPE:
            raise IdentityError("token_header_invalid")
        key_id = header.get("kid")
        if not isinstance(key_id, str):
            raise IdentityError("token_key_id_invalid")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        expected = hmac.new(
            self.key_ring.secret_for(key_id), signing_input, hashlib.sha256
        ).digest()
        supplied = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, supplied):
            raise IdentityError("token_signature_invalid")

        required = {
            "aud",
            "device_id",
            "exp",
            "iat",
            "iss",
            "jti",
            "scope",
            "session_id",
            "sub",
        }
        if set(payload) != required:
            raise IdentityError("token_claims_invalid")
        if payload["iss"] != self.issuer or payload["aud"] != audience:
            raise IdentityError("token_audience_invalid")
        if not isinstance(payload["iat"], int) or not isinstance(payload["exp"], int):
            raise IdentityError("token_time_invalid")
        if payload["iat"] > timestamp + maximum_clock_skew_seconds:
            raise IdentityError("token_not_yet_valid")
        if payload["exp"] <= timestamp:
            raise IdentityError("token_expired")
        if payload["exp"] - payload["iat"] > self.maximum_ttl_seconds:
            raise IdentityError("token_ttl_exceeds_policy")
        if not isinstance(payload["scope"], list) or not all(
            isinstance(scope, str) for scope in payload["scope"]
        ):
            raise IdentityError("token_scope_invalid")

        claims = AccessClaims(
            issuer=payload["iss"],
            subject=payload["sub"],
            audience=payload["aud"],
            device_id=payload["device_id"],
            scopes=frozenset(payload["scope"]),
            issued_at=payload["iat"],
            expires_at=payload["exp"],
            token_id=payload["jti"],
            session_id=payload["session_id"],
            key_id=key_id,
        )
        self.devices.require_active(
            device_id=claims.device_id, subject=claims.subject
        )
        if self.revocations.is_revoked(claims):
            raise IdentityError("token_revoked")
        missing = set(required_scopes) - claims.scopes
        if missing:
            raise IdentityError("token_scope_insufficient")
        return claims
