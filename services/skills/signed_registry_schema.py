"""Fail-closed schema and local continuity for durable signed-Skill authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from services.control_plane.durable_state import timestamp
from services.skills.signed_package import (
    SignedSkillError,
    canonical,
    digest,
    fail,
    name,
    parse_manifest,
    sha256,
)


def _object_binding_supported() -> bool:
    required = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    return (
        os.name == "posix"
        and all(hasattr(os, value) for value in required)
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and Path("/proc/self/fd").is_dir()
    )


def _regular_file(value: os.stat_result) -> bool:
    return stat.S_ISREG(value.st_mode) and not stat.S_ISLNK(value.st_mode)


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


@dataclass(frozen=True)
class RegistryDatabaseBinding:
    absolute_path: str
    parent_path: str
    basename: str
    parent_fd: int
    file_fd: int
    parent_dev: int
    parent_ino: int
    file_dev: int
    file_ino: int


class BoundRegistryDatabase:
    """Bind SQLite to one held no-follow file object for its full lifetime.

    This is a trusted local Linux-host contract, not hostile-kernel or network
    filesystem isolation. A hard-linked database is rejected because an unseen
    alias defeats pathname custody.
    """

    def __init__(self, path: str, *, create: bool, initialize_schema: bool) -> None:
        if type(path) is not str or not path or path == ":memory:":
            fail("skill_registry_database_identity_invalid")
        if not _object_binding_supported():
            fail("skill_registry_database_identity_unavailable")
        absolute = os.path.abspath(path)
        parent_path, basename = os.path.split(absolute)
        if not basename or basename in (".", ".."):
            fail("skill_registry_database_identity_invalid")

        self.lock = threading.RLock()
        self.db: sqlite3.Connection | None = None
        parent_fd = file_fd = -1
        try:
            parent_fd = self._open_parent(parent_path, create=create)
            parent_before = os.fstat(parent_fd)
            if not stat.S_ISDIR(parent_before.st_mode):
                fail("skill_registry_database_identity_invalid")
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
            try:
                file_fd = os.open(basename, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                if not create:
                    fail("skill_registry_database_identity_invalid")
                try:
                    file_fd = os.open(
                        basename, flags | os.O_CREAT | os.O_EXCL, 0o600,
                        dir_fd=parent_fd,
                    )
                except OSError:
                    fail("skill_registry_database_identity_invalid")
            except OSError:
                fail("skill_registry_database_identity_invalid")
            opened = os.fstat(file_fd)
            if not _regular_file(opened) or opened.st_nlink != 1:
                fail("skill_registry_database_identity_invalid")
            self.binding = RegistryDatabaseBinding(
                absolute, parent_path, basename, parent_fd, file_fd,
                parent_before.st_dev, parent_before.st_ino,
                opened.st_dev, opened.st_ino,
            )
            self.identity = (opened.st_dev, opened.st_ino)
            parent_ctime = os.fstat(parent_fd).st_ctime_ns
            try:
                db = sqlite3.connect(
                    f"/proc/self/fd/{file_fd}", isolation_level=None,
                    check_same_thread=False, timeout=5,
                )
            except sqlite3.DatabaseError:
                fail("skill_registry_storage_integrity_invalid")
            self.db = db
            self._closed = False
            db.row_factory = sqlite3.Row
            # Before any PRAGMA/schema write, bind the SQLite-opened object to
            # the held inode and reject connect-interval pathname ABA.
            self._verify_identity(initial_parent_ctime=parent_ctime)
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA synchronous=FULL")
                if initialize_schema:
                    mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    if mode != "wal" or db.execute("PRAGMA synchronous").fetchone()[0] != 2:
                        fail("skill_registry_storage_configuration_unavailable")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS hepta_component_schema("
                        "component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
                    )
                self.verify_identity()
            except sqlite3.DatabaseError:
                fail("skill_registry_storage_integrity_invalid")
        except BaseException:
            if self.db is not None:
                self.db.close()
                self.db = None
            if file_fd >= 0:
                os.close(file_fd)
            if parent_fd >= 0:
                os.close(parent_fd)
            raise

    @staticmethod
    def _open_parent(parent_path: str, *, create: bool) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            current = os.open("/", flags)
            for component in (part for part in parent_path.split(os.sep) if part):
                try:
                    next_fd = os.open(component, flags, dir_fd=current)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                    next_fd = os.open(component, flags, dir_fd=current)
                os.close(current)
                current = next_fd
            return current
        except OSError:
            try:
                if "current" in locals() and current >= 0:
                    os.close(current)
            except OSError:
                pass
            fail("skill_registry_database_identity_invalid")
        raise AssertionError("unreachable")

    def _verify_identity(self, *, initial_parent_ctime: int | None = None) -> None:
        binding = self.binding
        try:
            held_parent = os.fstat(binding.parent_fd)
            named_parent = os.stat(binding.parent_path, follow_symlinks=False)
            held_file = os.fstat(binding.file_fd)
            relative_file = os.stat(
                binding.basename, dir_fd=binding.parent_fd, follow_symlinks=False,
            )
            absolute_file = os.stat(binding.absolute_path, follow_symlinks=False)
        except OSError:
            fail("skill_registry_database_replaced")
        if (
            not stat.S_ISDIR(held_parent.st_mode)
            or not stat.S_ISDIR(named_parent.st_mode)
            or (held_parent.st_dev, held_parent.st_ino)
                != (binding.parent_dev, binding.parent_ino)
            or not _same_object(held_parent, named_parent)
            or not _regular_file(held_file)
            or not _regular_file(relative_file)
            or not _regular_file(absolute_file)
            or held_file.st_nlink != 1
            or relative_file.st_nlink != 1
            or absolute_file.st_nlink != 1
            or (held_file.st_dev, held_file.st_ino)
                != (binding.file_dev, binding.file_ino)
            or not _same_object(held_file, relative_file)
            or not _same_object(held_file, absolute_file)
            or (initial_parent_ctime is not None
                and held_parent.st_ctime_ns != initial_parent_ctime)
        ):
            fail("skill_registry_database_replaced")

    def verify_identity(self) -> None:
        self._verify_identity()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.db is None:
            fail("skill_registry_storage_integrity_invalid")
        with self.lock:
            self.verify_identity()
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.verify_identity()
                yield self.db
                self.verify_identity()
                self.db.execute("COMMIT")
                self.verify_identity()
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def version(self, component: str, expected: int) -> bool:
        if self.db is None:
            fail("skill_registry_storage_integrity_invalid")
        row = self.db.execute(
            "SELECT version FROM hepta_component_schema WHERE component=?",
            (component,),
        ).fetchone()
        if row is not None and row["version"] != expected:
            raise ValueError(f"{component}_schema_migration_required")
        return row is None

    def mark_version(self, component: str, version: int) -> None:
        if self.db is None:
            fail("skill_registry_storage_integrity_invalid")
        self.db.execute(
            "INSERT OR IGNORE INTO hepta_component_schema VALUES(?,?)",
            (component, version),
        )

    def close(self) -> None:
        with self.lock:
            if getattr(self, "_closed", False):
                return
            self._closed = True
            db, self.db = self.db, None
            if db is not None:
                db.close()
            for descriptor in (self.binding.file_fd, self.binding.parent_fd):
                try:
                    os.close(descriptor)
                except OSError:
                    pass


STATE_COMPONENT = "signed_skills_state"
STATE_VERSION = 1
STATE_TABLE = "signed_skill_state"
LEGACY_TABLES = frozenset(
    {
        "signed_skill_policy",
        "signed_skill_keys",
        "signed_skill_installed",
        "signed_skill_revocations",
        "signed_skill_events",
    }
)
REQUIRED_TABLES = LEGACY_TABLES | {STATE_TABLE}

CREATE_STATEMENTS = (
    "CREATE TABLE signed_skill_policy(id INTEGER PRIMARY KEY CHECK(id=1),policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
    "CREATE TABLE signed_skill_keys(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,binding BLOB NOT NULL)",
    "CREATE TABLE signed_skill_installed(id TEXT PRIMARY KEY,document BLOB NOT NULL,signature BLOB NOT NULL,digest TEXT NOT NULL,consent_expires_at INTEGER NOT NULL,event_sequence INTEGER NOT NULL)",
    "CREATE TABLE signed_skill_revocations(kind TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(kind,target))",
    "CREATE TABLE signed_skill_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,target TEXT NOT NULL,digest TEXT NOT NULL,observed_at INTEGER NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)",
    "CREATE TABLE signed_skill_state(id INTEGER PRIMARY KEY CHECK(id=1),instance_id TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL CHECK(revision>=0),authority_digest TEXT NOT NULL)",
)

EXPECTED_COLUMNS = {
    "signed_skill_policy": (("id", "INTEGER", 0, 1), ("policy", "BLOB", 1, 0),
                            ("last_time", "INTEGER", 1, 0), ("suspended", "INTEGER", 1, 0)),
    "signed_skill_keys": (("id", "TEXT", 0, 1), ("fingerprint", "TEXT", 1, 0),
                          ("binding", "BLOB", 1, 0)),
    "signed_skill_installed": (("id", "TEXT", 0, 1), ("document", "BLOB", 1, 0),
        ("signature", "BLOB", 1, 0), ("digest", "TEXT", 1, 0),
        ("consent_expires_at", "INTEGER", 1, 0), ("event_sequence", "INTEGER", 1, 0)),
    "signed_skill_revocations": (("kind", "TEXT", 1, 1), ("target", "TEXT", 1, 2)),
    "signed_skill_events": (("sequence", "INTEGER", 0, 1), ("event", "TEXT", 1, 0),
        ("target", "TEXT", 1, 0), ("digest", "TEXT", 1, 0),
        ("observed_at", "INTEGER", 1, 0), ("previous_hash", "TEXT", 1, 0),
        ("event_hash", "TEXT", 1, 0)),
    "signed_skill_state": (("id", "INTEGER", 0, 1), ("instance_id", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0), ("authority_digest", "TEXT", 1, 0)),
}

_AUTHORITY_COLUMNS = (
    ("signed_skill_policy", ("id", "policy", "last_time", "suspended"), "id"),
    ("signed_skill_keys", ("id", "fingerprint", "binding"), "id"),
    ("signed_skill_installed", ("id", "document", "signature", "digest", "consent_expires_at", "event_sequence"), "id"),
    ("signed_skill_revocations", ("kind", "target"), "kind,target"),
    ("signed_skill_events", ("sequence", "event", "target", "digest", "observed_at", "previous_hash", "event_hash"), "sequence"),
)


@dataclass(frozen=True)
class RegistryStateAnchor:
    """Host-retained checkpoint. Client JSON is never authority for this value."""

    instance_id: str
    revision: int
    authority_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.instance_id) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.instance_id)
            or type(self.revision) is not int
            or type(self.revision) is bool
            or self.revision < 1
            or type(self.authority_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.authority_digest)
        ):
            fail("skill_registry_state_anchor_invalid")


@dataclass(frozen=True)
class RegistryStateCheckpoint:
    instance_id: str
    revision: int
    authority_digest: str
    anchor_floor_satisfied: bool
    anchor_exact: bool
    external_evidence: bool = False


def _columns(db: sqlite3.Connection, table: str) -> tuple[tuple[str, str, int, int], ...]:
    return tuple((row[1], str(row[2]).upper(), row[3], row[5])
                 for row in db.execute(f"PRAGMA table_info({table})"))


def _unique_columns(db: sqlite3.Connection, table: str, expected: tuple[str, ...]) -> bool:
    for row in db.execute(f"PRAGMA index_list({table})"):
        if row[2] != 1 or (len(row) > 4 and row[4] != 0):
            continue
        columns = tuple(item[2] for item in db.execute(f"PRAGMA index_info({row[1]})"))
        if columns == expected:
            return True
    return False


def _table_sql(db: sqlite3.Connection, table: str) -> str:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return "" if row is None else "".join(str(row[0]).upper().split())


def _validate_common(
    db: sqlite3.Connection,
    *,
    expected_tables: frozenset[str],
    policy: bytes | None,
) -> bytes:
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    owned = {table for table in tables if table.startswith("signed_skill_")}
    if owned != expected_tables:
        fail("skill_registry_schema_integrity_invalid")
    if any(_columns(db, table) != EXPECTED_COLUMNS[table]
           for table in expected_tables):
        fail("skill_registry_schema_integrity_invalid")
    if not _unique_columns(db, "signed_skill_keys", ("fingerprint",)):
        fail("skill_registry_schema_integrity_invalid")
    if "AUTOINCREMENT" not in _table_sql(db, "signed_skill_events"):
        fail("skill_registry_schema_integrity_invalid")
    if "CHECK(ID=1)" not in _table_sql(db, "signed_skill_policy"):
        fail("skill_registry_schema_integrity_invalid")
    if STATE_TABLE in expected_tables:
        state_sql = _table_sql(db, STATE_TABLE)
        if ("CHECK(ID=1)" not in state_sql
                or "CHECK(REVISION>=0)" not in state_sql
                or not _unique_columns(db, STATE_TABLE, ("instance_id",))):
            fail("skill_registry_schema_integrity_invalid")

    rows = db.execute(
        "SELECT id,policy,last_time,suspended FROM signed_skill_policy"
    ).fetchall()
    try:
        if (len(rows) != 1 or rows[0]["id"] != 1
                or not timestamp(rows[0]["last_time"])
                or type(rows[0]["suspended"]) is not int
                or rows[0]["suspended"] not in (0, 1)):
            fail("skill_registry_schema_integrity_invalid")
        stored_policy = bytes(rows[0]["policy"])
    except (TypeError, ValueError, IndexError, KeyError):
        fail("skill_registry_schema_integrity_invalid")
    if policy is not None and stored_policy != policy:
        fail("skill_registry_policy_migration_required")
    return stored_policy


def validate_legacy_schema(db: sqlite3.Connection, policy: bytes | None = None) -> bytes:
    """Validate the exact pre-continuity five-table layout for offline migration."""
    try:
        return _validate_common(db, expected_tables=LEGACY_TABLES, policy=policy)
    except sqlite3.DatabaseError:
        fail("skill_registry_schema_integrity_invalid")
    raise AssertionError("unreachable")


def ensure_signed_skill_schema(db: sqlite3.Connection, *, fresh: bool,
                               policy: bytes, now: int | None = None) -> None:
    """Initialize a truly fresh component or validate every established table."""
    try:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        owned = {table for table in tables if table.startswith("signed_skill_")}
        if fresh:
            if owned:
                fail("skill_unmarked_schema_rejected")
            if now is None or not timestamp(now):
                fail("skill_clock_invalid")
            for statement in CREATE_STATEMENTS:
                db.execute(statement)
            db.execute("INSERT INTO signed_skill_policy VALUES(1,?,?,0)", (policy, now))
            db.execute(
                "INSERT INTO signed_skill_state VALUES(1,?,0,?)",
                ("0" * 64, "0" * 64),
            )
            return

        _validate_common(db, expected_tables=REQUIRED_TABLES, policy=policy)
        rows = db.execute(
            "SELECT id,instance_id,revision,authority_digest FROM signed_skill_state"
        ).fetchall()
        if (len(rows) != 1 or rows[0]["id"] != 1
                or type(rows[0]["instance_id"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", rows[0]["instance_id"])
                or type(rows[0]["revision"]) is not int
                or type(rows[0]["revision"]) is bool
                or rows[0]["revision"] < 1
                or type(rows[0]["authority_digest"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", rows[0]["authority_digest"])):
            fail("skill_registry_schema_integrity_invalid")
    except sqlite3.DatabaseError:
        fail("skill_registry_schema_integrity_invalid")


def database_identity(path: str) -> tuple[int, int]:
    """Legacy pathname helper retained for compatibility; not a connection binding."""
    try:
        value = os.lstat(path)
    except OSError:
        fail("skill_registry_database_identity_invalid")
    if not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode):
        fail("skill_registry_database_identity_invalid")
    return value.st_dev, value.st_ino


def verify_database_identity(path: str, expected: tuple[int, int]) -> None:
    if database_identity(path) != expected:
        fail("skill_registry_database_replaced")


def _frame(hasher, value: object) -> None:
    if value is None:
        hasher.update(b"N")
        return
    if type(value) is int:
        raw, marker = str(value).encode("ascii"), b"I"
    elif type(value) is str:
        try:
            raw = value.encode("utf-8")
        except UnicodeError:
            fail("skill_registry_state_integrity_invalid")
        marker = b"S"
    elif type(value) is bytes:
        raw, marker = value, b"B"
    else:
        fail("skill_registry_state_integrity_invalid")
    hasher.update(marker)
    hasher.update(len(raw).to_bytes(8, "big"))
    hasher.update(raw)


def authority_digest(db: sqlite3.Connection) -> str:
    """Stream a deterministic digest of all local authority rows."""
    hasher = hashlib.sha256(b"HEPTA-SIGNED-SKILL-STATE-V1\0")
    try:
        for table, columns, order in _AUTHORITY_COLUMNS:
            _frame(hasher, table)
            count = 0
            for row in db.execute(
                f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"
            ):
                hasher.update(b"R")
                for value in row:
                    _frame(hasher, value)
                count += 1
            hasher.update(b"E")
            hasher.update(count.to_bytes(8, "big"))
        sequence = db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='signed_skill_events'"
        ).fetchone()
        _frame(hasher, -1 if sequence is None else sequence[0])
    except sqlite3.DatabaseError:
        fail("skill_registry_storage_integrity_invalid")
    return hasher.hexdigest()


def _canonical_object(raw: bytes, *, code: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
        if type(value) is not dict or canonical(value) != raw:
            fail(code)
        return value
    except SignedSkillError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        fail(code)
    raise AssertionError("unreachable")


def validate_authority_rows(db: sqlite3.Connection) -> None:
    """Reject structurally valid tables containing malformed authority facts."""
    try:
        if [tuple(row) for row in db.execute("PRAGMA quick_check").fetchall()] != [("ok",)]:
            fail("skill_registry_storage_integrity_invalid")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            fail("skill_registry_storage_integrity_invalid")

        rows = db.execute(
            "SELECT policy,last_time,suspended FROM signed_skill_policy"
        ).fetchall()
        if len(rows) != 1:
            fail("skill_registry_state_integrity_invalid")
        policy = _canonical_object(bytes(rows[0][0]), code="skill_registry_state_integrity_invalid")
        if (
            not {"subject", "capabilities", "domains", "maximum_entries"} <= set(policy)
            or not set(policy) <= {"subject", "capabilities", "domains", "maximum_entries", "transparency"}
            or name(policy["subject"]) != policy["subject"]
            or type(policy["capabilities"]) is not list
            or type(policy["domains"]) is not list
            or policy["capabilities"] != sorted(set(policy["capabilities"]))
            or policy["domains"] != sorted(set(policy["domains"]))
            or any(name(item) != item for item in policy["capabilities"] + policy["domains"])
            or type(policy["maximum_entries"]) is not int
            or type(policy["maximum_entries"]) is bool
            or not 1 <= policy["maximum_entries"] <= 10000
            or ("transparency" in policy and digest(policy["transparency"]) != policy["transparency"])
            or not timestamp(rows[0][1])
            or type(rows[0][2]) is not int
            or rows[0][2] not in (0, 1)
        ):
            fail("skill_registry_state_integrity_invalid")

        key_rows = db.execute(
            "SELECT id,fingerprint,binding FROM signed_skill_keys"
        ).fetchall()
        if not 1 <= len(key_rows) <= 32:
            fail("skill_registry_state_integrity_invalid")
        for key_id, fingerprint, binding_raw in key_rows:
            name(key_id)
            digest(fingerprint)
            binding = _canonical_object(bytes(binding_raw), code="skill_registry_state_integrity_invalid")
            if (
                set(binding) != {"publisher", "not_before", "not_after"}
                or name(binding["publisher"]) != binding["publisher"]
                or not timestamp(binding["not_before"])
                or not timestamp(binding["not_after"])
                or binding["not_before"] >= binding["not_after"]
            ):
                fail("skill_registry_state_integrity_invalid")

        events: dict[int, tuple[str, str, str, int]] = {}
        revocation_events: set[tuple[str, str]] = set()
        suspended_events = 0
        installed_events = 0
        previous, expected_sequence, previous_time = "", 1, 0
        for row in db.execute(
            "SELECT sequence,event,target,digest,observed_at,previous_hash,event_hash "
            "FROM signed_skill_events ORDER BY sequence"
        ):
            sequence, event, target, object_digest, observed_at, prior, event_hash = row
            if (
                type(sequence) is not int or sequence != expected_sequence
                or type(event) is not str or type(target) is not str
                or type(object_digest) is not str or not timestamp(observed_at)
                or observed_at < previous_time or observed_at > rows[0][1]
                or prior != previous or type(event_hash) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", event_hash)
            ):
                fail("skill_registry_state_integrity_invalid")
            body = [sequence, event, target, object_digest, observed_at, prior]
            if sha256(canonical(body)) != event_hash:
                fail("skill_registry_state_integrity_invalid")
            if event == "installed":
                name(target); digest(object_digest)
                installed_events += 1
            elif event.startswith("revoked."):
                kind = event.removeprefix("revoked.")
                if kind not in {"skill", "publisher", "key", "package"} or object_digest != "":
                    fail("skill_registry_state_integrity_invalid")
                digest(target) if kind == "package" else name(target)
                if (kind, target) in revocation_events:
                    fail("skill_registry_state_integrity_invalid")
                revocation_events.add((kind, target))
            elif event == "suspended":
                if target != "registry" or object_digest != "":
                    fail("skill_registry_state_integrity_invalid")
                suspended_events += 1
                if suspended_events > 1:
                    fail("skill_registry_state_integrity_invalid")
            else:
                fail("skill_registry_state_integrity_invalid")
            events[sequence] = (event, target, object_digest, observed_at)
            previous = event_hash
            previous_time = observed_at
            expected_sequence += 1
        sequence_row = db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='signed_skill_events'"
        ).fetchone()
        if ((expected_sequence == 1 and sequence_row is not None)
                or (expected_sequence > 1 and (sequence_row is None
                    or type(sequence_row[0]) is not int
                    or sequence_row[0] != expected_sequence - 1))
                or installed_events > policy["maximum_entries"]):
            fail("skill_registry_state_integrity_invalid")

        installed_rows = db.execute(
            "SELECT id,document,signature,digest,consent_expires_at,event_sequence "
            "FROM signed_skill_installed"
        ).fetchall()
        if len(installed_rows) > policy["maximum_entries"]:
            fail("skill_registry_state_integrity_invalid")
        for skill_id, document, signature, document_digest, expiry, event_sequence in installed_rows:
            name(skill_id)
            if type(document) is not bytes or type(signature) is not bytes or len(signature) != 64:
                fail("skill_registry_state_integrity_invalid")
            manifest = parse_manifest(document)
            if manifest["skill_id"] != skill_id or sha256(document) != document_digest:
                fail("skill_registry_state_integrity_invalid")
            digest(document_digest)
            if not timestamp(expiry) or expiry > manifest["expires_at"]:
                fail("skill_registry_state_integrity_invalid")
            event = events.get(event_sequence)
            if event is None or event[:3] != ("installed", skill_id, document_digest):
                fail("skill_registry_state_integrity_invalid")

        revocations = set()
        for kind, target in db.execute("SELECT kind,target FROM signed_skill_revocations"):
            if kind not in {"skill", "publisher", "key", "package"}:
                fail("skill_registry_state_integrity_invalid")
            digest(target) if kind == "package" else name(target)
            revocations.add((kind, target))
        if (revocations != revocation_events
                or len(revocations) > policy["maximum_entries"]):
            fail("skill_registry_state_integrity_invalid")
        if bool(rows[0][2]) != bool(suspended_events):
            fail("skill_registry_state_integrity_invalid")
    except SignedSkillError as error:
        if error.code == "skill_registry_storage_integrity_invalid":
            raise
        fail("skill_registry_state_integrity_invalid")
    except (sqlite3.DatabaseError, TypeError, ValueError, UnicodeError, IndexError, KeyError):
        fail("skill_registry_state_integrity_invalid")


def _state_row(db: sqlite3.Connection) -> tuple[str, int, str]:
    try:
        rows = db.execute(
            "SELECT instance_id,revision,authority_digest FROM signed_skill_state"
        ).fetchall()
    except sqlite3.DatabaseError:
        fail("skill_registry_storage_integrity_invalid")
    if len(rows) != 1:
        fail("skill_registry_state_integrity_invalid")
    instance_id, revision, stored_digest = rows[0]
    if (
        type(instance_id) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", instance_id)
        or type(revision) is not int or type(revision) is bool or revision < 1
        or type(stored_digest) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", stored_digest)
    ):
        fail("skill_registry_state_integrity_invalid")
    return instance_id, revision, stored_digest


def verify_registry_state(
    db: sqlite3.Connection,
    anchor: RegistryStateAnchor | None,
    *,
    deep: bool = False,
) -> RegistryStateCheckpoint:
    if anchor is not None and type(anchor) is not RegistryStateAnchor:
        fail("skill_registry_state_anchor_invalid")
    instance_id, revision, stored_digest = _state_row(db)
    actual = authority_digest(db)
    if actual != stored_digest:
        fail("skill_registry_state_integrity_invalid")
    if deep:
        validate_authority_rows(db)
    exact = False
    if anchor is not None:
        if instance_id != anchor.instance_id:
            fail("skill_registry_state_instance_mismatch")
        if revision < anchor.revision:
            fail("skill_registry_state_rollback")
        if revision == anchor.revision:
            if stored_digest != anchor.authority_digest:
                fail("skill_registry_state_fork")
            exact = True
    return RegistryStateCheckpoint(
        instance_id, revision, stored_digest, anchor is not None, exact, False
    )


def initialize_registry_state(db: sqlite3.Connection) -> RegistryStateCheckpoint:
    instance_id = secrets.token_hex(32)
    initial = authority_digest(db)
    try:
        updated = db.execute(
            "UPDATE signed_skill_state SET instance_id=?,revision=1,authority_digest=? "
            "WHERE id=1 AND revision=0",
            (instance_id, initial),
        )
    except sqlite3.DatabaseError:
        fail("skill_registry_storage_integrity_invalid")
    if updated.rowcount != 1:
        fail("skill_registry_state_integrity_invalid")
    return RegistryStateCheckpoint(instance_id, 1, initial, False, False, False)


def seal_registry_state(
    db: sqlite3.Connection, prior: RegistryStateCheckpoint
) -> RegistryStateCheckpoint:
    current = authority_digest(db)
    if current == prior.authority_digest:
        return prior
    revision = prior.revision + 1
    try:
        updated = db.execute(
            "UPDATE signed_skill_state SET revision=?,authority_digest=? "
            "WHERE id=1 AND instance_id=? AND revision=? AND authority_digest=?",
            (revision, current, prior.instance_id, prior.revision, prior.authority_digest),
        )
    except sqlite3.DatabaseError:
        fail("skill_registry_storage_integrity_invalid")
    if updated.rowcount != 1:
        fail("skill_registry_state_conflict")
    return RegistryStateCheckpoint(
        prior.instance_id, revision, current,
        prior.anchor_floor_satisfied, False, False,
    )


def migrate_signed_skills_v1(path: str) -> dict[str, object]:
    """Add continuity metadata to an intact five-table registry, offline."""
    if type(path) is not str or not path or path == ":memory:":
        fail("skill_registry_migration_path_invalid")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        fail("skill_registry_migration_existing_file_required")
    storage = BoundRegistryDatabase(path, create=False, initialize_schema=False)
    try:
        db = storage.db
        if db is None:
            fail("skill_registry_storage_integrity_invalid")
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            fail("skill_registry_migration_wal_required")
        with storage.transaction() as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            owned = {table for table in tables if table.startswith("signed_skill_")}
            if owned != LEGACY_TABLES:
                fail("skill_registry_migration_schema_invalid")
            marker = db.execute(
                "SELECT version FROM hepta_component_schema WHERE component='signed_skills'"
            ).fetchone()
            state_marker = db.execute(
                "SELECT version FROM hepta_component_schema WHERE component=?",
                (STATE_COMPONENT,),
            ).fetchone()
            if marker is None or marker[0] != 1 or state_marker is not None:
                fail("skill_registry_migration_version_invalid")
            validate_legacy_schema(db)
            validate_authority_rows(db)
            counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                      for table in sorted(LEGACY_TABLES)}
            db.execute(CREATE_STATEMENTS[-1])
            db.execute("INSERT INTO signed_skill_state VALUES(1,?,0,?)",
                       ("0" * 64, "0" * 64))
            checkpoint = initialize_registry_state(db)
            db.execute(
                "INSERT INTO hepta_component_schema(component,version) VALUES(?,?)",
                (STATE_COMPONENT, STATE_VERSION),
            )
            storage.verify_identity()
        storage.verify_identity()
        return {
            "component": "signed_skills",
            "state_component": STATE_COMPONENT,
            "state_version": STATE_VERSION,
            "instance_id": checkpoint.instance_id,
            "revision": checkpoint.revision,
            "authority_digest": checkpoint.authority_digest,
            "preserved_rows": counts,
            "old_processes_stopped_verified": False,
            "external_anchor_verified": False,
            "object_bound_sqlite": True,
        }
    except SignedSkillError:
        raise
    except sqlite3.DatabaseError:
        fail("skill_registry_storage_integrity_invalid")
    finally:
        storage.close()
