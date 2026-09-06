"""Authenticated durable mutation-lease issuer for the mobile edge runtime.

The service verifies a current identity/session principal, enforces an immutable
action/risk policy, stores only canonical argument digests, and returns a short-
lived exact single-use lease. It is framework-neutral and does not accept client
claims as identity proof.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

MAX_REQUEST_BYTES = 65_536
MAX_TIME = 253_402_300_799
DEFAULT_AUDIENCE = "hepta-mutation-authority"
REQUIRED_SCOPE = "mutation.authorize"


class MutationIngressError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class MutationPrincipal:
    subject: str
    device_id: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    policy_hash: str
    user_present: bool
    biometric_verified: bool
    expires_at: int


class MutationIdentityVerifier(Protocol):
    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> MutationPrincipal: ...


DEFAULT_ACTION_POLICY: Mapping[str, str] = {
    "device.display_text": "r1",
    "device.microphone_on": "r2",
    "device.exit_mode": "r1",
    "device.notification_whitelist": "r2",
    "device.send_notification": "r1",
    "device.display_bitmap_asset": "r1",
}


class MutationLeaseAuthority:
    def __init__(self, path: str, *, identity: MutationIdentityVerifier,
                 clock: Callable[[], int],
                 action_policy: Mapping[str, str] = DEFAULT_ACTION_POLICY,
                 audience: str = DEFAULT_AUDIENCE,
                 maximum_lease_seconds: int = 60,
                 maximum_records: int = 100_000) -> None:
        if not callable(getattr(identity, "verify", None)) or not callable(clock):
            raise MutationIngressError("mutation_authority_configuration_invalid", 500)
        self._identifier(audience, "mutation_authority_configuration_invalid")
        if (type(maximum_lease_seconds) is not int or
                not 1 <= maximum_lease_seconds <= 300 or
                type(maximum_records) is not int or
                not 1 <= maximum_records <= 1_000_000):
            raise MutationIngressError("mutation_authority_configuration_invalid", 500)
        normalized: dict[str, str] = {}
        for action, risk in action_policy.items():
            self._identifier(action, "mutation_authority_configuration_invalid")
            if risk not in {"r0", "r1", "r2", "r3"}:
                raise MutationIngressError("mutation_authority_configuration_invalid", 500)
            normalized[action] = risk
        if not normalized:
            raise MutationIngressError("mutation_authority_configuration_invalid", 500)
        self.identity = identity
        self.clock = clock
        self.action_policy = dict(sorted(normalized.items()))
        self.audience = audience
        self.maximum_lease_seconds = maximum_lease_seconds
        self.maximum_records = maximum_records
        self._lock = threading.RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._initialize_schema()

    def close(self) -> None:
        self.db.close()

    def authorize(self, *, authorization: str | None, body: bytes) -> dict[str, object]:
        token = self._bearer(authorization)
        request = self._request(body)
        try:
            principal = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=REQUIRED_SCOPE,
            )
            principal = self._principal(principal)
        except MutationIngressError as error:
            if error.code == "mutation_authority_unauthorized":
                raise MutationIngressError(error.code, 401) from None
            raise
        except Exception:
            raise MutationIngressError("mutation_authority_unauthorized", 401) from None

        if principal.audience != self.audience or REQUIRED_SCOPE not in principal.scopes:
            raise MutationIngressError("mutation_authority_scope_denied", 403)
        expected_risk = self.action_policy.get(request["action"])
        if expected_risk is None or expected_risk != request["risk_tier"]:
            raise MutationIngressError("mutation_authority_action_denied", 403)
        if expected_risk == "r2" and not principal.user_present:
            raise MutationIngressError("mutation_authority_user_presence_required", 403)
        if expected_risk == "r3" and (
            not principal.user_present or not principal.biometric_verified
        ):
            raise MutationIngressError("mutation_authority_biometric_required", 403)

        now = self._now()
        if principal.expires_at <= now:
            raise MutationIngressError("mutation_authority_unauthorized", 401)
        request_deadline = request["deadline_epoch_seconds"]
        expires_at = min(
            request_deadline,
            principal.expires_at,
            now + self.maximum_lease_seconds,
        )
        if expires_at <= now:
            raise MutationIngressError("mutation_authority_request_expired", 409)
        argument_digest = self._canonical_digest(request["arguments"])
        fingerprint = self._canonical_digest({
            "subject": principal.subject,
            "device_id": principal.device_id,
            "session_id": principal.session_id,
            "task_id": request["task_id"],
            "action": request["action"],
            "risk_tier": request["risk_tier"],
            "argument_digest": argument_digest,
            "deadline_epoch_seconds": request_deadline,
            "policy_hash": principal.policy_hash,
        })

        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._deny_if_revoked(principal)
                existing = self.db.execute(
                    "SELECT * FROM mutation_leases WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()
                if existing is not None:
                    if existing["state"] != "issued" or existing["expires_at"] <= now:
                        raise MutationIngressError("mutation_authority_lease_replayed", 409)
                    row = existing
                else:
                    count = self.db.execute(
                        "SELECT COUNT(*) FROM mutation_leases"
                    ).fetchone()[0]
                    if count >= self.maximum_records:
                        raise MutationIngressError("mutation_authority_capacity_exhausted", 503)
                    lease_id = "l-" + secrets.token_urlsafe(24)
                    self.db.execute(
                        "INSERT INTO mutation_leases(lease_id,fingerprint,subject,device_id,session_id,"
                        "task_id,action,risk_tier,argument_digest,policy_hash,issued_at,expires_at,state) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            lease_id, fingerprint, principal.subject, principal.device_id,
                            principal.session_id, request["task_id"], request["action"],
                            request["risk_tier"], argument_digest, principal.policy_hash,
                            now, expires_at, "issued",
                        ),
                    )
                    row = self.db.execute(
                        "SELECT * FROM mutation_leases WHERE lease_id=?",
                        (lease_id,),
                    ).fetchone()
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
        return self._response(row, principal)

    def revoke(self, kind: str, identifier: str) -> None:
        if kind not in {"subject", "device", "session"}:
            raise MutationIngressError("mutation_authority_revoke_kind_invalid")
        self._identifier(identifier, "mutation_authority_revoke_target_invalid")
        now = self._now()
        column = {"subject": "subject", "device": "device_id", "session": "session_id"}[kind]
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT OR IGNORE INTO mutation_revocations(kind,identifier,revoked_at) VALUES(?,?,?)",
                    (kind, identifier, now),
                )
                self.db.execute(
                    f"UPDATE mutation_leases SET state='revoked' WHERE {column}=? AND state='issued'",
                    (identifier,),
                )
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _initialize_schema(self) -> None:
        policy = self._canonical_digest({
            "audience": self.audience,
            "scope": REQUIRED_SCOPE,
            "actions": self.action_policy,
            "maximum_lease_seconds": self.maximum_lease_seconds,
            "maximum_records": self.maximum_records,
        })
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS mutation_authority_policy("
                    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version INTEGER NOT NULL,"
                    "policy_digest TEXT NOT NULL)"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS mutation_leases("
                    "lease_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL UNIQUE,subject TEXT NOT NULL,"
                    "device_id TEXT NOT NULL,session_id TEXT NOT NULL,task_id TEXT NOT NULL,"
                    "action TEXT NOT NULL,risk_tier TEXT NOT NULL,argument_digest TEXT NOT NULL,"
                    "policy_hash TEXT NOT NULL,issued_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,"
                    "state TEXT NOT NULL CHECK(state IN ('issued','revoked')))"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS mutation_revocations("
                    "kind TEXT NOT NULL,identifier TEXT NOT NULL,revoked_at INTEGER NOT NULL,"
                    "PRIMARY KEY(kind,identifier))"
                )
                row = self.db.execute(
                    "SELECT schema_version,policy_digest FROM mutation_authority_policy WHERE singleton=1"
                ).fetchone()
                if row is None:
                    self.db.execute(
                        "INSERT INTO mutation_authority_policy VALUES(1,1,?)", (policy,)
                    )
                elif row["schema_version"] != 1 or row["policy_digest"] != policy:
                    raise MutationIngressError("mutation_authority_policy_migration_required", 500)
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                self.db.close()
                raise

    def _deny_if_revoked(self, principal: MutationPrincipal) -> None:
        for kind, identifier in (
            ("subject", principal.subject),
            ("device", principal.device_id),
            ("session", principal.session_id),
        ):
            if self.db.execute(
                "SELECT 1 FROM mutation_revocations WHERE kind=? AND identifier=?",
                (kind, identifier),
            ).fetchone():
                raise MutationIngressError("mutation_authority_revoked", 403)

    def _request(self, body: bytes) -> dict[str, Any]:
        if type(body) is not bytes or not 1 <= len(body) <= MAX_REQUEST_BYTES:
            raise MutationIngressError("mutation_authority_body_invalid", 413)
        try:
            document = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=self._unique_object,
                parse_constant=lambda _: self._json_invalid(),
            )
        except (UnicodeError, json.JSONDecodeError, MutationIngressError):
            raise MutationIngressError("mutation_authority_json_invalid") from None
        if type(document) is not dict or set(document) != {
            "task_id", "action", "arguments", "risk_tier", "deadline_epoch_seconds"
        }:
            raise MutationIngressError("mutation_authority_request_shape_invalid")
        task_id = self._identifier(document["task_id"], "mutation_authority_request_invalid")
        action = self._identifier(document["action"], "mutation_authority_request_invalid")
        risk = document["risk_tier"]
        deadline = document["deadline_epoch_seconds"]
        arguments = document["arguments"]
        if risk not in {"r0", "r1", "r2", "r3", "r4"} or type(risk) is not str:
            raise MutationIngressError("mutation_authority_request_invalid")
        if type(deadline) is not int or type(deadline) is bool or not 0 <= deadline <= MAX_TIME:
            raise MutationIngressError("mutation_authority_request_invalid")
        self._normalize_json(arguments)
        return {
            "task_id": task_id,
            "action": action,
            "arguments": arguments,
            "risk_tier": risk,
            "deadline_epoch_seconds": deadline,
        }

    def _principal(self, value: object) -> MutationPrincipal:
        if type(value) is not MutationPrincipal:
            raise MutationIngressError("mutation_authority_unauthorized", 401)
        try:
            self._identifier(value.subject, "mutation_authority_unauthorized")
            self._identifier(value.device_id, "mutation_authority_unauthorized")
            self._identifier(value.session_id, "mutation_authority_unauthorized")
            self._identifier(value.audience, "mutation_authority_unauthorized")
        except MutationIngressError:
            raise MutationIngressError("mutation_authority_unauthorized", 401) from None
        if (type(value.scopes) is not tuple or not value.scopes or len(value.scopes) > 32
                or len(set(value.scopes)) != len(value.scopes)
                or any(type(scope) is not str or not 1 <= len(scope) <= 128 for scope in value.scopes)
                or re.fullmatch(r"[a-f0-9]{64}", value.policy_hash) is None
                or type(value.user_present) is not bool
                or type(value.biometric_verified) is not bool
                or type(value.expires_at) is not int or type(value.expires_at) is bool
                or not 0 <= value.expires_at <= MAX_TIME):
            raise MutationIngressError("mutation_authority_unauthorized", 401)
        return value

    def _response(self, row: sqlite3.Row, principal: MutationPrincipal) -> dict[str, object]:
        return {
            "task_id": row["task_id"],
            "action": row["action"],
            "risk_tier": row["risk_tier"],
            "argument_digest": row["argument_digest"],
            "subject": row["subject"],
            "device_id": row["device_id"],
            "policy_hash": row["policy_hash"],
            "authenticated": True,
            "user_present": principal.user_present,
            "biometric_verified": principal.biometric_verified,
            "lease_id": row["lease_id"],
            "allowed_actions": [row["action"]],
            "issued_at_epoch_seconds": row["issued_at"],
            "expires_at_epoch_seconds": row["expires_at"],
            "single_use": True,
        }

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise MutationIngressError("mutation_authority_clock_invalid", 503) from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= MAX_TIME:
            raise MutationIngressError("mutation_authority_clock_invalid", 503)
        return value

    @staticmethod
    def _bearer(value: str | None) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise MutationIngressError("mutation_authority_unauthorized", 401)
        token = value[7:]
        if not 16 <= len(token) <= 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in token):
            raise MutationIngressError("mutation_authority_unauthorized", 401)
        return token

    @staticmethod
    def _identifier(value: object, code: str) -> str:
        if (type(value) is not str or not 1 <= len(value) <= 256
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None):
            raise MutationIngressError(code)
        return value

    @classmethod
    def _normalize_json(cls, value: object, *, depth: int = 0) -> object:
        if depth > 16:
            raise MutationIngressError("mutation_authority_arguments_invalid")
        if value is None or type(value) in (str, bool, int):
            if type(value) is str and len(value.encode("utf-8")) > MAX_REQUEST_BYTES:
                raise MutationIngressError("mutation_authority_arguments_invalid")
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise MutationIngressError("mutation_authority_arguments_invalid")
            return value
        if type(value) is list:
            if len(value) > 2048:
                raise MutationIngressError("mutation_authority_arguments_invalid")
            return [cls._normalize_json(item, depth=depth + 1) for item in value]
        if type(value) is dict:
            if len(value) > 2048 or any(type(key) is not str for key in value):
                raise MutationIngressError("mutation_authority_arguments_invalid")
            return {
                key: cls._normalize_json(value[key], depth=depth + 1)
                for key in sorted(value)
            }
        raise MutationIngressError("mutation_authority_arguments_invalid")

    @classmethod
    def _canonical_digest(cls, value: object) -> str:
        normalized = cls._normalize_json(value)
        try:
            raw = json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise MutationIngressError("mutation_authority_arguments_invalid") from None
        if len(raw) > MAX_REQUEST_BYTES:
            raise MutationIngressError("mutation_authority_arguments_invalid")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise MutationIngressError("mutation_authority_json_invalid")
            result[key] = value
        return result

    @staticmethod
    def _json_invalid() -> object:
        raise MutationIngressError("mutation_authority_json_invalid")
