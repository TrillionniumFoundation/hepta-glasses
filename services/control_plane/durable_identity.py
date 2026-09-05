"""Durable identity authority, not an HTTP authentication or attestation verifier.

Only authenticated service code may call admission methods. Proofs must have been
verified outside this store. Every final token admission rechecks its durable
subject/device/session authority. Revocation is terminal and is never deleted by
capacity management. See docs/development/DURABLE_IDENTITY.md.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from services.control_plane.durable_state import DurableDatabase, identifier, timestamp


class DurableIdentityError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(value: object, maximum: int = 256) -> str:
    if not identifier(value, maximum):
        raise DurableIdentityError("identity_binding_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise DurableIdentityError("identity_binding_invalid") from error
    return value


def _digest(value: object) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise DurableIdentityError("identity_digest_invalid")
    return value


def _ttl(value: object, ceiling: int) -> int:
    if type(value) is not int or not 1 <= value <= ceiling:
        raise DurableIdentityError("identity_ttl_invalid")
    return value


def _scopes(values: Iterable[str]) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)) or not 1 <= len(values) <= 32:
        raise DurableIdentityError("identity_scope_invalid")
    for value in values:
        _text(value, 128)
    result = tuple(sorted(set(values)))
    if len(result) != len(values):
        raise DurableIdentityError("identity_scope_duplicate")
    return result


def canonical_claims(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(dict(value), ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise DurableIdentityError("identity_claims_invalid") from error


@dataclass(frozen=True)
class EnrollmentChallenge:
    nonce: str
    subject: str
    device_id: str
    platform: str
    application_id: str
    signer_digest: str
    expires_at: int


class DurableIdentityStore:
    """Single-host SQLite store with cross-connection transactional admission.

    Clock and admission inputs belong to the authenticated control-plane service,
    not to arbitrary request JSON. No bearer tokens or raw proofs are stored.
    All tables are namespaced; the existing reference identity.py is unchanged.
    """
    CLAIM_FIELDS = frozenset({"iss", "aud", "sub", "device_id", "session_id",
                             "jti", "scope", "iat", "exp", "kid"})

    def __init__(self, path: str, *, issuer: str, allowed_scopes: Iterable[str],
                 maximum_rows: int = 100000, maximum_token_ttl: int = 900,
                 clock: Callable[[], int] | None = None):
        self.issuer = _text(issuer)
        self.allowed_scopes = frozenset(_scopes(allowed_scopes))
        if type(maximum_rows) is not int or not 1 <= maximum_rows <= 1000000:
            raise ValueError("identity_capacity_invalid")
        self.maximum_rows = maximum_rows
        self.maximum_token_ttl = _ttl(maximum_token_ttl, 900)
        self._clock = clock or (lambda: int(time.time()))
        self._storage = DurableDatabase(path)
        self.db, self.lock = self._storage.db, self._storage.lock
        try:
            with self._storage.transaction():
                self._storage.version("identity", 1)
                for statement in (
                    "CREATE TABLE IF NOT EXISTS identity_subjects(id TEXT PRIMARY KEY,state TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS identity_devices(id TEXT PRIMARY KEY,subject TEXT NOT NULL,"
                    "proof_digest TEXT NOT NULL,platform TEXT NOT NULL,application_id TEXT NOT NULL,"
                    "signer_digest TEXT NOT NULL,state TEXT NOT NULL,registered_at INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS identity_challenges(digest TEXT PRIMARY KEY,subject TEXT NOT NULL,"
                    "device_id TEXT NOT NULL,platform TEXT NOT NULL,application_id TEXT NOT NULL,"
                    "signer_digest TEXT NOT NULL,expires_at INTEGER NOT NULL,state TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS identity_sessions(id TEXT PRIMARY KEY,subject TEXT NOT NULL,"
                    "device_id TEXT NOT NULL,audience TEXT NOT NULL,scopes TEXT NOT NULL,"
                    "expires_at INTEGER NOT NULL,state TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS identity_tokens(id TEXT PRIMARY KEY,subject TEXT NOT NULL,"
                    "device_id TEXT NOT NULL,session_id TEXT NOT NULL,claims_digest TEXT NOT NULL,"
                    "expires_at INTEGER NOT NULL,state TEXT NOT NULL,signer_receipt TEXT)",
                    "CREATE TABLE IF NOT EXISTS identity_revocations(kind TEXT NOT NULL,id TEXT NOT NULL,"
                    "revoked_at INTEGER NOT NULL,PRIMARY KEY(kind,id))",
                    "CREATE TABLE IF NOT EXISTS identity_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "kind TEXT NOT NULL,id TEXT NOT NULL,created_at INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS identity_policy(id INTEGER PRIMARY KEY CHECK(id=1),"
                    "issuer TEXT NOT NULL,scopes TEXT NOT NULL,maximum_ttl INTEGER NOT NULL)",
                ):
                    self.db.execute(statement)
                policy = (self.issuer, json.dumps(sorted(self.allowed_scopes)), self.maximum_token_ttl)
                stored = self.db.execute("SELECT issuer,scopes,maximum_ttl FROM identity_policy WHERE id=1").fetchone()
                if stored is not None and tuple(stored) != policy:
                    raise DurableIdentityError("identity_policy_migration_required")
                self.db.execute("INSERT OR IGNORE INTO identity_policy VALUES(1,?,?,?)", policy)
                self._storage.mark_version("identity", 1)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._storage.close()

    def _now(self) -> int:
        now = self._clock()
        if not timestamp(now) or now > 253402214399:
            raise DurableIdentityError("identity_clock_invalid")
        return now

    def _capacity(self, table: str) -> None:
        # table is selected only by static internal call sites, never caller input.
        if self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= self.maximum_rows:
            raise DurableIdentityError("identity_capacity_exhausted")

    def _revoked(self, kind: str, value: str) -> bool:
        return self.db.execute("SELECT 1 FROM identity_revocations WHERE kind=? AND id=?",
                               (kind, value)).fetchone() is not None

    def _subject(self, subject: str) -> None:
        row = self.db.execute("SELECT state FROM identity_subjects WHERE id=?", (subject,)).fetchone()
        if row is None or row["state"] != "active" or self._revoked("subject", subject):
            raise DurableIdentityError("identity_subject_unavailable")

    def _device(self, subject: str, device: str) -> sqlite3.Row:
        self._subject(subject)
        row = self.db.execute("SELECT * FROM identity_devices WHERE id=?", (device,)).fetchone()
        if (row is None or row["subject"] != subject or row["state"] != "active"
                or self._revoked("device", device)):
            raise DurableIdentityError("identity_device_unavailable")
        return row

    def _session(self, subject: str, device: str, session: str, now: int) -> sqlite3.Row:
        self._device(subject, device)
        row = self.db.execute("SELECT * FROM identity_sessions WHERE id=?", (session,)).fetchone()
        if (row is None or row["subject"] != subject or row["device_id"] != device
                or row["state"] != "active" or row["expires_at"] <= now
                or self._revoked("session", session)):
            raise DurableIdentityError("identity_session_unavailable")
        return row

    def admit_subject(self, subject: str) -> None:
        """Authenticated identity-provider admission; not public account creation."""
        _text(subject)
        with self._storage.transaction():
            if self._revoked("subject", subject):
                raise DurableIdentityError("identity_subject_revoked")
            row = self.db.execute("SELECT state FROM identity_subjects WHERE id=?", (subject,)).fetchone()
            if row is None:
                self._capacity("identity_subjects")
                self.db.execute("INSERT INTO identity_subjects VALUES(?,'active')", (subject,))
            elif row["state"] != "active":
                raise DurableIdentityError("identity_subject_revoked")

    def challenge(self, *, subject: str, device_id: str, platform: str,
                  application_id: str, signer_digest: str, ttl_seconds: int = 120) -> EnrollmentChallenge:
        for value in (subject, device_id, application_id):
            _text(value)
        _digest(signer_digest)
        if platform not in ("android", "ios"):
            raise DurableIdentityError("identity_platform_invalid")
        ttl_seconds = _ttl(ttl_seconds, 300)
        nonce = secrets.token_urlsafe(32)
        with self._storage.transaction():
            now = self._now()
            self._subject(subject)
            if self._revoked("device", device_id):
                raise DurableIdentityError("identity_device_revoked")
            existing = self.db.execute("SELECT subject,state FROM identity_devices WHERE id=?", (device_id,)).fetchone()
            if existing and (existing["subject"] != subject or existing["state"] != "active"):
                raise DurableIdentityError("identity_device_binding_conflict")
            self._capacity("identity_challenges")
            self.db.execute("INSERT INTO identity_challenges VALUES(?,?,?,?,?,?,?,'issued')",
                            (hashlib.sha256(nonce.encode()).hexdigest(), subject, device_id, platform,
                             application_id, signer_digest, now + ttl_seconds))
        return EnrollmentChallenge(nonce, subject, device_id, platform, application_id,
                                   signer_digest, now + ttl_seconds)

    def accept_attestation(self, *, challenge: EnrollmentChallenge, proof_digest: str,
                           verification_receipt: str) -> dict[str, object]:
        """Called only AFTER a trusted platform verifier validates the exact challenge.

        A string receipt is an audit reference, not authentication of a proof.
        The production composition must use identity_authority.py, not expose
        this method as an endpoint that accepts a client's 'verified' boolean.
        """
        if not isinstance(challenge, EnrollmentChallenge):
            raise DurableIdentityError("identity_challenge_invalid")
        _text(challenge.nonce, 128)
        _digest(proof_digest)
        _text(verification_receipt)
        digest = hashlib.sha256(challenge.nonce.encode()).hexdigest()
        with self._storage.transaction():
            now = self._now()
            self._subject(challenge.subject)
            row = self.db.execute("SELECT * FROM identity_challenges WHERE digest=?", (digest,)).fetchone()
            expected = (challenge.subject, challenge.device_id, challenge.platform,
                        challenge.application_id, challenge.signer_digest, challenge.expires_at)
            if row is None or tuple(row[k] for k in (
                    "subject", "device_id", "platform", "application_id", "signer_digest", "expires_at")) != expected:
                raise DurableIdentityError("identity_challenge_binding_invalid")
            if row["state"] != "issued" or row["expires_at"] <= now:
                raise DurableIdentityError("identity_challenge_spent_or_expired")
            if self._revoked("device", challenge.device_id):
                raise DurableIdentityError("identity_device_revoked")
            device = self.db.execute("SELECT * FROM identity_devices WHERE id=?", (challenge.device_id,)).fetchone()
            if device is not None:
                binding = (device["subject"], device["platform"], device["application_id"], device["signer_digest"])
                if device["state"] != "active" or binding != expected[:1] + expected[2:5]:
                    raise DurableIdentityError("identity_device_binding_conflict")
                # Re-enrollment must not silently change identity proof. Use reviewed recovery.
                if device["proof_digest"] != proof_digest:
                    raise DurableIdentityError("identity_device_recovery_required")
            else:
                self._capacity("identity_devices")
                self.db.execute("INSERT INTO identity_devices VALUES(?,?,?,?,?,?,'active',?)",
                                (challenge.device_id, challenge.subject, proof_digest, challenge.platform,
                                 challenge.application_id, challenge.signer_digest, now))
            self.db.execute("UPDATE identity_challenges SET state='consumed' WHERE digest=?", (digest,))
            # Receipt is returned, not persisted with raw platform claims/proof material.
            return {"device_id": challenge.device_id, "subject": challenge.subject,
                    "proof_digest": proof_digest, "verification_receipt": verification_receipt,
                    "state": "active"}

    def create_session(self, *, subject: str, device_id: str, audience: str,
                       scopes: Iterable[str], ttl_seconds: int = 900) -> str:
        for value in (subject, device_id, audience):
            _text(value)
        normalized = _scopes(scopes)
        if not set(normalized) <= self.allowed_scopes:
            raise DurableIdentityError("identity_scope_not_allowed")
        ttl_seconds = _ttl(ttl_seconds, 86400)
        session_id = secrets.token_urlsafe(24)
        with self._storage.transaction():
            now = self._now()
            self._device(subject, device_id)
            self._capacity("identity_sessions")
            if self._revoked("session", session_id):
                raise DurableIdentityError("identity_generated_id_collision")
            self.db.execute("INSERT INTO identity_sessions VALUES(?,?,?,?,?,?,'active')",
                            (session_id, subject, device_id, audience, json.dumps(normalized), now + ttl_seconds))
        return session_id

    def prepare_token(self, *, subject: str, device_id: str, session_id: str,
                      audience: str, scopes: Iterable[str], key_id: str,
                      ttl_seconds: int = 300) -> dict[str, object]:
        for value in (subject, device_id, session_id, audience, key_id):
            _text(value)
        normalized = _scopes(scopes)
        ttl_seconds = _ttl(ttl_seconds, self.maximum_token_ttl)
        token_id = secrets.token_urlsafe(24)
        with self._storage.transaction():
            now = self._now()
            session = self._session(subject, device_id, session_id, now)
            if audience != session["audience"] or not set(normalized) <= set(json.loads(session["scopes"])):
                raise DurableIdentityError("identity_scope_or_audience_escalation")
            if now + ttl_seconds > session["expires_at"]:
                raise DurableIdentityError("identity_token_outlives_session")
            if self._revoked("token", token_id):
                raise DurableIdentityError("identity_generated_id_collision")
            claims = {"iss": self.issuer, "aud": audience, "sub": subject, "device_id": device_id,
                      "session_id": session_id, "jti": token_id, "scope": list(normalized),
                      "iat": now, "exp": now + ttl_seconds, "kid": key_id}
            self._capacity("identity_tokens")
            self.db.execute("INSERT INTO identity_tokens VALUES(?,?,?,?,?,?,'preparing',NULL)",
                            (token_id, subject, device_id, session_id,
                             hashlib.sha256(canonical_claims(claims)).hexdigest(), now + ttl_seconds))
        return claims

    def _claims(self, claims: Mapping[str, object], now: int) -> sqlite3.Row:
        if not isinstance(claims, dict) or set(claims) != self.CLAIM_FIELDS:
            raise DurableIdentityError("identity_claims_invalid")
        for field in self.CLAIM_FIELDS - {"iat", "exp", "scope"}:
            _text(claims[field])
        scopes = _scopes(claims["scope"])
        if (not timestamp(claims["iat"]) or not timestamp(claims["exp"])
                or not 0 < claims["exp"] - claims["iat"] <= self.maximum_token_ttl
                or claims["iat"] > now or claims["exp"] <= now or claims["iss"] != self.issuer):
            raise DurableIdentityError("identity_claim_time_or_issuer_invalid")
        session = self._session(claims["sub"], claims["device_id"], claims["session_id"], now)
        if (claims["aud"] != session["audience"] or claims["exp"] > session["expires_at"]
                or not set(scopes) <= set(json.loads(session["scopes"]))):
            raise DurableIdentityError("identity_scope_or_audience_escalation")
        row = self.db.execute("SELECT * FROM identity_tokens WHERE id=?", (claims["jti"],)).fetchone()
        if (row is None or self._revoked("token", claims["jti"])
                or row["claims_digest"] != hashlib.sha256(canonical_claims(claims)).hexdigest()
                or (row["subject"], row["device_id"], row["session_id"], row["expires_at"])
                   != (claims["sub"], claims["device_id"], claims["session_id"], claims["exp"])):
            raise DurableIdentityError("identity_token_binding_invalid")
        return row

    def commit_token(self, claims: dict[str, object], *, signer_receipt: str) -> None:
        """Recheck durable authority AFTER remote signing and local signature verification."""
        _text(signer_receipt)
        with self._storage.transaction():
            row = self._claims(claims, self._now())
            if row["state"] != "preparing":
                raise DurableIdentityError("identity_token_not_prepared")
            self.db.execute("UPDATE identity_tokens SET state='active',signer_receipt=? WHERE id=?",
                            (signer_receipt, claims["jti"]))

    def abandon_token(self, token_id: str) -> None:
        _text(token_id)
        with self._storage.transaction():
            self.db.execute("UPDATE identity_tokens SET state='indeterminate' WHERE id=? AND state='preparing'", (token_id,))

    def require_token(self, claims: dict[str, object], *, audience: str,
                       required_scopes: Iterable[str]) -> dict[str, object]:
        _text(audience)
        required = _scopes(required_scopes)
        # One transaction prevents a cross-connection revoke splitting reads.
        with self._storage.transaction():
            row = self._claims(claims, self._now())
            if row["state"] != "active":
                raise DurableIdentityError("identity_token_not_active")
            if claims["aud"] != audience or not set(required) <= set(claims["scope"]):
                raise DurableIdentityError("identity_token_insufficient")
            return json.loads(canonical_claims(claims))

    def revoke(self, kind: str, identity: str) -> int:
        """Tombstone even unknown IDs, before an in-flight registration can create them.

        Revocation is deliberately not constrained by admission capacity. It must
        remain possible when the store has reached its new-work limit.
        """
        if kind not in ("subject", "device", "session", "token"):
            raise DurableIdentityError("identity_revocation_kind_invalid")
        _text(identity)
        with self._storage.transaction():
            now = self._now()
            inserted = self.db.execute("INSERT OR IGNORE INTO identity_revocations VALUES(?,?,?)",
                                       (kind, identity, now)).rowcount
            if inserted:
                self.db.execute("INSERT INTO identity_events(kind,id,created_at) VALUES(?,?,?)", (kind, identity, now))
            if kind == "subject":
                self.db.execute("UPDATE identity_subjects SET state='revoked' WHERE id=?", (identity,))
                self.db.execute("UPDATE identity_devices SET state='revoked' WHERE subject=?", (identity,))
                self.db.execute("UPDATE identity_sessions SET state='revoked' WHERE subject=?", (identity,))
                self.db.execute("UPDATE identity_challenges SET state='revoked' WHERE subject=?", (identity,))
                self.db.execute("UPDATE identity_tokens SET state='revoked' WHERE subject=?", (identity,))
            elif kind == "device":
                self.db.execute("UPDATE identity_devices SET state='revoked' WHERE id=?", (identity,))
                self.db.execute("UPDATE identity_sessions SET state='revoked' WHERE device_id=?", (identity,))
                self.db.execute("UPDATE identity_challenges SET state='revoked' WHERE device_id=?", (identity,))
                self.db.execute("UPDATE identity_tokens SET state='revoked' WHERE device_id=?", (identity,))
            elif kind == "session":
                self.db.execute("UPDATE identity_sessions SET state='revoked' WHERE id=?", (identity,))
                self.db.execute("UPDATE identity_tokens SET state='revoked' WHERE session_id=?", (identity,))
            else:
                self.db.execute("UPDATE identity_tokens SET state='revoked' WHERE id=?", (identity,))
            return self.db.execute("SELECT seq FROM identity_events WHERE kind=? AND id=?", (kind, identity)).fetchone()[0]

    def events_after(self, sequence: int, *, limit: int = 100) -> list[dict[str, object]]:
        if (type(sequence) is not int or sequence < 0 or sequence > 9223372036854775807
                or type(limit) is not int or not 1 <= limit <= 1000):
            raise DurableIdentityError("identity_event_cursor_invalid")
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT seq,kind,id,created_at FROM identity_events WHERE seq>? ORDER BY seq LIMIT ?",
                (sequence, limit))]

    def pending_tokens(self, *, limit: int = 100) -> list[str]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise DurableIdentityError("identity_recovery_limit_invalid")
        with self.lock:
            return [row[0] for row in self.db.execute(
                "SELECT id FROM identity_tokens WHERE state IN ('preparing','indeterminate') ORDER BY id LIMIT ?", (limit,))]
