"""Durable speech bootstrap custody; no raw audio or transcript persistence."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


MAX_TIME = 253402300799


class SpeechGatewayError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _identifier(value: object, *, maximum: int = 128) -> str:
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None):
        raise SpeechGatewayError("speech_binding_invalid")
    return value


def _deadline(value: object) -> float:
    if type(value) not in (int, float) or type(value) is bool or not 0 < value <= 60:
        raise SpeechGatewayError("speech_deadline_invalid")
    return float(value)


@dataclass(frozen=True)
class ProviderSpeechTicket:
    endpoint: str
    bearer_token: str
    provider: str
    provider_ticket_id: str
    expires_at: int
    maximum_audio_bytes: int


class SpeechProviderBroker(Protocol):
    def mint_ticket(self, *, subject: str, session_id: str, locale: str,
                    audio_format: str, maximum_audio_bytes: int, expires_at: int,
                    timeout_seconds: float) -> ProviderSpeechTicket: ...
    def revoke_session(self, *, session_id: str, timeout_seconds: float) -> None: ...


@dataclass(frozen=True)
class SpeechBootstrap:
    bootstrap_id: str
    session_id: str
    generation: int
    pair_identity: str
    locale: str
    endpoint: str
    bearer_token: str
    provider: str
    expires_at: int
    maximum_audio_bytes: int


class ProductionSpeechGateway:
    """Host-clocked one-shot speech bootstrap reservation and revocation fence.

    The broker is trusted server-side code. This class does not authenticate the
    account, stream audio, implement ASR readback, or prove remote deletion.
    """
    AUDIO_FORMAT = "pcm_s16le_16000_mono"

    def __init__(self, path: str, *, broker: SpeechProviderBroker,
                 provider_binding: str, clock: Callable[[], int],
                 maximum_session_bytes: int = 960000,
                 ticket_ttl_seconds: int = 90, daily_limit: int = 200):
        _identifier(provider_binding)
        if (type(maximum_session_bytes) is not int or not 3200 <= maximum_session_bytes <= 16_000_000
                or type(ticket_ttl_seconds) is not int or not 1 <= ticket_ttl_seconds <= 300
                or type(daily_limit) is not int or not 1 <= daily_limit <= 10_000
                or not callable(clock)
                or not callable(getattr(broker, "mint_ticket", None))
                or not callable(getattr(broker, "revoke_session", None))):
            raise ValueError("speech_configuration_invalid")
        if getattr(broker, "binding_id", provider_binding) != provider_binding:
            raise SpeechGatewayError("speech_provider_binding_mismatch")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        for pragma in ("PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL"):
            self.db.execute(pragma)
        self.broker = broker
        self.provider_binding = provider_binding
        self.clock = clock
        self.maximum_session_bytes = maximum_session_bytes
        self.ticket_ttl_seconds = ticket_ttl_seconds
        self.daily_limit = daily_limit
        self.lock = threading.RLock()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS bootstraps(bootstrap_digest TEXT PRIMARY KEY,"
            "subject TEXT NOT NULL,session_id TEXT NOT NULL,generation INTEGER NOT NULL,"
            "pair_digest TEXT NOT NULL,locale TEXT NOT NULL,provider TEXT NOT NULL,"
            "provider_ticket_digest TEXT NOT NULL,expires_at INTEGER NOT NULL,state TEXT NOT NULL,day INTEGER NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS revoked_sessions(session_id TEXT PRIMARY KEY,revoked_at INTEGER NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS speech_session_state ON bootstraps(session_id,state)")

    def close(self) -> None:
        self.db.close()

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise SpeechGatewayError("speech_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= MAX_TIME:
            raise SpeechGatewayError("speech_clock_invalid")
        return value

    def _begin(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")

    def _broker_ok(self) -> None:
        if getattr(self.broker, "binding_id", self.provider_binding) != self.provider_binding:
            raise SpeechGatewayError("speech_provider_binding_mismatch")

    def _validate_ticket(self, ticket: object, *, now: int, requested_expiry: int) -> ProviderSpeechTicket:
        if type(ticket) is not ProviderSpeechTicket:
            raise SpeechGatewayError("speech_provider_ticket_invalid")
        if (type(ticket.endpoint) is not str or not ticket.endpoint.startswith("https://")
                or type(ticket.bearer_token) is not str or not 1 <= len(ticket.bearer_token) <= 8192
                or any(ord(c) <= 32 or ord(c) == 127 for c in ticket.bearer_token)
                or _identifier(ticket.provider) != self.provider_binding
                or not _identifier(ticket.provider_ticket_id)
                or type(ticket.expires_at) is not int or type(ticket.expires_at) is bool
                or not now < ticket.expires_at <= requested_expiry
                or type(ticket.maximum_audio_bytes) is not int or type(ticket.maximum_audio_bytes) is bool
                or not 1 <= ticket.maximum_audio_bytes <= self.maximum_session_bytes):
            raise SpeechGatewayError("speech_provider_ticket_invalid")
        return ticket

    def bootstrap(self, *, subject: str, session_id: str, generation: int,
                  pair_identity: str, locale: str,
                  timeout_seconds: float = 8) -> SpeechBootstrap:
        for value in (subject, session_id, pair_identity):
            _identifier(value)
        if type(generation) is not int or type(generation) is bool or generation < 1:
            raise SpeechGatewayError("speech_binding_invalid")
        if (type(locale) is not str or not 1 <= len(locale) <= 64
                or re.fullmatch(r"[A-Za-z0-9-]+", locale) is None):
            raise SpeechGatewayError("speech_binding_invalid")
        timeout_seconds = _deadline(timeout_seconds)
        now = self._now()
        expiry = now + self.ticket_ttl_seconds
        if expiry > MAX_TIME:
            raise SpeechGatewayError("speech_ticket_expiry_invalid")
        # token_urlsafe may begin with '-' or '_', while bootstrap IDs are part
        # of the strict identifier contract. A fixed alphanumeric prefix makes
        # every generated identifier valid without reducing token entropy.
        bootstrap_id = "b-" + secrets.token_urlsafe(24)
        digest = hashlib.sha256(bootstrap_id.encode()).hexdigest()
        pair_digest = hashlib.sha256(pair_identity.encode()).hexdigest()
        day = now // 86400

        # Reserve before broker work so revocation and quota races have durable
        # local state. Empty provider fields are never returned as authority.
        with self.lock:
            self._begin()
            try:
                if self.db.execute("SELECT 1 FROM revoked_sessions WHERE session_id=?", (session_id,)).fetchone():
                    raise SpeechGatewayError("speech_session_revoked")
                if self.db.execute(
                    "SELECT 1 FROM bootstraps WHERE session_id=? AND state IN ('minting','indeterminate') LIMIT 1",
                    (session_id,),).fetchone():
                    raise SpeechGatewayError("speech_bootstrap_recovery_required")
                count = self.db.execute(
                    "SELECT COUNT(*) FROM bootstraps WHERE subject=? AND day=?", (subject, day)).fetchone()[0]
                if count >= self.daily_limit:
                    raise SpeechGatewayError("speech_quota_exhausted")
                self.db.execute(
                    "INSERT INTO bootstraps VALUES(?,?,?,?,?,?,'','',?,'minting',?)",
                    (digest, subject, session_id, generation, pair_digest, locale, expiry, day))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

        try:
            self._broker_ok()
            ticket = self.broker.mint_ticket(
                subject=subject, session_id=session_id, locale=locale,
                audio_format=self.AUDIO_FORMAT,
                maximum_audio_bytes=self.maximum_session_bytes,
                expires_at=expiry, timeout_seconds=timeout_seconds)
            fresh = self._now()
            ticket = self._validate_ticket(ticket, now=fresh, requested_expiry=expiry)
        except BaseException:
            with self.lock:
                self._begin()
                try:
                    self.db.execute(
                        "UPDATE bootstraps SET state='indeterminate' WHERE bootstrap_digest=? AND state='minting'",
                        (digest,))
                    self.db.execute("COMMIT")
                except BaseException:
                    self.db.execute("ROLLBACK")
                    raise
            raise

        revoked_after_mint = False
        with self.lock:
            self._begin()
            try:
                self._broker_ok()
                row = self.db.execute(
                    "SELECT state,session_id,generation,pair_digest FROM bootstraps WHERE bootstrap_digest=?",
                    (digest,),).fetchone()
                if row is None or row["session_id"] != session_id or row["generation"] != generation or row["pair_digest"] != pair_digest:
                    raise SpeechGatewayError("speech_bootstrap_invalid")
                if self.db.execute("SELECT 1 FROM revoked_sessions WHERE session_id=?", (session_id,)).fetchone() or row["state"] == "revoked":
                    revoked_after_mint = True
                    self.db.execute("UPDATE bootstraps SET state='revoked' WHERE bootstrap_digest=?", (digest,))
                elif row["state"] != "minting":
                    raise SpeechGatewayError("speech_bootstrap_recovery_required")
                else:
                    final_now = self._now()
                    if final_now >= ticket.expires_at:
                        self.db.execute("UPDATE bootstraps SET state='indeterminate' WHERE bootstrap_digest=?", (digest,))
                        raise SpeechGatewayError("speech_provider_ticket_expired")
                    self.db.execute(
                        "UPDATE bootstraps SET provider=?,provider_ticket_digest=?,expires_at=?,state='issued' "
                        "WHERE bootstrap_digest=? AND state='minting'",
                        (ticket.provider, hashlib.sha256(ticket.provider_ticket_id.encode()).hexdigest(),
                         ticket.expires_at, digest))
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

        if revoked_after_mint:
            # The earlier revoke may have raced ahead of mint completion. Revoke
            # again after the late ticket is known to exist; broker must be idempotent.
            try:
                self._broker_ok()
                self.broker.revoke_session(session_id=session_id, timeout_seconds=timeout_seconds)
            except BaseException:
                raise SpeechGatewayError("speech_remote_revoke_pending") from None
            raise SpeechGatewayError("speech_session_revoked")
        return SpeechBootstrap(
            bootstrap_id, session_id, generation, pair_identity, locale,
            ticket.endpoint, ticket.bearer_token, ticket.provider,
            ticket.expires_at, ticket.maximum_audio_bytes)

    def consume(self, bootstrap_id: str, *, session_id: str, generation: int,
                pair_identity: str) -> None:
        _identifier(bootstrap_id, maximum=512)
        _identifier(session_id)
        _identifier(pair_identity)
        if type(generation) is not int or type(generation) is bool or generation < 1:
            raise SpeechGatewayError("speech_binding_invalid")
        digest = hashlib.sha256(bootstrap_id.encode()).hexdigest()
        pair_digest = hashlib.sha256(pair_identity.encode()).hexdigest()
        with self.lock:
            self._begin()
            try:
                row = self.db.execute("SELECT * FROM bootstraps WHERE bootstrap_digest=?", (digest,)).fetchone()
                if (not row or row["session_id"] != session_id or row["generation"] != generation
                        or row["pair_digest"] != pair_digest):
                    raise SpeechGatewayError("speech_bootstrap_invalid")
                if self.db.execute("SELECT 1 FROM revoked_sessions WHERE session_id=?", (session_id,)).fetchone():
                    self.db.execute("UPDATE bootstraps SET state='revoked' WHERE bootstrap_digest=?", (digest,))
                    raise SpeechGatewayError("speech_session_revoked")
                if row["state"] != "issued":
                    raise SpeechGatewayError("speech_bootstrap_replayed")
                now = self._now()
                if row["expires_at"] <= now:
                    raise SpeechGatewayError("speech_bootstrap_expired")
                self.db.execute("UPDATE bootstraps SET state='consumed' WHERE bootstrap_digest=?", (digest,))
                if self._now() >= row["expires_at"]:
                    raise SpeechGatewayError("speech_bootstrap_expired")
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def revoke_session(self, session_id: str, *, timeout_seconds: float = 5) -> None:
        _identifier(session_id)
        timeout_seconds = _deadline(timeout_seconds)
        now = self._now()
        with self.lock:
            self._begin()
            try:
                self.db.execute("INSERT OR IGNORE INTO revoked_sessions VALUES(?,?)", (session_id, now))
                self.db.execute("UPDATE bootstraps SET state='revoked' WHERE session_id=?", (session_id,))
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        self._broker_ok()
        self.broker.revoke_session(session_id=session_id, timeout_seconds=timeout_seconds)

    def pending_recovery(self, *, limit: int = 100) -> tuple[str, ...]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise SpeechGatewayError("speech_recovery_limit_invalid")
        with self.lock:
            return tuple(row[0] for row in self.db.execute(
                "SELECT DISTINCT session_id FROM bootstraps WHERE state IN ('minting','indeterminate') "
                "ORDER BY session_id LIMIT ?", (limit,)))
