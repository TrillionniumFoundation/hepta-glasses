"""Durable OAuth 2.1 PKCE and encrypted refresh-credential custody.

The vault stores state and token digests plus ciphertext only.  Authorization
codes and access tokens never enter SQLite.  A state is reserved before provider
I/O and is never made retryable after an uncertain exchange.  Revocation is
monotonic: local authority is removed before remote cleanup is attempted.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

_MAX_TIME = 253_402_300_799
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z")
_PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


class OAuthVaultError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OAuthCipher(Protocol):
    def current_key_id(self, *, subject: str) -> str: ...
    def encrypt(
        self, *, subject: str, key_id: str, plaintext: bytes, aad: bytes
    ) -> bytes: ...
    def decrypt(
        self, *, subject: str, key_id: str, ciphertext: bytes, aad: bytes
    ) -> bytes: ...


@dataclass(frozen=True, repr=False)
class OAuthTokenSet:
    account_id: str
    scopes: tuple[str, ...]
    refresh_token: str
    access_token: str
    access_expires_at: int
    provider_receipt_id: str


@dataclass(frozen=True, repr=False)
class OAuthAccessGrant:
    subject: str
    account_id: str
    provider: str
    scopes: tuple[str, ...]
    access_token: str
    expires_at: int
    credential_id: str
    generation: int


@dataclass(frozen=True)
class OAuthRevocation:
    sequence: int
    credential_id: str
    subject: str
    account_id: str
    provider: str
    generation: int


class OAuthProvider(Protocol):
    provider_id: str

    def exchange_code(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
        requested_scopes: tuple[str, ...],
        timeout_seconds: float,
    ) -> OAuthTokenSet: ...

    def refresh_access(
        self,
        *,
        refresh_token: str,
        requested_scopes: tuple[str, ...],
        timeout_seconds: float,
    ) -> OAuthTokenSet: ...

    def revoke_refresh(
        self, *, refresh_token: str, timeout_seconds: float
    ) -> str: ...


class DurableOAuthVault:
    VERSION = 1

    def __init__(
        self,
        path: str,
        *,
        cipher: OAuthCipher,
        providers: Iterable[OAuthProvider],
        clock: Callable[[], int],
        maximum_states: int = 100_000,
        maximum_credentials: int = 100_000,
    ) -> None:
        provider_map: dict[str, OAuthProvider] = {}
        try:
            for provider in providers:
                identifier = getattr(provider, "provider_id", None)
                if (
                    type(identifier) is not str
                    or _PROVIDER.fullmatch(identifier) is None
                    or identifier in provider_map
                    or not callable(getattr(provider, "exchange_code", None))
                    or not callable(getattr(provider, "refresh_access", None))
                    or not callable(getattr(provider, "revoke_refresh", None))
                ):
                    raise OAuthVaultError("oauth_provider_invalid")
                provider_map[identifier] = provider
        except TypeError:
            raise OAuthVaultError("oauth_provider_invalid") from None
        if (
            type(path) is not str
            or not path
            or not provider_map
            or not callable(clock)
            or not callable(getattr(cipher, "current_key_id", None))
            or not callable(getattr(cipher, "encrypt", None))
            or not callable(getattr(cipher, "decrypt", None))
            or type(maximum_states) is not int
            or not 1 <= maximum_states <= 1_000_000
            or type(maximum_credentials) is not int
            or not 1 <= maximum_credentials <= 1_000_000
        ):
            raise OAuthVaultError("oauth_configuration_invalid")
        self.path = path
        self.cipher = cipher
        self.providers = provider_map
        self.clock = clock
        self.maximum_states = maximum_states
        self.maximum_credentials = maximum_credentials
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False, timeout=5
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
        def __init__(self, owner: "DurableOAuthVault") -> None:
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

    def _transaction(self) -> "DurableOAuthVault._Transaction":
        return self._Transaction(self)

    def close(self) -> None:
        self.db.close()

    def _ensure_schema(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS oauth_component("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER "
            "NOT NULL,component_id TEXT NOT NULL)"
        )
        marker = self.db.execute(
            "SELECT version FROM oauth_component WHERE singleton=1"
        ).fetchone()
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"oauth_states", "oauth_credentials", "oauth_revoke_outbox"}
        if marker is not None:
            if marker[0] != self.VERSION or not required <= tables:
                raise OAuthVaultError("oauth_schema_invalid")
            return
        if required & tables:
            raise OAuthVaultError("oauth_unmarked_schema_rejected")
        self.db.execute(
            "CREATE TABLE oauth_states("
            "state_digest TEXT PRIMARY KEY,subject TEXT NOT NULL,account_hint TEXT "
            "NOT NULL,provider TEXT NOT NULL,redirect_uri TEXT NOT NULL,scopes TEXT "
            "NOT NULL,challenge TEXT NOT NULL,expires_at INTEGER NOT NULL,state TEXT "
            "NOT NULL CHECK(state IN ('issued','exchanging','indeterminate','consumed',"
            "'expired')),created_at INTEGER NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE oauth_credentials("
            "credential_id TEXT PRIMARY KEY,subject TEXT NOT NULL,account_id TEXT "
            "NOT NULL,provider TEXT NOT NULL,scopes TEXT NOT NULL,key_id TEXT NOT NULL,"
            "refresh_ciphertext BLOB NOT NULL,refresh_digest TEXT NOT NULL,generation "
            "INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN ('active','revoked')),"
            "provider_receipt_id TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at "
            "INTEGER NOT NULL,UNIQUE(subject,account_id,provider))"
        )
        self.db.execute(
            "CREATE INDEX oauth_credentials_subject ON oauth_credentials("
            "subject,provider,state)"
        )
        self.db.execute(
            "CREATE TABLE oauth_revoke_outbox("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT,credential_id TEXT NOT NULL,"
            "subject TEXT NOT NULL,account_id TEXT NOT NULL,provider TEXT NOT NULL,"
            "key_id TEXT NOT NULL,refresh_ciphertext BLOB NOT NULL,generation INTEGER "
            "NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','acknowledged')),"
            "attempts INTEGER NOT NULL DEFAULT 0,last_receipt_digest TEXT)"
        )
        self.db.execute(
            "INSERT INTO oauth_component VALUES(1,?,?)",
            (self.VERSION, secrets.token_hex(16)),
        )

    @staticmethod
    def _identifier(value: object, code: str = "oauth_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise OAuthVaultError(code)
        return value

    @staticmethod
    def _provider(value: object) -> str:
        if type(value) is not str or _PROVIDER.fullmatch(value) is None:
            raise OAuthVaultError("oauth_provider_invalid")
        return value

    @staticmethod
    def _secret(value: object, code: str) -> str:
        if (
            type(value) is not str
            or not 16 <= len(value.encode("utf-8")) <= 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in value)
        ):
            raise OAuthVaultError(code)
        return value

    @staticmethod
    def _scopes(values: Iterable[str]) -> tuple[str, ...]:
        try:
            result = tuple(values)
        except TypeError:
            raise OAuthVaultError("oauth_scope_invalid") from None
        if (
            not result
            or len(result) > 32
            or len(set(result)) != len(result)
            or any(
                type(scope) is not str
                or not 1 <= len(scope) <= 256
                or any(ord(character) <= 32 or ord(character) == 127 for character in scope)
                for scope in result
            )
        ):
            raise OAuthVaultError("oauth_scope_invalid")
        return tuple(sorted(result))

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise OAuthVaultError("oauth_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise OAuthVaultError("oauth_clock_invalid")
        return value

    @staticmethod
    def _timeout(value: object) -> float:
        if type(value) not in (int, float) or type(value) is bool:
            raise OAuthVaultError("oauth_timeout_invalid")
        result = float(value)
        if not 0.01 <= result <= 60:
            raise OAuthVaultError("oauth_timeout_invalid")
        return result

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def pkce_challenge(verifier: str) -> str:
        verifier = DurableOAuthVault._secret(verifier, "oauth_verifier_invalid")
        if not 43 <= len(verifier) <= 128 or re.fullmatch(
            r"[A-Za-z0-9._~-]+", verifier
        ) is None:
            raise OAuthVaultError("oauth_verifier_invalid")
        return base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

    @staticmethod
    def _aad(
        *,
        credential_id: str,
        subject: str,
        account_id: str,
        provider: str,
        scopes: tuple[str, ...],
        generation: int,
    ) -> bytes:
        return json.dumps(
            [credential_id, subject, account_id, provider, scopes, generation],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")

    def begin_authorization(
        self,
        *,
        subject: str,
        account_hint: str,
        provider: str,
        redirect_uri: str,
        scopes: Iterable[str],
        code_challenge: str,
        expires_at: int,
    ) -> str:
        subject = self._identifier(subject)
        account_hint = self._identifier(account_hint)
        provider = self._provider(provider)
        redirect_uri = self._identifier(redirect_uri)
        scopes = self._scopes(scopes)
        if (
            provider not in self.providers
            or type(code_challenge) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge) is None
        ):
            raise OAuthVaultError("oauth_authorization_invalid")
        state = secrets.token_urlsafe(48)
        with self._transaction():
            now = self._now()
            if (
                type(expires_at) is not int
                or type(expires_at) is bool
                or not now < expires_at <= min(_MAX_TIME, now + 600)
            ):
                raise OAuthVaultError("oauth_authorization_expiry_invalid")
            if self.db.execute(
                "SELECT COUNT(*) FROM oauth_states"
            ).fetchone()[0] >= self.maximum_states:
                raise OAuthVaultError("oauth_state_capacity_exhausted")
            self.db.execute(
                "UPDATE oauth_states SET state='expired' WHERE state='issued' "
                "AND expires_at<=?",
                (now,),
            )
            self.db.execute(
                "INSERT INTO oauth_states VALUES(?,?,?,?,?,?,?,?, 'issued',?)",
                (
                    self._digest(state),
                    subject,
                    account_hint,
                    provider,
                    redirect_uri,
                    json.dumps(scopes, separators=(",", ":")),
                    code_challenge,
                    expires_at,
                    now,
                ),
            )
        return state

    def complete_authorization(
        self,
        *,
        state: str,
        code_verifier: str,
        authorization_code: str,
        timeout_seconds: float = 8,
    ) -> str:
        state = self._secret(state, "oauth_state_invalid")
        authorization_code = self._secret(
            authorization_code, "oauth_authorization_code_invalid"
        )
        challenge = self.pkce_challenge(code_verifier)
        timeout_seconds = self._timeout(timeout_seconds)
        state_digest = self._digest(state)
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM oauth_states WHERE state_digest=?", (state_digest,)
            ).fetchone()
            if row is None or row["state"] != "issued":
                raise OAuthVaultError("oauth_state_replayed_or_unknown")
            if row["expires_at"] <= now:
                self.db.execute(
                    "UPDATE oauth_states SET state='expired' WHERE state_digest=?",
                    (state_digest,),
                )
                raise OAuthVaultError("oauth_state_expired")
            if row["challenge"] != challenge:
                raise OAuthVaultError("oauth_pkce_mismatch")
            scopes = tuple(json.loads(row["scopes"]))
            self.db.execute(
                "UPDATE oauth_states SET state='exchanging' WHERE state_digest=?",
                (state_digest,),
            )
            snapshot = dict(row)
        provider = self.providers[snapshot["provider"]]
        started = time.monotonic()
        try:
            result = provider.exchange_code(
                authorization_code=authorization_code,
                code_verifier=code_verifier,
                redirect_uri=snapshot["redirect_uri"],
                requested_scopes=scopes,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            with self._transaction():
                self.db.execute(
                    "UPDATE oauth_states SET state='indeterminate' WHERE "
                    "state_digest=? AND state='exchanging'",
                    (state_digest,),
                )
            raise OAuthVaultError("oauth_exchange_indeterminate") from None
        if time.monotonic() - started > timeout_seconds:
            with self._transaction():
                self.db.execute(
                    "UPDATE oauth_states SET state='indeterminate' WHERE "
                    "state_digest=? AND state='exchanging'",
                    (state_digest,),
                )
            raise OAuthVaultError("oauth_exchange_indeterminate")
        return self._commit_token_set(
            state_digest=state_digest,
            state_row=snapshot,
            requested_scopes=scopes,
            result=result,
        )

    def _token_set(
        self,
        value: object,
        *,
        account_hint: str,
        requested_scopes: tuple[str, ...],
        now: int,
    ) -> OAuthTokenSet:
        if type(value) is not OAuthTokenSet:
            raise OAuthVaultError("oauth_provider_response_invalid")
        self._identifier(value.account_id, "oauth_provider_response_invalid")
        self._identifier(value.provider_receipt_id, "oauth_provider_response_invalid")
        refresh = self._secret(value.refresh_token, "oauth_provider_response_invalid")
        self._secret(value.access_token, "oauth_provider_response_invalid")
        scopes = self._scopes(value.scopes)
        if (
            value.account_id != account_hint
            or scopes != requested_scopes
            or type(value.access_expires_at) is not int
            or type(value.access_expires_at) is bool
            or not now < value.access_expires_at <= min(_MAX_TIME, now + 86_400)
        ):
            raise OAuthVaultError("oauth_provider_response_invalid")
        return OAuthTokenSet(
            value.account_id,
            scopes,
            refresh,
            value.access_token,
            value.access_expires_at,
            value.provider_receipt_id,
        )

    def _commit_token_set(
        self,
        *,
        state_digest: str,
        state_row: dict[str, object],
        requested_scopes: tuple[str, ...],
        result: object,
    ) -> str:
        with self._transaction():
            now = self._now()
            current = self.db.execute(
                "SELECT * FROM oauth_states WHERE state_digest=?", (state_digest,)
            ).fetchone()
            if (
                current is None
                or current["state"] != "exchanging"
                or current["subject"] != state_row["subject"]
                or current["provider"] != state_row["provider"]
                or current["expires_at"] <= now
            ):
                raise OAuthVaultError("oauth_exchange_authority_expired")
            token_set = self._token_set(
                result,
                account_hint=str(state_row["account_hint"]),
                requested_scopes=requested_scopes,
                now=now,
            )
            existing = self.db.execute(
                "SELECT * FROM oauth_credentials WHERE subject=? AND account_id=? "
                "AND provider=?",
                (
                    state_row["subject"],
                    token_set.account_id,
                    state_row["provider"],
                ),
            ).fetchone()
            if existing is None and self.db.execute(
                "SELECT COUNT(*) FROM oauth_credentials"
            ).fetchone()[0] >= self.maximum_credentials:
                raise OAuthVaultError("oauth_credential_capacity_exhausted")
            credential_id = (
                secrets.token_urlsafe(18)
                if existing is None
                else existing["credential_id"]
            )
            generation = 1 if existing is None else existing["generation"] + 1
            try:
                key_id = self.cipher.current_key_id(
                    subject=str(state_row["subject"])
                )
                self._identifier(key_id, "oauth_key_invalid")
                aad = self._aad(
                    credential_id=credential_id,
                    subject=str(state_row["subject"]),
                    account_id=token_set.account_id,
                    provider=str(state_row["provider"]),
                    scopes=requested_scopes,
                    generation=generation,
                )
                ciphertext = self.cipher.encrypt(
                    subject=str(state_row["subject"]),
                    key_id=key_id,
                    plaintext=token_set.refresh_token.encode("utf-8"),
                    aad=aad,
                )
            except OAuthVaultError:
                raise
            except Exception:
                raise OAuthVaultError("oauth_encrypt_failed") from None
            if not isinstance(ciphertext, (bytes, bytearray)) or not ciphertext:
                raise OAuthVaultError("oauth_encrypt_failed")
            if existing is not None and existing["state"] == "active":
                self._queue_revoke(existing)
            self.db.execute(
                "INSERT INTO oauth_credentials VALUES(?,?,?,?,?,?,?,?,?, 'active',?,?,?) "
                "ON CONFLICT(credential_id) DO UPDATE SET scopes=excluded.scopes,"
                "key_id=excluded.key_id,refresh_ciphertext=excluded.refresh_ciphertext,"
                "refresh_digest=excluded.refresh_digest,generation=excluded.generation,"
                "state='active',provider_receipt_id=excluded.provider_receipt_id,"
                "updated_at=excluded.updated_at",
                (
                    credential_id,
                    state_row["subject"],
                    token_set.account_id,
                    state_row["provider"],
                    json.dumps(requested_scopes, separators=(",", ":")),
                    key_id,
                    bytes(ciphertext),
                    self._digest(token_set.refresh_token),
                    generation,
                    token_set.provider_receipt_id,
                    now if existing is None else existing["created_at"],
                    now,
                ),
            )
            self.db.execute(
                "UPDATE oauth_states SET state='consumed' WHERE state_digest=?",
                (state_digest,),
            )
            return credential_id

    def _queue_revoke(self, row: sqlite3.Row) -> None:
        self.db.execute(
            "INSERT INTO oauth_revoke_outbox(credential_id,subject,account_id,"
            "provider,key_id,refresh_ciphertext,generation,state) VALUES(?,?,?,?,?,?,?,"
            "'pending')",
            (
                row["credential_id"],
                row["subject"],
                row["account_id"],
                row["provider"],
                row["key_id"],
                row["refresh_ciphertext"],
                row["generation"],
            ),
        )

    def _decrypt(self, row: sqlite3.Row) -> str:
        scopes = tuple(json.loads(row["scopes"]))
        aad = self._aad(
            credential_id=row["credential_id"],
            subject=row["subject"],
            account_id=row["account_id"],
            provider=row["provider"],
            scopes=scopes,
            generation=row["generation"],
        )
        try:
            raw = self.cipher.decrypt(
                subject=row["subject"],
                key_id=row["key_id"],
                ciphertext=bytes(row["refresh_ciphertext"]),
                aad=aad,
            )
            token = raw.decode("utf-8")
        except Exception:
            raise OAuthVaultError("oauth_decrypt_failed") from None
        token = self._secret(token, "oauth_decrypt_failed")
        if self._digest(token) != row["refresh_digest"]:
            raise OAuthVaultError("oauth_integrity_invalid")
        return token

    def grant_access(
        self,
        *,
        subject: str,
        account_id: str,
        provider: str,
        scopes: Iterable[str],
        authorize: Callable[[], None],
        timeout_seconds: float = 8,
    ) -> OAuthAccessGrant:
        subject = self._identifier(subject)
        account_id = self._identifier(account_id)
        provider = self._provider(provider)
        scopes = self._scopes(scopes)
        timeout_seconds = self._timeout(timeout_seconds)
        if not callable(authorize) or provider not in self.providers:
            raise OAuthVaultError("oauth_authority_invalid")
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM oauth_credentials WHERE subject=? AND account_id=? "
                "AND provider=?",
                (subject, account_id, provider),
            ).fetchone()
            if row is None or row["state"] != "active":
                raise OAuthVaultError("oauth_credential_unavailable")
            stored_scopes = tuple(json.loads(row["scopes"]))
            if not set(scopes) <= set(stored_scopes):
                raise OAuthVaultError("oauth_scope_denied")
            refresh_token = self._decrypt(row)
            snapshot = dict(row)
            authorize()
        started = time.monotonic()
        try:
            token_set = self.providers[provider].refresh_access(
                refresh_token=refresh_token,
                requested_scopes=scopes,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            raise OAuthVaultError("oauth_refresh_indeterminate") from None
        finally:
            refresh_token = ""
        if time.monotonic() - started > timeout_seconds:
            raise OAuthVaultError("oauth_refresh_indeterminate")
        with self._transaction():
            now = self._now()
            current = self.db.execute(
                "SELECT * FROM oauth_credentials WHERE credential_id=?",
                (snapshot["credential_id"],),
            ).fetchone()
            if (
                current is None
                or current["state"] != "active"
                or current["generation"] != snapshot["generation"]
                or current["refresh_digest"] != snapshot["refresh_digest"]
            ):
                raise OAuthVaultError("oauth_authority_revoked")
            authorize()
            validated = self._token_set(
                token_set,
                account_hint=account_id,
                requested_scopes=scopes,
                now=now,
            )
            # A refresh-token rotation is committed before its access token is
            # released.  The superseded token remains in the remote-revoke outbox.
            if validated.refresh_token != "unchanged":
                self._queue_revoke(current)
                key_id = self.cipher.current_key_id(subject=subject)
                self._identifier(key_id, "oauth_key_invalid")
                generation = current["generation"] + 1
                aad = self._aad(
                    credential_id=current["credential_id"],
                    subject=subject,
                    account_id=account_id,
                    provider=provider,
                    scopes=tuple(json.loads(current["scopes"])),
                    generation=generation,
                )
                try:
                    encrypted = self.cipher.encrypt(
                        subject=subject,
                        key_id=key_id,
                        plaintext=validated.refresh_token.encode("utf-8"),
                        aad=aad,
                    )
                except Exception:
                    raise OAuthVaultError("oauth_encrypt_failed") from None
                self.db.execute(
                    "UPDATE oauth_credentials SET key_id=?,refresh_ciphertext=?,"
                    "refresh_digest=?,generation=?,provider_receipt_id=?,updated_at=? "
                    "WHERE credential_id=?",
                    (
                        key_id,
                        bytes(encrypted),
                        self._digest(validated.refresh_token),
                        generation,
                        validated.provider_receipt_id,
                        now,
                        current["credential_id"],
                    ),
                )
            else:
                generation = current["generation"]
            return OAuthAccessGrant(
                subject=subject,
                account_id=account_id,
                provider=provider,
                scopes=scopes,
                access_token=validated.access_token,
                expires_at=validated.access_expires_at,
                credential_id=current["credential_id"],
                generation=generation,
            )

    def revoke(
        self, *, subject: str, account_id: str, provider: str
    ) -> None:
        subject = self._identifier(subject)
        account_id = self._identifier(account_id)
        provider = self._provider(provider)
        with self._transaction():
            row = self.db.execute(
                "SELECT * FROM oauth_credentials WHERE subject=? AND account_id=? "
                "AND provider=?",
                (subject, account_id, provider),
            ).fetchone()
            if row is None or row["state"] == "revoked":
                return
            self._queue_revoke(row)
            self.db.execute(
                "UPDATE oauth_credentials SET state='revoked',generation=generation+1,"
                "updated_at=? WHERE credential_id=?",
                (self._now(), row["credential_id"]),
            )

    def pending_revocations(self, *, limit: int = 100) -> list[OAuthRevocation]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise OAuthVaultError("oauth_revoke_page_invalid")
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM oauth_revoke_outbox WHERE state='pending' ORDER BY "
                "sequence LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                OAuthRevocation(
                    row["sequence"],
                    row["credential_id"],
                    row["subject"],
                    row["account_id"],
                    row["provider"],
                    row["generation"],
                )
                for row in rows
            ]

    def deliver_revocation(
        self, *, sequence: int, timeout_seconds: float = 8
    ) -> str:
        if type(sequence) is not int or type(sequence) is bool or sequence < 1:
            raise OAuthVaultError("oauth_revoke_sequence_invalid")
        timeout_seconds = self._timeout(timeout_seconds)
        with self._transaction():
            row = self.db.execute(
                "SELECT * FROM oauth_revoke_outbox WHERE sequence=?", (sequence,)
            ).fetchone()
            if row is None or row["state"] != "pending":
                raise OAuthVaultError("oauth_revoke_sequence_invalid")
            # Recreate the original AAD from the generation kept by the outbox.
            credential = self.db.execute(
                "SELECT * FROM oauth_credentials WHERE credential_id=?",
                (row["credential_id"],),
            ).fetchone()
            if credential is None:
                raise OAuthVaultError("oauth_revoke_custody_invalid")
            original = dict(credential)
            original["generation"] = row["generation"]
            original["key_id"] = row["key_id"]
            original["refresh_ciphertext"] = row["refresh_ciphertext"]
            refresh = self._decrypt(original)
            self.db.execute(
                "UPDATE oauth_revoke_outbox SET attempts=attempts+1 WHERE sequence=?",
                (sequence,),
            )
        try:
            receipt = self.providers[row["provider"]].revoke_refresh(
                refresh_token=refresh, timeout_seconds=timeout_seconds
            )
        except Exception:
            raise OAuthVaultError("oauth_remote_revoke_indeterminate") from None
        finally:
            refresh = ""
        receipt = self._identifier(receipt, "oauth_revoke_receipt_invalid")
        with self._transaction():
            changed = self.db.execute(
                "UPDATE oauth_revoke_outbox SET state='acknowledged',"
                "last_receipt_digest=? WHERE sequence=? AND state='pending'",
                (self._digest(receipt), sequence),
            ).rowcount
            if changed != 1:
                raise OAuthVaultError("oauth_revoke_sequence_invalid")
        return receipt

    def checkpoint(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
