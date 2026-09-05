"""Bounded signed Skill package format; validates bytes, never executes/extracts.

Linux/system OpenSSL verification uses externally pinned Ed25519 public keys.
This is a distinct format: legacy HMAC manifests are not accepted or upgraded.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from services.control_plane.durable_state import timestamp
from tools.external_evidence.openssl_policy import (
    trusted_openssl_path, trusted_subprocess_environment,
)

PREFIX = b"HEPTA-SKILL-PACKAGE-V1\n"
MAX_DOCUMENT = 32768
MAX_PACKAGE = 16 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_FILES = 128
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
_FIELDS = frozenset({"schema_version", "skill_id", "version", "publisher", "key_id",
    "entrypoint", "capabilities", "data_classes", "network_domains", "risk_tier",
    "timeout_ms", "issued_at", "expires_at", "package_sha256", "files", "dependencies"})


class SignedSkillError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fail(code: str) -> None:
    raise SignedSkillError(code)


def name(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,95}", value):
        fail("skill_name_invalid")
    return value


def digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail("skill_digest_invalid")
    return value


def version(value: object) -> tuple[int, int, int]:
    if type(value) is not str or not re.fullmatch(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})", value):
        fail("skill_version_invalid")
    return tuple(int(x) for x in value.split("."))


def package_path(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 240:
        fail("skill_package_path_invalid")
    parts = value.split("/")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
    for part in parts:
        if (not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part)
                or part.endswith(".") or part.split(".")[0].lower() in reserved):
            fail("skill_package_path_invalid")
    return value


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _array(value: object, *, maximum: int = 64) -> list:
    if type(value) is not list or len(value) > maximum:
        fail("skill_manifest_array_invalid")
    return value


def _names(value: object) -> list[str]:
    values = _array(value)
    for item in values:
        name(item)
    if values != sorted(set(values)):
        fail("skill_manifest_set_invalid")
    return values


def parse_manifest(raw: bytes) -> dict:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_DOCUMENT:
        fail("skill_manifest_size_invalid")
    def pairs(items):
        out = {}
        for key, val in items:
            if key in out:
                fail("skill_manifest_duplicate_key")
            out[key] = val
        return out
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: fail("skill_manifest_nonfinite"))
        if type(value) is not dict or set(value) != _FIELDS or canonical(value) != raw:
            fail("skill_manifest_format_invalid")
    except (ValueError, UnicodeError, RecursionError, TypeError) as error:
        if isinstance(error, SignedSkillError):
            raise
        raise SignedSkillError("skill_manifest_format_invalid") from None
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        fail("skill_manifest_version_invalid")
    for field in ("skill_id", "publisher", "key_id"):
        name(value[field])
    version(value["version"])
    package_path(value["entrypoint"])
    for field in ("capabilities", "data_classes", "network_domains"):
        _names(value[field])
    if not set(value["data_classes"]) <= {"public", "personal", "sensitive"}:
        fail("skill_data_class_invalid")
    for domain in value["network_domains"]:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+", domain):
            fail("skill_network_domain_invalid")
    if type(value["risk_tier"]) is not str or value["risk_tier"] not in {"R0", "R1", "R2", "R3"}:
        fail("skill_risk_invalid")
    if type(value["timeout_ms"]) is not int or not 1 <= value["timeout_ms"] <= 300000:
        fail("skill_timeout_invalid")
    if (not timestamp(value["issued_at"]) or not timestamp(value["expires_at"])
            or not 0 < value["expires_at"] - value["issued_at"] <= 2592000):
        fail("skill_manifest_time_invalid")
    digest(value["package_sha256"])
    files = _array(value["files"], maximum=MAX_FILES)
    paths = []
    for file in files:
        if type(file) is not dict or set(file) != {"path", "size", "sha256"}:
            fail("skill_file_inventory_invalid")
        paths.append(package_path(file["path"]))
        if type(file["size"]) is not int or not 0 <= file["size"] <= MAX_FILE:
            fail("skill_file_size_invalid")
        digest(file["sha256"])
    if (not files or paths != sorted(set(paths)) or len({p.lower() for p in paths}) != len(paths)
            or value["entrypoint"] not in paths or sum(f["size"] for f in files) > MAX_PACKAGE):
        fail("skill_file_inventory_invalid")
    lowered = {p.lower() for p in paths}
    if any("/".join(p.lower().split("/")[:i]) in lowered for p in paths for i in range(1, len(p.split("/")))):
        fail("skill_file_directory_conflict")
    dependencies = _array(value["dependencies"], maximum=32)
    ids = []
    for dep in dependencies:
        if type(dep) is not dict or set(dep) != {"skill_id", "version", "manifest_sha256"}:
            fail("skill_dependency_invalid")
        ids.append(name(dep["skill_id"]))
        version(dep["version"])
        digest(dep["manifest_sha256"])
    if ids != sorted(set(ids)) or value["skill_id"] in ids:
        fail("skill_dependency_invalid")
    return value


def inspect_package(manifest: dict, raw: bytes) -> tuple[tuple[str, bytes], ...]:
    if type(raw) is not bytes or not 22 <= len(raw) <= MAX_PACKAGE:
        fail("skill_package_size_invalid")
    if sha256(raw) != manifest["package_sha256"]:
        fail("skill_package_digest_mismatch")
    # Bound entry count before ZipFile allocates the central-directory objects.
    end = struct.unpack("<4s4H2LH", raw[-22:])
    if (end[0] != b"PK\x05\x06" or end[1:3] != (0, 0) or end[3] != end[4]
            or not 1 <= end[4] <= MAX_FILES or end[7] != 0
            or end[5] > MAX_FILES * 512 or end[5] + end[6] != len(raw) - 22):
        fail("skill_archive_layout_invalid")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) != len(manifest["files"]) or len(infos) != end[4] or archive.comment:
                fail("skill_archive_inventory_mismatch")
            expected = {f["path"]: f for f in manifest["files"]}
            seen = set()
            result = []
            position = 0
            for info in infos:
                path = package_path(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if (info.orig_filename != path or path in seen or path not in expected
                        or info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or info.compress_type != zipfile.ZIP_STORED or info.flag_bits & ~0x800
                        or info.extra or info.comment or info.volume != 0
                        or info.file_size != expected[path]["size"] or info.compress_size != info.file_size
                        or info.header_offset != position):
                    fail("skill_archive_member_invalid")
                # No data descriptors, prefixes, extra fields, hidden local members or gaps.
                local = raw[position:position + 30]
                if len(local) != 30:
                    fail("skill_archive_layout_invalid")
                fields = struct.unpack("<4s5H3L2H", local)
                if (fields[0] != b"PK\x03\x04" or fields[2] != info.flag_bits
                        or fields[3] != info.compress_type or fields[6] != info.CRC
                        or fields[7:9] != (info.compress_size, info.file_size)
                        or fields[9:] != (len(path.encode("ascii")), 0)):
                    fail("skill_archive_layout_invalid")
                position += 30 + fields[9]
                if raw[position - fields[9]:position] != path.encode("ascii"):
                    fail("skill_archive_member_invalid")
                position += info.compress_size
                with archive.open(info) as handle:
                    data = handle.read(MAX_FILE + 1)
                if len(data) != expected[path]["size"] or sha256(data) != expected[path]["sha256"]:
                    fail("skill_file_digest_mismatch")
                seen.add(path)
                result.append((path, data))
            if position != end[6] or seen != set(expected):
                fail("skill_archive_inventory_mismatch")
            return tuple(sorted(result))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, ValueError, struct.error) as error:
        if isinstance(error, SignedSkillError):
            raise
        raise SignedSkillError("skill_archive_invalid") from None


@dataclass(frozen=True)
class PublisherKey:
    publisher: str
    public_der: bytes
    not_before: int
    not_after: int

    def __post_init__(self) -> None:
        name(self.publisher)
        if (type(self.public_der) is not bytes or len(self.public_der) != 44
                or not self.public_der.startswith(SPKI_PREFIX)
                or not timestamp(self.not_before) or not timestamp(self.not_after)
                or self.not_before >= self.not_after):
            fail("skill_public_key_invalid")


@contextmanager
def sealed_inputs(values: tuple[bytes, ...]) -> Iterator[tuple[int, ...]]:
    import fcntl
    if not hasattr(os, "memfd_create") or not hasattr(fcntl, "F_ADD_SEALS"):
        fail("skill_verifier_platform_unsupported")
    descriptors = []
    try:
        for value in values:
            fd = os.memfd_create("hepta-skill-verification", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            descriptors.append(fd)
            data = memoryview(value)
            while data:
                written = os.write(fd, data)
                if written <= 0:
                    fail("skill_verifier_io_unavailable")
                data = data[written:]
            os.lseek(fd, 0, os.SEEK_SET)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL)
        yield tuple(descriptors)
    finally:
        for fd in descriptors:
            os.close(fd)


def verify_signature(key: PublisherKey, document: bytes, signature: bytes) -> None:
    if type(signature) is not bytes or len(signature) != 64:
        fail("skill_signature_invalid")
    executable = trusted_openssl_path(fail=lambda _: fail("skill_verifier_runtime_unavailable"))
    try:
        with sealed_inputs((key.public_der, PREFIX + document, signature)) as descriptors:
            pub, message, sig = (f"/proc/self/fd/{fd}" for fd in descriptors)
            checked = subprocess.run([executable, "pkeyutl", "-verify", "-pubin", "-keyform", "DER",
                "-inkey", pub, "-rawin", "-in", message, "-sigfile", sig],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=descriptors,
                timeout=5, check=False, env=trusted_subprocess_environment())
    except (OSError, subprocess.SubprocessError):
        raise SignedSkillError("skill_verifier_runtime_unavailable") from None
    if checked.returncode != 0:
        fail("skill_signature_invalid")
