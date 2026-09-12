"""Durable authenticated account, session, token, pair and revoke custody.

This component stores only token digests.  It deliberately separates the
session lifetime from each access-token lifetime so token rotation cannot
accidentally terminate the authenticated session.  It implements the
``DurableAccessAuthority`` and ``ActivePairAuthority`` protocols consumed by
``AuthenticatedPrincipalAdapter``.

Production signing and platform attestation remain deployment authorities.  A
caller may construct this store only after those authorities have admitted the
subject/device pair.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from services.control_plane.authenticated_principals import (
    ActivePairBinding,
    VerifiedAccessClaims,
)

_MAX_TIME = 253_402_300_799
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class AccountRuntimeError(ValueError):
    """Stable account-runtime failure without attacker-controlled detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class AccountSession:
    session_id: str
    subject: str
    device_id: str
    expires_at: int
    generation: int


@dataclass(frozen=True)
class RevocationEvent:
    sequence: int
    subject: str
    session_id: str | None
    device_id: str | None
    reason: str
    created_at: int


class DurableAccountRuntime:
    """SQLite-backed identity interpretation used by every product ingress.

    The database contains no bearer-token bytes.  Token rotation revokes only
    predecessor tokens for the same session/audience; the session remains live
    until its own expiry or an explicit monotonic revoke.
    """

    VERSION = 1

    def __init__(
        self,
        path: str,
        *,
        clock: Callable[[], int],
        maximum_subjects: int = 100_000,
        maximum_sessions: int = 1_000_000,
    ) -> None:
        if (
            type(path) is not str
            or not path
            or not callable(clock)
            or type(maximum_subjects) is not int
            or not 1 <= maximum_subjects <= 1_000_000
            or type(maximum_sessions) is not int
            or not 1 <= maximum_sessions <= 10_000_000
        ):
            raise AccountRuntimeError("account_runtime_configuration_invalid")
        self.path = path
        self.clock = clock
        self.maximum_subjects = maximum_subjects
        self.maximum_sessions = maximum_sessions
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            path,
            isolation_level=None,
            check_same_thread=False,
            timeout=5,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA secure_delete=ON")
        try:
            with self._transaction():
                self._ensure_schema()
        except BaseException:
            self.db.close()
            raise

    class _Transaction:
        def __init__(self, owner: "DurableAccountRuntime") -> None:
            self.owner = owner

        def __enter__(self) -> sqlite3.Connection:
            self.owner.lock.acquire()
            try:
                self.owner.db.execute("BEGIN IMMEDIATE")
            except BaseException:
                self.owner.lock.release()
                raise
            return self.owner.db

        def __exit__(self, typ, value, traceback) -> None:
            try:
                self.owner.db.execute("ROLLBACK" if typ else "COMMIT")
            finally:
                self.owner.lock.release()

    def _transaction(self) -> "DurableAccountRuntime._Transaction":
        return self._Transaction(self)

    def close(self) -> None:
        self.db.close()

    def _ensure_schema(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS account_component("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "version INTEGER NOT NULL,component_id TEXT NOT NULL)"
        )
        row = self.db.execute(
            "SELECT version FROM account_component WHERE singleton=1"
        ).fetchone()
        existing = {
            item[0]
            for item in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "account_subjects",
            "account_devices",
            "account_sessions",
            "account_tokens",
            "account_pairs",
            "account_revocations",
        }
        if row is not None:
            if row[0] != self.VERSION or not required <= existing:
                raise AccountRuntimeError("account_runtime_schema_invalid")
            return
        if required & existing:
            raise AccountRuntimeError("account_runtime_unmarked_schema_rejected")
        statements = (
            "CREATE TABLE account_subjects("
            "subject TEXT PRIMARY KEY,state TEXT NOT NULL CHECK(state IN "
            "('active','revoked')),created_at INTEGER NOT NULL)",
            "CREATE TABLE account_devices("
            "device_id TEXT PRIMARY KEY,subject TEXT NOT NULL REFERENCES "
            "account_subjects(subject),state TEXT NOT NULL CHECK(state IN "
            "('active','lost','replaced','revoked')),replacement_device_id TEXT,"
            "registered_at INTEGER NOT NULL)",
            "CREATE TABLE account_sessions("
            "session_id TEXT PRIMARY KEY,subject TEXT NOT NULL REFERENCES "
            "account_subjects(subject),device_id TEXT NOT NULL REFERENCES "
            "account_devices(device_id),state TEXT NOT NULL CHECK(state IN "
            "('active','revoked','expired')),expires_at INTEGER NOT NULL,"
            "generation INTEGER NOT NULL,created_at INTEGER NOT NULL)",
            "CREATE TABLE account_tokens("
            "token_digest TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES "
            "account_sessions(session_id),audience TEXT NOT NULL,scopes TEXT NOT NULL,"
            "policy_hash TEXT NOT NULL,user_present INTEGER NOT NULL CHECK(" 
            "user_present IN (0,1)),biometric_verified INTEGER NOT NULL CHECK(" 
            "biometric_verified IN (0,1)),expires_at INTEGER NOT NULL,state TEXT "
            "NOT NULL CHECK(state IN ('active','rotated','revoked','expired')),"
            "created_at INTEGER NOT NULL)",
            "CREATE INDEX account_tokens_session ON account_tokens(session_id,audience,state)",
            "CREATE TABLE account_pairs("
            "session_id TEXT PRIMARY KEY REFERENCES account_sessions(session_id),"
            "subject TEXT NOT NULL,device_id TEXT NOT NULL,pair_identity TEXT NOT NULL,"
            "state TEXT NOT NULL CHECK(state IN ('active','revoked','expired')),"
            "expires_at INTEGER NOT NULL,generation INTEGER NOT NULL)",
            "CREATE TABLE account_revocations("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT,subject TEXT NOT NULL,"
            "session_id TEXT,device_id TEXT,reason TEXT NOT NULL,created_at INTEGER "
            "NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','acknowledged')))"
        )
        for statement in statements:
            self.db.execute(statement)
        self.db.execute(
            "INSERT INTO account_component VALUES(1,?,?)",
            (self.VERSION, secrets.token_hex(16)),
        )

    @staticmethod
    def _identifier(value: object, code: str = "account_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise AccountRuntimeError(code)
        return value

    @staticmethod
    def _policy_hash(value: object) -> str:
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise AccountRuntimeError("account_policy_hash_invalid")
        return value

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise AccountRuntimeError("account_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise AccountRuntimeError("account_clock_invalid")
        return value

    @staticmethod
    def _expiry(value: object, now: int, code: str) -> int:
        if (
            type(value) is not int
            or type(value) is bool
            or not now < value <= _MAX_TIME
        ):
            raise AccountRuntimeError(code)
        return value

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _scopes(values: Iterable[str]) -> tuple[str, ...]:
        try:
            scopes = tuple(values)
        except TypeError:
            raise AccountRuntimeError("account_scope_invalid") from None
        if (
            not scopes
            or len(scopes) > 32
            or len(set(scopes)) != len(scopes)
            or any(
                type(item) is not str
                or not 1 <= len(item) <= 128
                or any(ord(character) <= 32 or ord(character) == 127 for character in item)
                for item in scopes
            )
        ):
            raise AccountRuntimeError("account_scope_invalid")
        return tuple(sorted(scopes))

    def register_subject(self, *, subject: str, device_id: str) -> None:
        subject = self._identifier(subject)
        device_id = self._identifier(device_id)
        with self._transaction():
            now = self._now()
            subject_row = self.db.execute(
                "SELECT * FROM account_subjects WHERE subject=?", (subject,)
            ).fetchone()
            if subject_row is None:
                if self.db.execute(
                    "SELECT COUNT(*) FROM account_subjects"
                ).fetchone()[0] >= self.maximum_subjects:
                    raise AccountRuntimeError("account_subject_capacity_exhausted")
                self.db.execute(
                    "INSERT INTO account_subjects VALUES(?,'active',?)",
                    (subject, now),
                )
            elif subject_row["state"] != "active":
                raise AccountRuntimeError("account_subject_revoked")
            device = self.db.execute(
                "SELECT * FROM account_devices WHERE device_id=?", (device_id,)
            ).fetchone()
            if device is None:
                self.db.execute(
                    "INSERT INTO account_devices VALUES(?,?,'active',NULL,?)",
                    (device_id, subject, now),
                )
            elif device["subject"] != subject or device["state"] != "active":
                raise AccountRuntimeError("account_device_conflict")

    def open_session(
        self,
        *,
        subject: str,
        device_id: str,
        expires_at: int,
        session_id: str | None = None,
    ) -> AccountSession:
        subject = self._identifier(subject)
        device_id = self._identifier(device_id)
        session_id = self._identifier(session_id or secrets.token_urlsafe(18))
        with self._transaction():
            now = self._now()
            expires_at = self._expiry(
                expires_at, now, "account_session_expiry_invalid"
            )
            subject_row = self.db.execute(
                "SELECT state FROM account_subjects WHERE subject=?", (subject,)
            ).fetchone()
            device = self.db.execute(
                "SELECT subject,state FROM account_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
            if subject_row is None or subject_row[0] != "active":
                raise AccountRuntimeError("account_subject_unavailable")
            if (
                device is None
                or device["subject"] != subject
                or device["state"] != "active"
            ):
                raise AccountRuntimeError("account_device_unavailable")
            if self.db.execute(
                "SELECT COUNT(*) FROM account_sessions"
            ).fetchone()[0] >= self.maximum_sessions:
                raise AccountRuntimeError("account_session_capacity_exhausted")
            try:
                self.db.execute(
                    "INSERT INTO account_sessions VALUES(?,?,?,'active',?,1,?)",
                    (session_id, subject, device_id, expires_at, now),
                )
            except sqlite3.IntegrityError:
                raise AccountRuntimeError("account_session_conflict") from None
        return AccountSession(session_id, subject, device_id, expires_at, 1)

    def bind_pair(
        self,
        *,
        session_id: str,
        pair_identity: str,
        expires_at: int,
    ) -> ActivePairBinding:
        session_id = self._identifier(session_id)
        pair_identity = self._identifier(pair_identity)
        with self._transaction():
            now = self._now()
            row = self._live_session(session_id, now)
            expires_at = self._expiry(
                expires_at, now, "account_pair_expiry_invalid"
            )
            if expires_at > row["expires_at"]:
                raise AccountRuntimeError("account_pair_expiry_invalid")
            existing = self.db.execute(
                "SELECT * FROM account_pairs WHERE session_id=?", (session_id,)
            ).fetchone()
            generation = 1 if existing is None else existing["generation"] + 1
            self.db.execute(
                "INSERT INTO account_pairs VALUES(?,?,?,?, 'active',?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET subject=excluded.subject,"
                "device_id=excluded.device_id,pair_identity=excluded.pair_identity,"
                "state='active',expires_at=excluded.expires_at,"
                "generation=excluded.generation",
                (
                    session_id,
                    row["subject"],
                    row["device_id"],
                    pair_identity,
                    expires_at,
                    generation,
                ),
            )
        return ActivePairBinding(
            row["subject"], row["device_id"], session_id, pair_identity, True,
            expires_at,
        )

    def issue_access(
        self,
        *,
        session_id: str,
        audience: str,
        scopes: Iterable[str],
        policy_hash: str,
        expires_at: int,
        user_present: bool = False,
        biometric_verified: bool = False,
    ) -> str:
        session_id = self._identifier(session_id)
        audience = self._identifier(audience)
        scopes = self._scopes(scopes)
        policy_hash = self._policy_hash(policy_hash)
        if type(user_present) is not bool or type(biometric_verified) is not bool:
            raise AccountRuntimeError("account_presence_invalid")
        token = secrets.token_urlsafe(48)
        digest = self._token_digest(token)
        with self._transaction():
            now = self._now()
            row = self._live_session(session_id, now)
            expires_at = self._expiry(
                expires_at, now, "account_token_expiry_invalid"
            )
            if expires_at > row["expires_at"]:
                raise AccountRuntimeError("account_token_expiry_invalid")
            self.db.execute(
                "UPDATE account_tokens SET state='rotated' WHERE session_id=? "
                "AND audience=? AND state='active'",
                (session_id, audience),
            )
            self.db.execute(
                "INSERT INTO account_tokens VALUES(?,?,?,?,?,?,?,?, 'active',?)",
                (
                    digest,
                    session_id,
                    audience,
                    json.dumps(scopes, separators=(",", ":")),
                    policy_hash,
                    int(user_present),
                    int(biometric_verified),
                    expires_at,
                    now,
                ),
            )
        return token

    def _live_session(self, session_id: str, now: int) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT s.*,d.state AS device_state,u.state AS subject_state "
            "FROM account_sessions s JOIN account_devices d USING(device_id) "
            "JOIN account_subjects u USING(subject) WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise AccountRuntimeError("account_session_unknown")
        if row["expires_at"] <= now:
            self.db.execute(
                "UPDATE account_sessions SET state='expired',generation=generation+1 "
                "WHERE session_id=? AND state='active'",
                (session_id,),
            )
            self.db.execute(
                "UPDATE account_tokens SET state='expired' WHERE session_id=? "
                "AND state='active'",
                (session_id,),
            )
            self.db.execute(
                "UPDATE account_pairs SET state='expired',generation=generation+1 "
                "WHERE session_id=? AND state='active'",
                (session_id,),
            )
            raise AccountRuntimeError("account_session_expired")
        if (
            row["state"] != "active"
            or row["device_state"] != "active"
            or row["subject_state"] != "active"
        ):
            raise AccountRuntimeError("account_session_revoked")
        return row

    def verify_access(
        self,
        *,
        bearer_token: str,
        audience: str,
        required_scope: str,
    ) -> VerifiedAccessClaims:
        if (
            type(bearer_token) is not str
            or not 16 <= len(bearer_token.encode("utf-8")) <= 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in bearer_token)
        ):
            raise AccountRuntimeError("account_access_denied")
        audience = self._identifier(audience, "account_access_denied")
        if type(required_scope) is not str or not required_scope:
            raise AccountRuntimeError("account_access_denied")
        digest = self._token_digest(bearer_token)
        with self._transaction():
            now = self._now()
            token = self.db.execute(
                "SELECT t.*,s.subject,s.device_id,s.expires_at AS session_expires "
                "FROM account_tokens t JOIN account_sessions s USING(session_id) "
                "WHERE token_digest=?",
                (digest,),
            ).fetchone()
            if token is None or token["state"] != "active":
                raise AccountRuntimeError("account_access_denied")
            row = self._live_session(token["session_id"], now)
            if token["expires_at"] <= now:
                self.db.execute(
                    "UPDATE account_tokens SET state='expired' WHERE token_digest=?",
                    (digest,),
                )
                raise AccountRuntimeError("account_access_denied")
            try:
                scopes = tuple(json.loads(token["scopes"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise AccountRuntimeError("account_access_denied") from None
            if (
                token["audience"] != audience
                or required_scope not in scopes
                or token["expires_at"] > row["expires_at"]
            ):
                raise AccountRuntimeError("account_access_denied")
            return VerifiedAccessClaims(
                subject=row["subject"],
                device_id=row["device_id"],
                session_id=row["session_id"],
                audience=audience,
                scopes=scopes,
                expires_at=token["expires_at"],
                policy_hash=token["policy_hash"],
                user_present=bool(token["user_present"]),
                biometric_verified=bool(token["biometric_verified"]),
            )

    def resolve_pair(
        self, *, subject: str, device_id: str, session_id: str
    ) -> ActivePairBinding:
        subject = self._identifier(subject, "account_pair_denied")
        device_id = self._identifier(device_id, "account_pair_denied")
        session_id = self._identifier(session_id, "account_pair_denied")
        with self._transaction():
            now = self._now()
            session = self._live_session(session_id, now)
            pair = self.db.execute(
                "SELECT * FROM account_pairs WHERE session_id=?", (session_id,)
            ).fetchone()
            if (
                pair is None
                or pair["state"] != "active"
                or pair["expires_at"] <= now
                or pair["subject"] != subject
                or pair["device_id"] != device_id
                or session["subject"] != subject
                or session["device_id"] != device_id
            ):
                raise AccountRuntimeError("account_pair_denied")
            return ActivePairBinding(
                subject=subject,
                device_id=device_id,
                session_id=session_id,
                pair_identity=pair["pair_identity"],
                active=True,
                expires_at=pair["expires_at"],
            )

    def revoke_session(self, *, session_id: str, reason: str) -> None:
        session_id = self._identifier(session_id)
        reason = self._identifier(reason, "account_revoke_reason_invalid")
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM account_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise AccountRuntimeError("account_session_unknown")
            if row["state"] == "revoked":
                return
            self.db.execute(
                "UPDATE account_sessions SET state='revoked',generation=generation+1 "
                "WHERE session_id=?",
                (session_id,),
            )
            self.db.execute(
                "UPDATE account_tokens SET state='revoked' WHERE session_id=? "
                "AND state IN ('active','rotated')",
                (session_id,),
            )
            self.db.execute(
                "UPDATE account_pairs SET state='revoked',generation=generation+1 "
                "WHERE session_id=?",
                (session_id,),
            )
            self.db.execute(
                "INSERT INTO account_revocations(subject,session_id,device_id,reason,"
                "created_at,state) VALUES(?,?,?,?,?,'pending')",
                (row["subject"], session_id, row["device_id"], reason, now),
            )

    def replace_lost_device(
        self, *, subject: str, old_device_id: str, new_device_id: str
    ) -> None:
        subject = self._identifier(subject)
        old_device_id = self._identifier(old_device_id)
        new_device_id = self._identifier(new_device_id)
        if old_device_id == new_device_id:
            raise AccountRuntimeError("account_replacement_invalid")
        with self._transaction():
            now = self._now()
            old = self.db.execute(
                "SELECT * FROM account_devices WHERE device_id=?", (old_device_id,)
            ).fetchone()
            if old is None or old["subject"] != subject or old["state"] != "active":
                raise AccountRuntimeError("account_device_unavailable")
            if self.db.execute(
                "SELECT 1 FROM account_devices WHERE device_id=?", (new_device_id,)
            ).fetchone():
                raise AccountRuntimeError("account_device_conflict")
            self.db.execute(
                "UPDATE account_devices SET state='replaced',replacement_device_id=? "
                "WHERE device_id=?",
                (new_device_id, old_device_id),
            )
            self.db.execute(
                "INSERT INTO account_devices VALUES(?,?,'active',NULL,?)",
                (new_device_id, subject, now),
            )
            sessions = self.db.execute(
                "SELECT session_id FROM account_sessions WHERE subject=? AND "
                "device_id=? AND state='active'",
                (subject, old_device_id),
            ).fetchall()
            for session in sessions:
                self.db.execute(
                    "UPDATE account_sessions SET state='revoked',generation=generation+1 "
                    "WHERE session_id=?",
                    (session[0],),
                )
                self.db.execute(
                    "UPDATE account_tokens SET state='revoked' WHERE session_id=?",
                    (session[0],),
                )
                self.db.execute(
                    "UPDATE account_pairs SET state='revoked',generation=generation+1 "
                    "WHERE session_id=?",
                    (session[0],),
                )
                self.db.execute(
                    "INSERT INTO account_revocations(subject,session_id,device_id,"
                    "reason,created_at,state) VALUES(?,?,?,?,?,'pending')",
                    (subject, session[0], old_device_id, "lost_device", now),
                )

    def pending_revocations(
        self, *, after_sequence: int = 0, limit: int = 100
    ) -> list[RevocationEvent]:
        if (
            type(after_sequence) is not int
            or type(after_sequence) is bool
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise AccountRuntimeError("account_revoke_page_invalid")
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM account_revocations WHERE state='pending' AND "
                "sequence>? ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
            return [
                RevocationEvent(
                    sequence=row["sequence"],
                    subject=row["subject"],
                    session_id=row["session_id"],
                    device_id=row["device_id"],
                    reason=row["reason"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def acknowledge_revocation(self, *, sequence: int) -> None:
        if type(sequence) is not int or type(sequence) is bool or sequence < 1:
            raise AccountRuntimeError("account_revoke_sequence_invalid")
        with self._transaction():
            changed = self.db.execute(
                "UPDATE account_revocations SET state='acknowledged' WHERE "
                "sequence=? AND state='pending'",
                (sequence,),
            ).rowcount
            if changed != 1:
                raise AccountRuntimeError("account_revoke_sequence_invalid")

    def checkpoint(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def database_bytes(self) -> bytes:
        """Test/diagnostic helper; never returns WAL bytes or application data."""
        self.checkpoint()
        return Path(self.path).read_bytes()
