"""Encrypted payload custody for durable capability dispatch and recovery.

The existing durable capability ledger intentionally stores metadata only.  This
companion vault owns the encrypted request bytes needed for an authorized
readback/recovery worker.  It never retries a mutation after a dispatch claim;
post-claim loss is persistently ``indeterminate`` and only provider readback may
close it.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

_MAX_TIME = 253_402_300_799
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_TERMINAL = frozenset({"applied", "not_applied", "denied"})


class CapabilityPayloadError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PayloadCipher(Protocol):
    def current_key_id(self, *, subject: str) -> str: ...
    def encrypt(
        self, *, subject: str, key_id: str, plaintext: bytes, aad: bytes
    ) -> bytes: ...
    def decrypt(
        self, *, subject: str, key_id: str, ciphertext: bytes, aad: bytes
    ) -> bytes: ...


@dataclass(frozen=True)
class PayloadClaim:
    operation_id: str
    subject: str
    provider_id: str
    argument_digest: str
    generation: int
    deadline: int
    payload: Mapping[str, object]


@dataclass(frozen=True)
class RecoveryItem:
    operation_id: str
    subject: str
    provider_id: str
    argument_digest: str
    state: str
    generation: int
    readbacks: int
    deadline: int


class EncryptedCapabilityPayloadStore:
    VERSION = 1

    def __init__(
        self,
        path: str,
        *,
        cipher: PayloadCipher,
        clock: Callable[[], int],
        maximum_operations: int = 100_000,
        maximum_payload_bytes: int = 65_536,
        maximum_readbacks: int = 8,
    ) -> None:
        if (
            type(path) is not str
            or not path
            or not callable(clock)
            or not callable(getattr(cipher, "current_key_id", None))
            or not callable(getattr(cipher, "encrypt", None))
            or not callable(getattr(cipher, "decrypt", None))
            or type(maximum_operations) is not int
            or not 1 <= maximum_operations <= 1_000_000
            or type(maximum_payload_bytes) is not int
            or not 1 <= maximum_payload_bytes <= 1_048_576
            or type(maximum_readbacks) is not int
            or not 1 <= maximum_readbacks <= 32
        ):
            raise CapabilityPayloadError("capability_payload_configuration_invalid")
        self.path = path
        self.cipher = cipher
        self.clock = clock
        self.maximum_operations = maximum_operations
        self.maximum_payload_bytes = maximum_payload_bytes
        self.maximum_readbacks = maximum_readbacks
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
        def __init__(self, owner: "EncryptedCapabilityPayloadStore") -> None:
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

    def _transaction(self) -> "EncryptedCapabilityPayloadStore._Transaction":
        return self._Transaction(self)

    def close(self) -> None:
        self.db.close()

    def _ensure_schema(self) -> None:
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS capability_payload_component("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER "
            "NOT NULL,component_id TEXT NOT NULL)"
        )
        marker = self.db.execute(
            "SELECT version FROM capability_payload_component WHERE singleton=1"
        ).fetchone()
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "capability_payload_operations",
            "capability_payload_revoked_subjects",
            "capability_payload_events",
        }
        if marker is not None:
            if marker[0] != self.VERSION or not required <= tables:
                raise CapabilityPayloadError("capability_payload_schema_invalid")
            return
        if required & tables:
            raise CapabilityPayloadError(
                "capability_payload_unmarked_schema_rejected"
            )
        self.db.execute(
            "CREATE TABLE capability_payload_operations("
            "operation_id TEXT PRIMARY KEY,idempotency_digest TEXT UNIQUE NOT NULL,"
            "fingerprint TEXT NOT NULL,subject TEXT NOT NULL,provider_id TEXT NOT NULL,"
            "argument_digest TEXT NOT NULL,lease_digest TEXT NOT NULL,key_id TEXT NOT "
            "NULL,ciphertext BLOB NOT NULL,ciphertext_digest TEXT NOT NULL,state TEXT "
            "NOT NULL CHECK(state IN ('prepared','dispatching','indeterminate','applied',"
            "'not_applied','denied','quarantined','revoked')),generation INTEGER NOT "
            "NULL,readbacks INTEGER NOT NULL DEFAULT 0,deadline INTEGER NOT NULL,"
            "external_id TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)"
        )
        self.db.execute(
            "CREATE INDEX capability_payload_recovery ON "
            "capability_payload_operations(subject,state,operation_id)"
        )
        self.db.execute(
            "CREATE TABLE capability_payload_revoked_subjects("
            "subject TEXT PRIMARY KEY,revoked_at INTEGER NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE capability_payload_events("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT NOT NULL,"
            "event TEXT NOT NULL,generation INTEGER NOT NULL,created_at INTEGER NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO capability_payload_component VALUES(1,?,?)",
            (self.VERSION, secrets.token_hex(16)),
        )

    @staticmethod
    def _identifier(value: object, code: str = "capability_payload_binding_invalid") -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise CapabilityPayloadError(code)
        return value

    @staticmethod
    def _digest(value: object, code: str = "capability_payload_digest_invalid") -> str:
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise CapabilityPayloadError(code)
        return value

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise CapabilityPayloadError("capability_payload_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise CapabilityPayloadError("capability_payload_clock_invalid")
        return value

    def _payload(self, value: Mapping[str, object]) -> tuple[dict[str, object], bytes]:
        if type(value) is not dict or not value:
            raise CapabilityPayloadError("capability_payload_invalid")
        try:
            raw = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            decoded = json.loads(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise CapabilityPayloadError("capability_payload_invalid") from None
        if type(decoded) is not dict or len(raw) > self.maximum_payload_bytes:
            raise CapabilityPayloadError("capability_payload_invalid")
        return decoded, raw

    @staticmethod
    def _aad(
        operation_id: str,
        subject: str,
        provider_id: str,
        argument_digest: str,
        generation: int,
        deadline: int,
    ) -> bytes:
        return json.dumps(
            [
                operation_id,
                subject,
                provider_id,
                argument_digest,
                generation,
                deadline,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")

    @staticmethod
    def canonical_digest(value: Mapping[str, object]) -> str:
        try:
            raw = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise CapabilityPayloadError("capability_payload_invalid") from None
        return hashlib.sha256(raw).hexdigest()

    def prepare(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        subject: str,
        provider_id: str,
        payload: Mapping[str, object],
        lease_digest: str,
        deadline: int,
    ) -> RecoveryItem:
        operation_id = self._identifier(operation_id)
        idempotency_key = self._identifier(idempotency_key)
        subject = self._identifier(subject)
        provider_id = self._identifier(provider_id)
        lease_digest = self._digest(lease_digest)
        snapshot, raw = self._payload(payload)
        argument_digest = self.canonical_digest(snapshot)
        idempotency_digest = hashlib.sha256(
            json.dumps(
                [subject, idempotency_key], separators=(",", ":")
            ).encode("ascii")
        ).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(
                [operation_id, subject, provider_id, argument_digest, lease_digest, deadline],
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        with self._transaction():
            now = self._now()
            if (
                type(deadline) is not int
                or type(deadline) is bool
                or not now < deadline <= _MAX_TIME
            ):
                raise CapabilityPayloadError("capability_payload_deadline_invalid")
            if self.db.execute(
                "SELECT 1 FROM capability_payload_revoked_subjects WHERE subject=?",
                (subject,),
            ).fetchone():
                raise CapabilityPayloadError("capability_payload_subject_revoked")
            existing = self.db.execute(
                "SELECT * FROM capability_payload_operations WHERE idempotency_digest=?",
                (idempotency_digest,),
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise CapabilityPayloadError("capability_payload_idempotency_conflict")
                return self._item(existing)
            if self.db.execute(
                "SELECT COUNT(*) FROM capability_payload_operations"
            ).fetchone()[0] >= self.maximum_operations:
                raise CapabilityPayloadError("capability_payload_capacity_exhausted")
            try:
                key_id = self.cipher.current_key_id(subject=subject)
                self._identifier(key_id, "capability_payload_key_invalid")
                aad = self._aad(
                    operation_id,
                    subject,
                    provider_id,
                    argument_digest,
                    1,
                    deadline,
                )
                ciphertext = self.cipher.encrypt(
                    subject=subject,
                    key_id=key_id,
                    plaintext=raw,
                    aad=aad,
                )
            except CapabilityPayloadError:
                raise
            except Exception:
                raise CapabilityPayloadError("capability_payload_encrypt_failed") from None
            if not isinstance(ciphertext, (bytes, bytearray)) or not ciphertext:
                raise CapabilityPayloadError("capability_payload_encrypt_failed")
            self.db.execute(
                "INSERT INTO capability_payload_operations VALUES(?,?,?,?,?,?,?,?,?,?,"
                "'prepared',1,0,?,NULL,?,?)",
                (
                    operation_id,
                    idempotency_digest,
                    fingerprint,
                    subject,
                    provider_id,
                    argument_digest,
                    lease_digest,
                    key_id,
                    bytes(ciphertext),
                    hashlib.sha256(bytes(ciphertext)).hexdigest(),
                    deadline,
                    now,
                    now,
                ),
            )
            self._event(operation_id, "prepared", 1, now)
            return self._item(
                self.db.execute(
                    "SELECT * FROM capability_payload_operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
            )

    def _event(self, operation_id: str, event: str, generation: int, now: int) -> None:
        self.db.execute(
            "INSERT INTO capability_payload_events(operation_id,event,generation,created_at) "
            "VALUES(?,?,?,?)",
            (operation_id, event, generation, now),
        )

    @staticmethod
    def _item(row: sqlite3.Row) -> RecoveryItem:
        return RecoveryItem(
            operation_id=row["operation_id"],
            subject=row["subject"],
            provider_id=row["provider_id"],
            argument_digest=row["argument_digest"],
            state=row["state"],
            generation=row["generation"],
            readbacks=row["readbacks"],
            deadline=row["deadline"],
        )

    def _decode(self, row: sqlite3.Row) -> dict[str, object]:
        ciphertext = bytes(row["ciphertext"])
        if hashlib.sha256(ciphertext).hexdigest() != row["ciphertext_digest"]:
            raise CapabilityPayloadError("capability_payload_integrity_invalid")
        aad = self._aad(
            row["operation_id"],
            row["subject"],
            row["provider_id"],
            row["argument_digest"],
            row["generation"],
            row["deadline"],
        )
        try:
            raw = self.cipher.decrypt(
                subject=row["subject"],
                key_id=row["key_id"],
                ciphertext=ciphertext,
                aad=aad,
            )
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            raise CapabilityPayloadError("capability_payload_decrypt_failed") from None
        if type(value) is not dict or self.canonical_digest(value) != row["argument_digest"]:
            raise CapabilityPayloadError("capability_payload_integrity_invalid")
        return value

    def claim_dispatch(
        self,
        *,
        operation_id: str,
        subject: str,
        lease_digest: str,
        authorize: Callable[[], None],
    ) -> PayloadClaim:
        operation_id = self._identifier(operation_id)
        subject = self._identifier(subject)
        lease_digest = self._digest(lease_digest)
        if not callable(authorize):
            raise CapabilityPayloadError("capability_payload_authority_invalid")
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM capability_payload_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None or row["subject"] != subject:
                raise CapabilityPayloadError("capability_payload_unknown")
            if row["state"] != "prepared":
                raise CapabilityPayloadError("capability_payload_not_dispatchable")
            if row["deadline"] <= now:
                self.db.execute(
                    "UPDATE capability_payload_operations SET state='denied',"
                    "updated_at=? WHERE operation_id=?",
                    (now, operation_id),
                )
                self._event(operation_id, "deadline_denied", row["generation"], now)
                raise CapabilityPayloadError("capability_payload_expired")
            if row["lease_digest"] != lease_digest or self.db.execute(
                "SELECT 1 FROM capability_payload_revoked_subjects WHERE subject=?",
                (subject,),
            ).fetchone():
                raise CapabilityPayloadError("capability_payload_authority_denied")
            authorize()
            payload = self._decode(row)
            generation = row["generation"] + 1
            # Re-encrypt under generation-bound AAD before exposing the claim.
            key_id = self.cipher.current_key_id(subject=subject)
            self._identifier(key_id, "capability_payload_key_invalid")
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            try:
                ciphertext = self.cipher.encrypt(
                    subject=subject,
                    key_id=key_id,
                    plaintext=raw,
                    aad=self._aad(
                        operation_id,
                        subject,
                        row["provider_id"],
                        row["argument_digest"],
                        generation,
                        row["deadline"],
                    ),
                )
            except Exception:
                raise CapabilityPayloadError("capability_payload_encrypt_failed") from None
            self.db.execute(
                "UPDATE capability_payload_operations SET state='dispatching',"
                "generation=?,key_id=?,ciphertext=?,ciphertext_digest=?,updated_at=? "
                "WHERE operation_id=? AND state='prepared'",
                (
                    generation,
                    key_id,
                    bytes(ciphertext),
                    hashlib.sha256(bytes(ciphertext)).hexdigest(),
                    now,
                    operation_id,
                ),
            )
            self._event(operation_id, "dispatch_claimed", generation, now)
            authorize()
            return PayloadClaim(
                operation_id,
                subject,
                row["provider_id"],
                row["argument_digest"],
                generation,
                row["deadline"],
                payload,
            )

    def mark_indeterminate(self, *, operation_id: str, generation: int) -> None:
        operation_id = self._identifier(operation_id)
        if type(generation) is not int or generation < 1:
            raise CapabilityPayloadError("capability_payload_generation_invalid")
        with self._transaction():
            now = self._now()
            changed = self.db.execute(
                "UPDATE capability_payload_operations SET state='indeterminate',"
                "updated_at=? WHERE operation_id=? AND generation=? AND "
                "state='dispatching'",
                (now, operation_id, generation),
            ).rowcount
            if changed != 1:
                raise CapabilityPayloadError("capability_payload_state_conflict")
            self._event(operation_id, "indeterminate", generation, now)

    def claim_readback(
        self,
        *,
        operation_id: str,
        subject: str,
        authorize: Callable[[], None],
    ) -> PayloadClaim:
        operation_id = self._identifier(operation_id)
        subject = self._identifier(subject)
        if not callable(authorize):
            raise CapabilityPayloadError("capability_payload_authority_invalid")
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM capability_payload_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if (
                row is None
                or row["subject"] != subject
                or row["state"] not in {"dispatching", "indeterminate"}
            ):
                raise CapabilityPayloadError("capability_payload_not_recoverable")
            if row["readbacks"] >= self.maximum_readbacks:
                raise CapabilityPayloadError("capability_payload_readback_exhausted")
            if self.db.execute(
                "SELECT 1 FROM capability_payload_revoked_subjects WHERE subject=?",
                (subject,),
            ).fetchone():
                raise CapabilityPayloadError("capability_payload_subject_revoked")
            authorize()
            payload = self._decode(row)
            self.db.execute(
                "UPDATE capability_payload_operations SET readbacks=readbacks+1,"
                "updated_at=? WHERE operation_id=?",
                (now, operation_id),
            )
            self._event(operation_id, "readback_claimed", row["generation"], now)
            authorize()
            return PayloadClaim(
                operation_id,
                subject,
                row["provider_id"],
                row["argument_digest"],
                row["generation"],
                row["deadline"],
                payload,
            )

    def commit_observation(
        self,
        *,
        operation_id: str,
        generation: int,
        provider_id: str,
        argument_digest: str,
        disposition: str,
        terminal: bool,
        external_id: str | None = None,
    ) -> RecoveryItem:
        operation_id = self._identifier(operation_id)
        provider_id = self._identifier(provider_id)
        argument_digest = self._digest(argument_digest)
        if (
            type(generation) is not int
            or generation < 1
            or type(disposition) is not str
            or disposition not in {"applied", "not_applied", "unknown", "denied"}
            or type(terminal) is not bool
            or (external_id is not None and _IDENTIFIER.fullmatch(external_id) is None)
        ):
            raise CapabilityPayloadError("capability_payload_observation_invalid")
        with self._transaction():
            now = self._now()
            row = self.db.execute(
                "SELECT * FROM capability_payload_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if (
                row is None
                or row["generation"] != generation
                or row["provider_id"] != provider_id
                or row["argument_digest"] != argument_digest
                or row["state"] not in {"dispatching", "indeterminate"}
            ):
                raise CapabilityPayloadError("capability_payload_observation_conflict")
            if disposition == "unknown" or not terminal:
                next_state = "indeterminate"
            elif disposition in _TERMINAL:
                next_state = disposition
            else:
                next_state = "quarantined"
            self.db.execute(
                "UPDATE capability_payload_operations SET state=?,external_id=?,"
                "updated_at=? WHERE operation_id=?",
                (next_state, external_id, now, operation_id),
            )
            self._event(operation_id, "observation_" + next_state, generation, now)
            return self._item(
                self.db.execute(
                    "SELECT * FROM capability_payload_operations WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
            )

    def revoke_subject(self, *, subject: str) -> None:
        subject = self._identifier(subject)
        with self._transaction():
            now = self._now()
            self.db.execute(
                "INSERT INTO capability_payload_revoked_subjects VALUES(?,?) "
                "ON CONFLICT(subject) DO NOTHING",
                (subject, now),
            )
            rows = self.db.execute(
                "SELECT operation_id,generation FROM capability_payload_operations "
                "WHERE subject=? AND state IN ('prepared','dispatching','indeterminate')",
                (subject,),
            ).fetchall()
            self.db.execute(
                "UPDATE capability_payload_operations SET state='revoked',updated_at=? "
                "WHERE subject=? AND state IN ('prepared','dispatching','indeterminate')",
                (now, subject),
            )
            for row in rows:
                self._event(row["operation_id"], "subject_revoked", row["generation"], now)

    def recovery_inventory(
        self,
        *,
        subject: str,
        after_operation_id: str = "",
        limit: int = 100,
    ) -> list[RecoveryItem]:
        subject = self._identifier(subject)
        if (
            type(after_operation_id) is not str
            or (after_operation_id and _IDENTIFIER.fullmatch(after_operation_id) is None)
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise CapabilityPayloadError("capability_payload_page_invalid")
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM capability_payload_operations WHERE subject=? AND "
                "operation_id>? AND state IN ('dispatching','indeterminate') ORDER BY "
                "operation_id LIMIT ?",
                (subject, after_operation_id, limit),
            ).fetchall()
            return [self._item(row) for row in rows]

    def checkpoint(self) -> None:
        with self.lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
