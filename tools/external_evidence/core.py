#!/usr/bin/env python3
"""Authenticate authority-owned E5-E7/admin/upstream evidence without network access.

A repository-controlled JSON document is never sufficient authority. Every evidence
submission and every acceptance decision is signed with Ed25519 and verified against
an externally pinned trust registry. The registry digest must be supplied out of band;
the digest declared inside the bundle is not accepted as its own trust anchor.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
AUTHORITY = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
CLAIM = re.compile(r"^[a-z][a-z0-9_]{2,99}$")
ARTIFACT_URI = re.compile(r"^artifact://([A-Za-z0-9._/-]{1,500})$")
KEY_URI = re.compile(r"^key://([A-Za-z0-9._/-]{1,500})$")
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(
        rb"(?:OPENAI|DEEPSEEK|DASHSCOPE)_API_KEY\s*[:=]\s*[^\s]+",
        re.I,
    ),
    re.compile(
        rb"(?:refresh_token|client_secret)\s*[\"']?\s*[:=]\s*[\"'][^\"']{8,}",
        re.I,
    ),
)
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_REGISTRY_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_SIGNATURE_BYTES = 4096
MAX_PUBLIC_KEY_BYTES = 64 * 1024
# DER SubjectPublicKeyInfo for id-Ed25519 (OID 1.3.101.112), followed by a
# 32-byte raw public key. Re-encoding through OpenSSL avoids trusting the PEM
# label or registry algorithm string as the cryptographic key type.
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
ED25519_SPKI_BYTES = len(ED25519_SPKI_PREFIX) + 32
ALLOWED_KEY_USAGES = frozenset(
    {"evidence_issuer", "acceptance_reviewer", "independent_reviewer"}
)
_READ_SNAPSHOT: ContextVar[dict[Path, bytes] | None] = ContextVar(
    "hepta_external_evidence_read_snapshot",
    default=None,
)


class EvidenceError(AssertionError):
    """Stable fail-closed validation error."""


def fail(message: str) -> None:
    raise EvidenceError(message)


def validation_snapshot(function: Any) -> Any:
    """Pin every validation input to the first stable byte snapshot read.

    This prevents a concurrent writer from presenting one registry/key/artifact
    for hashing and another for parsing or OpenSSL verification. Nested calls
    reuse the active snapshot so the entire bundle validation has one byte view.
    """

    @functools.wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if _READ_SNAPSHOT.get() is not None:
            return function(*args, **kwargs)
        token = _READ_SNAPSHOT.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _READ_SNAPSHOT.reset(token)

    return wrapped


def _reject_json_constant(value: str) -> None:
    fail(f"non-finite JSON number is prohibited: {value}")


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON object member is prohibited: {key}")
        result[key] = value
    return result


def read_object(path: Path, label: str, *, maximum_bytes: int = MAX_JSON_BYTES) -> dict[str, Any]:
    raw = _read_bounded_file(path, label=label, maximum=maximum_bytes)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except EvidenceError:
        raise
    except Exception as error:  # noqa: BLE001 - stable CLI boundary
        fail(f"{label} is not valid UTF-8 JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    keys = set(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        fail(f"{label} is missing keys: {sorted(missing)}")
    if unknown:
        fail(f"{label} has unknown keys: {sorted(unknown)}")


def require_string(value: Any, *, label: str, maximum: int = 5000) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be a non-empty string")
    normalized = value.strip()
    if normalized != value:
        fail(f"{label} must not contain leading or trailing whitespace")
    if len(normalized) > maximum:
        fail(f"{label} exceeds {maximum} characters")
    return normalized


def require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be boolean")
    return value


def require_string_array(
    value: Any,
    *,
    label: str,
    minimum: int = 1,
    maximum: int = 128,
    item_maximum: int = 500,
) -> list[str]:
    if not isinstance(value, list) or not (minimum <= len(value) <= maximum):
        fail(f"{label} must contain between {minimum} and {maximum} strings")
    result = [
        require_string(item, label=f"{label}[{index}]", maximum=item_maximum)
        for index, item in enumerate(value)
    ]
    if len(set(result)) != len(result):
        fail(f"{label} contains duplicates")
    return result


def parse_time(value: Any, *, label: str, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    text = require_string(value, label=label, maximum=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        fail(f"{label} is not an ISO-8601 timestamp: {error}")
    if parsed.tzinfo is None:
        fail(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def require_sha(value: Any, *, label: str, width: int) -> str:
    text = require_string(value, label=label, maximum=width)
    pattern = SHA40 if width == 40 else SHA64
    if pattern.fullmatch(text) is None:
        fail(f"{label} must be a lowercase {width}-hex digest")
    return text


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        fail(f"value cannot be canonically encoded: {error}")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_bundle_digest(bundle: Mapping[str, Any]) -> str:
    clone = json.loads(json.dumps(bundle, allow_nan=False))
    acceptance = clone.get("acceptance")
    if isinstance(acceptance, dict):
        acceptance["bundle_digest"] = None
    return canonical_digest(clone)


def evidence_set_digest(bundle: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "statement_type": "hepta.external-evidence-set.v1",
            "contract_id": bundle.get("contract_id"),
            "trust_registry": bundle.get("trust_registry"),
            "candidate": bundle.get("candidate"),
            "submissions": bundle.get("submissions"),
        }
    )


def canonical_submission_statement(
    bundle: Mapping[str, Any],
    submission: Mapping[str, Any],
    *,
    contract_revision: str,
) -> bytes:
    unsigned = {key: value for key, value in submission.items() if key != "attestation"}
    attestation = submission.get("attestation")
    signed_at = attestation.get("signed_at") if isinstance(attestation, Mapping) else None
    unsigned["attestation"] = {"signed_at": signed_at}
    return canonical_bytes(
        {
            "statement_type": "hepta.external-evidence-submission.v1",
            "contract_id": bundle.get("contract_id"),
            "contract_revision": contract_revision,
            "trust_registry": bundle.get("trust_registry"),
            "candidate": bundle.get("candidate"),
            "submission": unsigned,
        }
    )


def canonical_review_statement(
    bundle: Mapping[str, Any],
    reviewer: Mapping[str, Any],
    *,
    contract_revision: str,
) -> bytes:
    unsigned = {
        key: value
        for key, value in reviewer.items()
        if key not in {"statement_digest", "signature_uri", "signature_sha256"}
    }
    return canonical_bytes(
        {
            "statement_type": "hepta.external-evidence-review.v1",
            "contract_id": bundle.get("contract_id"),
            "contract_revision": contract_revision,
            "trust_registry": bundle.get("trust_registry"),
            "candidate": bundle.get("candidate"),
            "evidence_set_digest": evidence_set_digest(bundle),
            "reviewer": unsigned,
        }
    )


def _safe_scoped_path(
    root: Path,
    uri: str,
    *,
    pattern: re.Pattern[str],
    scheme: str,
    label: str,
) -> Path:
    match = pattern.fullmatch(uri)
    if match is None:
        fail(f"{label} must use {scheme}:// with a scoped relative path")
    relative = PurePosixPath(match.group(1))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        fail(f"{label} escapes its scope")
    path = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError:
        fail(f"{label} escapes its scope")
    return path


def safe_artifact_path(root: Path, uri: str, *, label: str) -> Path:
    return _safe_scoped_path(
        root,
        uri,
        pattern=ARTIFACT_URI,
        scheme="artifact",
        label=label,
    )


def safe_key_path(root: Path, uri: str, *, label: str) -> Path:
    return _safe_scoped_path(
        root,
        uri,
        pattern=KEY_URI,
        scheme="key",
        label=label,
    )


def _read_bounded_file(path: Path, *, label: str, maximum: int) -> bytes:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        fail(f"{label} references a missing or unreadable file: {error}")

    cache = _READ_SNAPSHOT.get()
    if cache is not None and resolved in cache:
        data = cache[resolved]
        if len(data) > maximum:
            fail(f"{label} exceeds the {maximum}-byte validation bound")
        return data

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as error:
        fail(f"{label} cannot be opened safely: {error}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            fail(f"{label} must reference a regular file")
        if before.st_size > maximum:
            fail(f"{label} exceeds the {maximum}-byte validation bound")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                fail(f"{label} exceeds the {maximum}-byte validation bound")
        after = os.fstat(descriptor)
    except OSError as error:
        fail(f"{label} cannot be read stably: {error}")
    finally:
        os.close(descriptor)

    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    data = b"".join(chunks)
    if identity_before != identity_after or len(data) != before.st_size:
        fail(f"{label} changed while it was being read")
    if cache is not None:
        cache[resolved] = data
    return data


def scan_secret_material(path: Path, *, label: str) -> None:
    data = _read_bounded_file(path, label=label, maximum=MAX_ARTIFACT_BYTES)
    for pattern in SECRET_PATTERNS:
        if pattern.search(data):
            fail(f"{label} contains prohibited credential-shaped material")


def _resolve_openssl(openssl_binary: str) -> str:
    resolved = shutil.which(openssl_binary)
    if resolved is None:
        fail("OpenSSL executable is unavailable; Ed25519 verification cannot proceed")
    return resolved


def _run_openssl(command: list[str], *, label: str) -> bytes:
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        fail(f"{label} could not execute OpenSSL: {type(error).__name__}")
    if completed.returncode != 0:
        fail(f"{label} cryptographic verification failed")
    return completed.stdout


def _verify_public_key_material(
    public_key_data: bytes,
    *,
    openssl_binary: str,
    label: str,
) -> None:
    if b"PRIVATE KEY" in public_key_data or b"PUBLIC KEY" not in public_key_data:
        fail(f"{label} must contain only a PEM public key")
    with tempfile.TemporaryDirectory(prefix="hepta-evidence-key-") as directory:
        public_key = Path(directory) / "public.pem"
        public_key.write_bytes(public_key_data)
        der = _run_openssl(
            [
                _resolve_openssl(openssl_binary),
                "pkey",
                "-pubin",
                "-in",
                str(public_key),
                "-pubout",
                "-outform",
                "DER",
            ],
            label=label,
        )
    if len(der) != ED25519_SPKI_BYTES or not der.startswith(ED25519_SPKI_PREFIX):
        fail(f"{label} must contain an actual Ed25519 public key")


def verify_public_key(public_key: Path, *, openssl_binary: str, label: str) -> None:
    data = _read_bounded_file(
        public_key,
        label=label,
        maximum=MAX_PUBLIC_KEY_BYTES,
    )
    _verify_public_key_material(
        data,
        openssl_binary=openssl_binary,
        label=label,
    )


def _verify_ed25519_material(
    *,
    public_key_data: bytes,
    message: bytes,
    signature: bytes,
    openssl_binary: str,
    label: str,
) -> None:
    if len(signature) != 64:
        fail(f"{label}.signature must be a 64-byte Ed25519 signature")
    with tempfile.TemporaryDirectory(prefix="hepta-evidence-verify-") as directory:
        root = Path(directory)
        public_key = root / "public.pem"
        message_path = root / "message.bin"
        signature_path = root / "signature.bin"
        public_key.write_bytes(public_key_data)
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        der = _run_openssl(
            [
                _resolve_openssl(openssl_binary),
                "pkey",
                "-pubin",
                "-in",
                str(public_key),
                "-pubout",
                "-outform",
                "DER",
            ],
            label=f"{label}.public_key",
        )
        if len(der) != ED25519_SPKI_BYTES or not der.startswith(ED25519_SPKI_PREFIX):
            fail(f"{label}.public_key must contain an actual Ed25519 public key")
        _run_openssl(
            [
                _resolve_openssl(openssl_binary),
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                str(message_path),
                "-sigfile",
                str(signature_path),
            ],
            label=label,
        )


def verify_ed25519_file(
    *,
    public_key: Path,
    message_path: Path,
    signature_path: Path,
    openssl_binary: str,
    label: str,
) -> None:
    public_key_data = _read_bounded_file(
        public_key,
        label=f"{label}.public_key",
        maximum=MAX_PUBLIC_KEY_BYTES,
    )
    message = _read_bounded_file(
        message_path,
        label=f"{label}.message",
        maximum=MAX_ARTIFACT_BYTES,
    )
    signature = _read_bounded_file(
        signature_path,
        label=f"{label}.signature",
        maximum=MAX_SIGNATURE_BYTES,
    )
    _verify_ed25519_material(
        public_key_data=public_key_data,
        message=message,
        signature=signature,
        openssl_binary=openssl_binary,
        label=label,
    )


def verify_ed25519_bytes(
    *,
    public_key: Path,
    message: bytes,
    signature_path: Path,
    openssl_binary: str,
    label: str,
) -> None:
    public_key_data = _read_bounded_file(
        public_key,
        label=f"{label}.public_key",
        maximum=MAX_PUBLIC_KEY_BYTES,
    )
    signature = _read_bounded_file(
        signature_path,
        label=f"{label}.signature",
        maximum=MAX_SIGNATURE_BYTES,
    )
    _verify_ed25519_material(
        public_key_data=public_key_data,
        message=message,
        signature=signature,
        openssl_binary=openssl_binary,
        label=label,
    )
