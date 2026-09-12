"""Encrypted post-verification Skill package and consent custody.

Signed-package verification remains the responsibility of ``SignedSkillRegistry``.
This vault receives only the exact verified bytes/digests and stores ciphertext,
then rechecks package, publisher, version and consent authority before releasing
bytes to an isolated executor.  No signing key or package plaintext is persisted.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

_MAX_TIME = 253_402_300_799
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class PackageVaultError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PackageCipher(Protocol):
    def current_key_id(self, *, subject: str) -> str: ...
    def encrypt(
        self, *, subject: str, key_id: str, plaintext: bytes, aad: bytes
    ) -> bytes: ...
    def decrypt(
        self, *, subject: str, key_id: str, ciphertext: bytes, aad: bytes
    ) -> bytes: ...


@dataclass(frozen=True)
class VerifiedPackage:
    package_id: str
    skill_id: str
    publisher_id: str
    version: str
    manifest_digest: str
    package_digest: str
    package_bytes: bytes


@dataclass(frozen=True)
class PackageLease:
    subject: str
    package_id: str
    skill_id: str
    publisher_id: str
    version: str
    package_digest: str
    capabilities: tuple[str, ...]
    expires_at: int
    bytes: bytes


class EncryptedSkillPackageVault:
    VERSION = 1

    def __init__(
        self,
        path: str,
        *,
        cipher: PackageCipher,
        clock: Callable[[], int],
        maximum_packages: int = 10_000,
        maximum_package_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if (
            type(path) is not str
            or not path
            or not callable(clock)
            or not callable(getattr(cipher, "current_key_id", None))
            or not callable(getattr(cipher, "encrypt", None))
            or not callable(getattr(cipher, "decrypt", None))
            or type(maximum_packages) is not int
            or not 1 <= maximum_packages <= 100_000
            or type(maximum_package_bytes) is not int
            or not 1 <= maximum_package_bytes <= 64 * 1024 * 1024
        ):
            raise PackageVaultError("skill_vault_configuration_invalid")
        self.path = path
        self.cipher = cipher
        self.clock = clock
        self.maximum_packages = maximum_packages
        self.maximum_package_bytes = maximum_package_bytes
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
        def __init__(self, owner: "EncryptedSkillPackageVault") -> None:
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

    def _transaction(self) -> "EncryptedSkillPackageVault._Transaction":
        return self._Transaction(self)

    def close(self) -> None:
        self.db.close()

    def _ensure_schema(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS skill_vault_component("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT "
            "NULL,component_id TEXT NOT NULL)"
        )
        marker = self.db.execute(
            "SELECT version FROM skill_vault_component WHERE singleton=1"
        ).fetchone()
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "skill_vault_packages",
            "skill_vault_consents",
            "skill_vault_revocations",
            "skill_vault_events",
        }
        if marker is not None:
            if marker[0] != self.VERSION or not required <= tables:
                raise PackageVaultError("skill_vault_schema_invalid")
            return
        if required & tables:
            raise PackageVaultError("skill_vault_unmarked_schema_rejected")
        self.db.execute(
            "CREATE TABLE skill_vault_packages("
            "package_id TEXT PRIMARY KEY,skill_id TEXT NOT NULL,publisher_id TEXT NOT "
            "NULL,version TEXT NOT NULL,manifest_digest TEXT NOT NULL,package_digest "
            "TEXT NOT NULL UNIQUE,key_subject TEXT NOT NULL,key_id TEXT NOT NULL,"
            "ciphertext BLOB NOT NULL,ciphertext_digest TEXT NOT NULL,state TEXT NOT "
            "NULL CHECK(state IN ('active','revoked')),generation INTEGER NOT NULL,"
            "created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,UNIQUE(skill_id,version))"
        )
        self.db.execute(
            "CREATE TABLE skill_vault_consents("
            "subject TEXT NOT NULL,skill_id TEXT NOT NULL,version TEXT NOT NULL,"
            "package_digest TEXT NOT NULL,capabilities TEXT NOT NULL,policy_digest TEXT "
            "NOT NULL,expires_at INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN "
            "('active','revoked')),generation INTEGER NOT NULL,updated_at INTEGER NOT "
            "NULL,PRIMARY KEY(subject,skill_id))"
        )
        self.db.execute(
            "CREATE TABLE skill_vault_revocations("
            "kind TEXT NOT NULL,identifier TEXT NOT NULL,created_at INTEGER NOT NULL,"
            "PRIMARY KEY(kind,identifier))"
        )
        self.db.execute(
            "CREATE TABLE skill_vault_events("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,subject TEXT,"
            "package_id TEXT,skill_id TEXT,generation INTEGER NOT NULL,created_at INTEGER "
            "NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO skill_vault_component VALUES(1,?,?)",
            (self.VERSION, secrets.token_hex(16)),
        )

    @staticmethod
    def _identifier(value: object, code: str = "skill_vault_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise PackageVaultError(code)
        return value

    @staticmethod
    def _digest(value: object, code: str = "skill_vault_digest_invalid") -> str:
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise PackageVaultError(code)
        return value

    @staticmethod
    def _capabilities(values: Iterable[str]) -> tuple[str, ...]:
        try:
            result = tuple(values)
        except TypeError:
            raise PackageVaultError("skill_vault_capabilities_invalid") from None
        if (
            len(result) > 64
            or len(set(result)) != len(result)
            or any(
                type(item) is not str
                or _IDENTIFIER.fullmatch(item) is None
                or len(item) > 128
                for item in result
            )
        ):
            raise PackageVaultError("skill_vault_capabilities_invalid")
        return tuple(sorted(result))

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise PackageVaultError("skill_vault_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise PackageVaultError("skill_vault_clock_invalid")
        return value

    @staticmethod
    def _aad(
        package_id: str,
        skill_id: str,
        publisher_id: str,
        version: str,
        manifest_digest: str,
        package_digest: str,
        generation: int,
    ) -> bytes:
        return json.dumps(
            [
                package_id,
                skill_id,
                publisher_id,
                version,
                manifest_digest,
                package_digest,
                generation,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")

    def install(self, *, package: VerifiedPackage, key_subject: str) -> None:
        if type(package) is not VerifiedPackage:
            raise PackageVaultError("skill_vault_package_invalid")
        package_id = self._identifier(package.package_id)
        skill_id = self._identifier(package.skill_id)
        publisher_id = self._identifier(package.publisher_id)
        version = self._identifier(package.version)
        key_subject = self._identifier(key_subject)
        manifest_digest = self._digest(package.manifest_digest)
        package_digest = self._digest(package.package_digest)
        if (
            type(package.package_bytes) is not bytes
            or not package.package_bytes
            or len(package.package_bytes) > self.maximum_package_bytes
            or hashlib.sha256(package.package_bytes).hexdigest() != package_digest
        ):
            raise PackageVaultError("skill_vault_package_invalid")
        snapshot = bytes(package.package_bytes)
        with self._transaction():
            now = self._now()
            for kind, identifier in (
                ("package", package_id),
                ("skill", skill_id),
                ("publisher", publisher_id),
            ):
                if self.db.execute(
                    "SELECT 1 FROM skill_vault_revocations WHERE kind=? AND identifier=?",
                    (kind, identifier),
                ).fetchone():
                    raise PackageVaultError("skill_vault_revoked")
            existing = self.db.execute(
                "SELECT * FROM skill_vault_packages WHERE skill_id=? AND version=?",
                (skill_id, version),
            ).fetchone()
            if existing is not None:
                if (
                    existing["package_id"] == package_id
                    and existing["publisher_id"] == publisher_id
                    and existing["manifest_digest"] == manifest_digest
                    and existing["package_digest"] == package_digest
                    and existing["state"] == "active"
                ):
                    return
                raise PackageVaultError("skill_vault_version_conflict")
            if self.db.execute(
                "SELECT COUNT(*) FROM skill_vault_packages"
            ).fetchone()[0] >= self.maximum_packages:
                raise PackageVaultError("skill_vault_capacity_exhausted")
            try:
                key_id = self.cipher.current_key_id(subject=key_subject)
                self._identifier(key_id, "skill_vault_key_invalid")
                ciphertext = self.cipher.encrypt(
                    subject=key_subject,
                    key_id=key_id,
                    plaintext=snapshot,
                    aad=self._aad(
                        package_id,
                        skill_id,
                        publisher_id,
                        version,
                        manifest_digest,
                        package_digest,
                        1,
                    ),
                )
            except PackageVaultError:
                raise
            except Exception:
                raise PackageVaultError("skill_vault_encrypt_failed") from None
            if not isinstance(ciphertext, (bytes, bytearray)) or not ciphertext:
                raise PackageVaultError("skill_vault_encrypt_failed")
            self.db.execute(
                "INSERT INTO skill_vault_packages VALUES(?,?,?,?,?,?,?,?,?,?,"
                "'active',1,?,?)",
                (
                    package_id,
                    skill_id,
                    publisher_id,
                    version,
                    manifest_digest,
                    package_digest,
                    key_subject,
                    key_id,
                    bytes(ciphertext),
                    hashlib.sha256(bytes(ciphertext)).hexdigest(),
                    now,
                    now,
                ),
            )
            self._event("package_installed", None, package_id, skill_id, 1, now)

    def grant_consent(
        self,
        *,
        subject: str,
        skill_id: str,
        version: str,
        package_digest: str,
        capabilities: Iterable[str],
        policy_digest: str,
        expires_at: int,
    ) -> None:
        subject = self._identifier(subject)
        skill_id = self._identifier(skill_id)
        version = self._identifier(version)
        package_digest = self._digest(package_digest)
        policy_digest = self._digest(policy_digest)
        capabilities = self._capabilities(capabilities)
        with self._transaction():
            now = self._now()
            if (
                type(expires_at) is not int
                or type(expires_at) is bool
                or not now < expires_at <= _MAX_TIME
            ):
                raise PackageVaultError("skill_vault_consent_expiry_invalid")
            package = self.db.execute(
                "SELECT * FROM skill_vault_packages WHERE skill_id=? AND version=?",
                (skill_id, version),
            ).fetchone()
            if (
                package is None
                or package["state"] != "active"
                or package["package_digest"] != package_digest
            ):
                raise PackageVaultError("skill_vault_package_unavailable")
            existing = self.db.execute(
                "SELECT generation FROM skill_vault_consents WHERE subject=? AND "
                "skill_id=?",
                (subject, skill_id),
            ).fetchone()
            generation = 1 if existing is None else existing[0] + 1
            self.db.execute(
                "INSERT INTO skill_vault_consents VALUES(?,?,?,?,?,?,?,'active',?,?) "
                "ON CONFLICT(subject,skill_id) DO UPDATE SET version=excluded.version,"
                "package_digest=excluded.package_digest,capabilities=excluded.capabilities,"
                "policy_digest=excluded.policy_digest,expires_at=excluded.expires_at,"
                "state='active',generation=excluded.generation,updated_at=excluded.updated_at",
                (
                    subject,
                    skill_id,
                    version,
                    package_digest,
                    json.dumps(capabilities, separators=(",", ":")),
                    policy_digest,
                    expires_at,
                    generation,
                    now,
                ),
            )
            self._event(
                "consent_granted",
                subject,
                package["package_id"],
                skill_id,
                generation,
                now,
            )

    def _event(
        self,
        event: str,
        subject: str | None,
        package_id: str | None,
        skill_id: str | None,
        generation: int,
        now: int,
    ) -> None:
        self.db.execute(
            "INSERT INTO skill_vault_events(event,subject,package_id,skill_id,"
            "generation,created_at) VALUES(?,?,?,?,?,?)",
            (event, subject, package_id, skill_id, generation, now),
        )

    def revoke_consent(self, *, subject: str, skill_id: str) -> None:
        subject = self._identifier(subject)
        skill_id = self._identifier(skill_id)
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM skill_vault_consents WHERE subject=? AND skill_id=?",
                (subject, skill_id),
            ).fetchone()
            if row is None or row["state"] == "revoked":
                return
            generation = row["generation"] + 1
            self.db.execute(
                "UPDATE skill_vault_consents SET state='revoked',generation=?,"
                "updated_at=? WHERE subject=? AND skill_id=?",
                (generation, now, subject, skill_id),
            )
            self._event("consent_revoked", subject, None, skill_id, generation, now)

    def revoke(self, *, kind: str, identifier: str) -> None:
        if kind not in {"package", "skill", "publisher"}:
            raise PackageVaultError("skill_vault_revoke_kind_invalid")
        identifier = self._identifier(identifier)
        with self._transaction():
            now = self._now()
            self.db.execute(
                "INSERT INTO skill_vault_revocations VALUES(?,?,?) ON CONFLICT DO NOTHING",
                (kind, identifier, now),
            )
            if kind == "package":
                rows = self.db.execute(
                    "SELECT package_id,skill_id,generation FROM skill_vault_packages "
                    "WHERE package_id=? AND state='active'",
                    (identifier,),
                ).fetchall()
                self.db.execute(
                    "UPDATE skill_vault_packages SET state='revoked',"
                    "generation=generation+1,updated_at=? WHERE package_id=?",
                    (now, identifier),
                )
            elif kind == "skill":
                rows = self.db.execute(
                    "SELECT package_id,skill_id,generation FROM skill_vault_packages "
                    "WHERE skill_id=? AND state='active'",
                    (identifier,),
                ).fetchall()
                self.db.execute(
                    "UPDATE skill_vault_packages SET state='revoked',"
                    "generation=generation+1,updated_at=? WHERE skill_id=?",
                    (now, identifier),
                )
                self.db.execute(
                    "UPDATE skill_vault_consents SET state='revoked',"
                    "generation=generation+1,updated_at=? WHERE skill_id=?",
                    (now, identifier),
                )
            else:
                rows = self.db.execute(
                    "SELECT package_id,skill_id,generation FROM skill_vault_packages "
                    "WHERE publisher_id=? AND state='active'",
                    (identifier,),
                ).fetchall()
                self.db.execute(
                    "UPDATE skill_vault_packages SET state='revoked',"
                    "generation=generation+1,updated_at=? WHERE publisher_id=?",
                    (now, identifier),
                )
                for skill in {row["skill_id"] for row in rows}:
                    self.db.execute(
                        "UPDATE skill_vault_consents SET state='revoked',"
                        "generation=generation+1,updated_at=? WHERE skill_id=?",
                        (now, skill),
                    )
            for row in rows:
                self._event(
                    kind + "_revoked",
                    None,
                    row["package_id"],
                    row["skill_id"],
                    row["generation"] + 1,
                    now,
                )

    def _package_plaintext(self, row: sqlite3.Row) -> bytes:
        ciphertext = bytes(row["ciphertext"])
        if hashlib.sha256(ciphertext).hexdigest() != row["ciphertext_digest"]:
            raise PackageVaultError("skill_vault_integrity_invalid")
        try:
            raw = self.cipher.decrypt(
                subject=row["key_subject"],
                key_id=row["key_id"],
                ciphertext=ciphertext,
                aad=self._aad(
                    row["package_id"],
                    row["skill_id"],
                    row["publisher_id"],
                    row["version"],
                    row["manifest_digest"],
                    row["package_digest"],
                    row["generation"],
                ),
            )
        except Exception:
            raise PackageVaultError("skill_vault_decrypt_failed") from None
        if hashlib.sha256(raw).hexdigest() != row["package_digest"]:
            raise PackageVaultError("skill_vault_integrity_invalid")
        return bytes(raw)

    def lease(
        self,
        *,
        subject: str,
        skill_id: str,
        required_capabilities: Iterable[str],
        policy_digest: str,
        authorize: Callable[[], None],
    ) -> PackageLease:
        subject = self._identifier(subject)
        skill_id = self._identifier(skill_id)
        required = self._capabilities(required_capabilities)
        policy_digest = self._digest(policy_digest)
        if not callable(authorize):
            raise PackageVaultError("skill_vault_authority_invalid")
        with self._transaction():
            now = self._now()
            consent = self.db.execute(
                "SELECT * FROM skill_vault_consents WHERE subject=? AND skill_id=?",
                (subject, skill_id),
            ).fetchone()
            if (
                consent is None
                or consent["state"] != "active"
                or consent["expires_at"] <= now
                or consent["policy_digest"] != policy_digest
            ):
                raise PackageVaultError("skill_vault_consent_denied")
            capabilities = tuple(json.loads(consent["capabilities"]))
            if not set(required) <= set(capabilities):
                raise PackageVaultError("skill_vault_capability_denied")
            package = self.db.execute(
                "SELECT * FROM skill_vault_packages WHERE skill_id=? AND version=?",
                (skill_id, consent["version"]),
            ).fetchone()
            if (
                package is None
                or package["state"] != "active"
                or package["package_digest"] != consent["package_digest"]
            ):
                raise PackageVaultError("skill_vault_package_unavailable")
            for kind, identifier in (
                ("package", package["package_id"]),
                ("skill", skill_id),
                ("publisher", package["publisher_id"]),
            ):
                if self.db.execute(
                    "SELECT 1 FROM skill_vault_revocations WHERE kind=? AND identifier=?",
                    (kind, identifier),
                ).fetchone():
                    raise PackageVaultError("skill_vault_revoked")
            authorize()
            raw = self._package_plaintext(package)
            # Recheck every mutable authority after decryption and immediately
            # before releasing bytes to the executor.
            current = self.db.execute(
                "SELECT * FROM skill_vault_consents WHERE subject=? AND skill_id=?",
                (subject, skill_id),
            ).fetchone()
            current_package = self.db.execute(
                "SELECT * FROM skill_vault_packages WHERE package_id=?",
                (package["package_id"],),
            ).fetchone()
            if (
                current is None
                or current["state"] != "active"
                or current["generation"] != consent["generation"]
                or current["expires_at"] <= self._now()
                or current_package is None
                or current_package["state"] != "active"
                or current_package["generation"] != package["generation"]
            ):
                raise PackageVaultError("skill_vault_authority_revoked")
            authorize()
            return PackageLease(
                subject=subject,
                package_id=package["package_id"],
                skill_id=skill_id,
                publisher_id=package["publisher_id"],
                version=package["version"],
                package_digest=package["package_digest"],
                capabilities=required,
                expires_at=current["expires_at"],
                bytes=raw,
            )

    def checkpoint(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
