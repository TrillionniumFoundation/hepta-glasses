#!/usr/bin/env python3
"""Verify an externally signed, content-addressed exact-head source Artifact.

The repository is an untrusted subject. The archive bytes, receipt, trusted
verification time, and trust registry are separate inputs. A passing result
proves only the exact source-evidence object and identities checked here; it
does not manufacture product, provider, device, signing, pilot, or release
authority.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPOSITORY = "TrillionniumFoundation/hepta-glasses"
OPENSSL_PATH = Path("/usr/bin/openssl")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KEY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
UTC_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
MAX_RECEIPT_BYTES = 128 * 1024
MAX_TRUST_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 200_000
MAX_COMPRESSION_RATIO = 250
MIN_RATIO_CHECK_BYTES = 1024 * 1024
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})

EXPECTED_MEMBERS = (
    "source-evidence-summary.json",
    "source-gate-result.json",
    "source-history-scan.json",
    "source-native-sanitizer.json",
    "source-provenance.json",
    "source-release-bundle.json",
    "source-sbom.spdx.json",
)
EXPECTED_MEMBER_SET = frozenset(EXPECTED_MEMBERS)
EXPECTED_CI_CHECKS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
)
EXPECTED_GATE_CHECKS = frozenset(
    {
        "exact_commit",
        "exact_tree",
        "required_ci",
        "sbom",
        "sbom_ecosystems",
        "history_scan",
        "native_sanitizer",
        "audit_contract",
        "provenance",
        "provenance_type",
        "contracts_version",
        "artifact_sbom_digest",
        "artifact_provenance_digest",
        "artifact_history_digest",
        "artifact_native_digest",
        "artifact_history_content",
        "artifact_native_content",
    }
)
EXPECTED_ECOSYSTEMS = frozenset(
    {"android/gradle", "dart/pub", "ios/cocoapods", "native/vendored"}
)
RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "head_commit",
        "source_tree",
        "artifact_name",
        "artifact_sha256",
        "artifact_size_bytes",
        "archive_object",
        "archived_at",
        "retention_until",
        "custodian",
        "key_id",
        "signature",
    }
)
TRUST_KEYS = frozenset({"schema_version", "keys"})
TRUST_ENTRY_KEYS = frozenset(
    {
        "key_id",
        "algorithm",
        "public_key_pem",
        "status",
        "valid_from",
        "valid_until",
    }
)
SUMMARY_KEYS = frozenset(
    {
        "audit_contract",
        "commit",
        "contracts_version",
        "file_count",
        "history_commit_count",
        "history_raw_finding_count",
        "history_acknowledged_finding_count",
        "history_finding_count",
        "history_unused_acknowledgement_count",
        "history_unscanned_blob_count",
        "native_sanitizer_digest",
        "package_count",
        "provenance_digest",
        "sbom_digest",
        "sbom_ecosystems",
        "tree",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "type",
        "attestation",
        "builder",
        "commit",
        "contracts_version",
        "generated_at",
        "history_scan_digest",
        "native_sanitizer_digest",
        "repository",
        "sbom_digest",
        "tree",
    }
)
SOURCE_BUNDLE_KEYS = frozenset(
    {
        "audit_contract",
        "ci_checks",
        "commit",
        "contracts_version",
        "history_scan",
        "native_sanitizer",
        "provenance",
        "provenance_type",
        "sbom",
        "sbom_ecosystems",
        "tree",
    }
)
GATE_KEYS = frozenset({"checks", "missing", "mode", "passed"})


class ArchiveReceiptError(ValueError):
    """Raised when archive custody or source evidence cannot be trusted."""


@dataclass(frozen=True)
class VerificationResult:
    repository: str
    head_commit: str
    source_tree: str
    artifact_name: str
    artifact_sha256: str
    artifact_size_bytes: int
    archive_object: str
    custodian: str
    key_id: str
    archived_at: str
    retention_until: str
    verification_time: str
    member_count: int
    source_gate_check_count: int
    sbom_file_count: int
    sbom_package_count: int

    def as_dict(self) -> dict[str, Any]:
        return {"passed": True, **asdict(self)}


def _fail(message: str) -> None:
    raise ArchiveReceiptError(message)


def _reject_constant(value: str) -> None:
    _fail(f"non-finite JSON number is prohibited: {value}")


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_object(
    value: Any,
    *,
    label: str,
    exact_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    if exact_keys is not None and frozenset(value) != exact_keys:
        _fail(
            f"{label} keys are not closed; "
            f"missing={sorted(exact_keys - frozenset(value))}, "
            f"extra={sorted(frozenset(value) - exact_keys)}"
        )
    return value


def _require_string(
    value: Any,
    *,
    label: str,
    pattern: re.Pattern[str] | None = None,
    maximum: int | None = None,
) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    if maximum is not None and len(value) > maximum:
        _fail(f"{label} exceeds its length limit")
    if pattern is not None and pattern.fullmatch(value) is None:
        _fail(f"{label} has an invalid shape")
    return value


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer, not bool/float/string")
    if value < minimum or (maximum is not None and value > maximum):
        _fail(f"{label} is outside its accepted range")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{label} must be a boolean")
    return value


def _parse_utc(value: Any, *, label: str) -> datetime:
    text = _require_string(value, label=label, pattern=UTC_TIME)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise ArchiveReceiptError(f"{label} is not a valid UTC timestamp") from error
    return parsed


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        _fail("verification_time must be timezone-aware UTC")
    if value.microsecond != 0:
        _fail("verification_time must have whole-second precision")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stable_regular_file(path: Path, *, label: str, maximum: int) -> bytes:
    try:
        lexical = path.absolute()
        lexical_stat = lexical.lstat()
    except OSError as error:
        raise ArchiveReceiptError(f"{label} is unavailable: {path}") from error
    if stat.S_ISLNK(lexical_stat.st_mode):
        _fail(f"{label} must not be a symlink")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lexical, flags)
    except OSError as error:
        raise ArchiveReceiptError(f"{label} cannot be opened safely: {path}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{label} must be a regular file")
        if before.st_size < 1 or before.st_size > maximum:
            _fail(f"{label} size is outside the accepted range")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
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
    if identity_before != identity_after or len(data) != before.st_size:
        _fail(f"{label} changed while it was being read")
    if len(data) > maximum:
        _fail(f"{label} exceeds the byte limit")
    return data


def _walk_json(value: Any, *, label: str) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            _fail(f"{label} exceeds the JSON node limit")
        if depth > MAX_JSON_DEPTH:
            _fail(f"{label} exceeds the JSON depth limit")
        if isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str):
                    _fail(f"{label} contains a non-string object key")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, float):
            if not math.isfinite(current):
                _fail(f"{label} contains an invalid floating-point value")
        elif current is not None and not isinstance(
            current, (str, int, float, bool)
        ):
            _fail(f"{label} contains an unsupported JSON value")


def _load_strict_json_bytes(data: bytes, *, label: str) -> Any:
    if data.startswith(b"\xef\xbb\xbf"):
        _fail(f"{label} must not contain a UTF-8 BOM")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ArchiveReceiptError(f"{label} is not strict UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ArchiveReceiptError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise ArchiveReceiptError(f"{label} is not valid JSON") from error
    _walk_json(value, label=label)
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_payloads(artifact: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(artifact), mode="r")
    except (zipfile.BadZipFile, OSError) as error:
        raise ArchiveReceiptError("artifact is not a valid ZIP archive") from error
    with archive:
        infos = archive.infolist()
        if len(infos) != len(EXPECTED_MEMBERS):
            _fail("artifact does not contain exactly seven source-evidence members")
        seen: set[str] = set()
        total = 0
        for info in infos:
            name = info.filename
            if (
                not name
                or "\\" in name
                or name.startswith("/")
                or name.startswith("./")
                or "//" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                _fail(f"artifact contains an unsafe member path: {name!r}")
            if name in seen:
                _fail(f"artifact contains a duplicate member: {name}")
            seen.add(name)
            if info.is_dir() or name.endswith("/"):
                _fail(f"artifact member must be a regular file: {name}")
            mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(mode)
            if kind not in {0, stat.S_IFREG}:
                _fail(f"artifact member is a symlink or special file: {name}")
            if info.flag_bits & 0x1:
                _fail(f"artifact member is encrypted: {name}")
            if info.compress_type not in ALLOWED_COMPRESSION:
                _fail(f"artifact member uses an unsupported compression method: {name}")
            if info.file_size < 1 or info.file_size > MAX_MEMBER_BYTES:
                _fail(f"artifact member size is outside the accepted range: {name}")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                _fail("artifact exceeds the total uncompressed byte limit")
            denominator = max(info.compress_size, 1)
            if (
                info.file_size >= MIN_RATIO_CHECK_BYTES
                and info.file_size / denominator > MAX_COMPRESSION_RATIO
            ):
                _fail(f"artifact member exceeds the compression-ratio limit: {name}")
        if seen != EXPECTED_MEMBER_SET:
            _fail(
                "artifact member inventory differs from the canonical seven files; "
                f"missing={sorted(EXPECTED_MEMBER_SET - seen)}, "
                f"extra={sorted(seen - EXPECTED_MEMBER_SET)}"
            )

        payloads: dict[str, bytes] = {}
        try:
            by_name = {info.filename: info for info in infos}
            for name in EXPECTED_MEMBERS:
                with archive.open(by_name[name], "r") as member:
                    data = member.read(MAX_MEMBER_BYTES + 1)
                    if member.read(1):
                        _fail(f"artifact member exceeds the read limit: {name}")
                if len(data) != by_name[name].file_size:
                    _fail(f"artifact member length differs from ZIP metadata: {name}")
                payloads[name] = data
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError) as error:
            raise ArchiveReceiptError(
                "artifact ZIP member failed CRC or bounded extraction"
            ) from error
        return payloads


def _decode_signature(value: Any) -> bytes:
    text = _require_string(value, label="receipt.signature", maximum=128)
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ArchiveReceiptError("receipt.signature is not canonical base64") from error
    if len(decoded) != 64:
        _fail("Ed25519 signature must be exactly 64 bytes")
    if base64.b64encode(decoded).decode("ascii") != text:
        _fail("receipt.signature base64 is not canonical")
    return decoded


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ArchiveReceiptError("receipt cannot be canonically encoded") from error


def _select_trust_key(
    registry: Any,
    *,
    key_id: str,
    archived_at: datetime,
) -> str:
    root = _require_object(registry, label="trust registry", exact_keys=TRUST_KEYS)
    if _require_int(root["schema_version"], label="trust.schema_version") != 1:
        _fail("unsupported trust registry schema_version")
    entries = root["keys"]
    if not isinstance(entries, list) or not entries:
        _fail("trust registry keys must be a non-empty array")
    seen: set[str] = set()
    matched: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        entry = _require_object(
            raw,
            label=f"trust.keys[{index}]",
            exact_keys=TRUST_ENTRY_KEYS,
        )
        current_id = _require_string(
            entry["key_id"],
            label=f"trust.keys[{index}].key_id",
            pattern=KEY_ID,
        )
        if current_id in seen:
            _fail(f"duplicate trust key_id: {current_id}")
        seen.add(current_id)
        algorithm = _require_string(
            entry["algorithm"], label=f"trust.keys[{index}].algorithm"
        )
        status_value = _require_string(
            entry["status"], label=f"trust.keys[{index}].status"
        )
        valid_from = _parse_utc(
            entry["valid_from"], label=f"trust.keys[{index}].valid_from"
        )
        valid_until = _parse_utc(
            entry["valid_until"], label=f"trust.keys[{index}].valid_until"
        )
        pem = _require_string(
            entry["public_key_pem"],
            label=f"trust.keys[{index}].public_key_pem",
            maximum=8192,
        )
        if valid_until <= valid_from:
            _fail(f"trust key validity is empty: {current_id}")
        if current_id == key_id:
            matched.append(
                {
                    "algorithm": algorithm,
                    "status": status_value,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "pem": pem,
                }
            )
    if len(matched) != 1:
        _fail("receipt key_id is not uniquely trusted")
    selected = matched[0]
    if selected["algorithm"] != "ed25519":
        _fail("archive receipt key must use ed25519")
    if selected["status"] != "active":
        _fail("archive receipt key is not active")
    if not selected["valid_from"] <= archived_at < selected["valid_until"]:
        _fail("archive receipt was signed outside key validity")
    pem = selected["pem"]
    if (
        "BEGIN PUBLIC KEY" not in pem
        or "END PUBLIC KEY" not in pem
        or "PRIVATE KEY" in pem
    ):
        _fail("trust key is not a public-key PEM")
    try:
        pem.encode("ascii")
    except UnicodeError as error:
        raise ArchiveReceiptError("trust key PEM must be ASCII") from error
    return pem


def _verify_ed25519(public_key_pem: str, payload: bytes, signature: bytes) -> None:
    if (
        OPENSSL_PATH != Path("/usr/bin/openssl")
        or not OPENSSL_PATH.is_file()
        or OPENSSL_PATH.is_symlink()
        or not os.access(OPENSSL_PATH, os.X_OK)
    ):
        _fail("fixed system OpenSSL verifier is unavailable")
    with tempfile.TemporaryDirectory(prefix="hepta-archive-verify-") as temp:
        directory = Path(temp)
        key = directory / "public.pem"
        message = directory / "payload.bin"
        detached = directory / "signature.bin"
        key.write_text(public_key_pem, encoding="ascii")
        message.write_bytes(payload)
        detached.write_bytes(signature)
        try:
            completed = subprocess.run(
                [
                    str(OPENSSL_PATH),
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(key),
                    "-sigfile",
                    str(detached),
                    "-rawin",
                    "-in",
                    str(message),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=15,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ArchiveReceiptError(
                "fixed system OpenSSL verifier could not execute"
            ) from error
        if completed.returncode != 0:
            _fail("archive receipt signature verification failed")


def _require_lower_digest(value: Any, *, label: str, length: int = 64) -> str:
    pattern = HEX40 if length == 40 else HEX64
    return _require_string(value, label=label, pattern=pattern)


def _same_sequence(value: Any, expected: Sequence[str], *, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(f"{label} must be an ordered string array")
    if tuple(value) != tuple(expected):
        _fail(f"{label} differs from the canonical order")


def _validate_source_evidence(
    payloads: Mapping[str, bytes],
    *,
    repository: str,
    head: str,
    tree: str,
    verification_time: datetime,
) -> tuple[int, int, int]:
    documents = {
        name: _load_strict_json_bytes(data, label=name)
        for name, data in payloads.items()
    }
    digests = {name: _digest(data) for name, data in payloads.items()}

    summary = _require_object(
        documents["source-evidence-summary.json"],
        label="source evidence summary",
        exact_keys=SUMMARY_KEYS,
    )
    if summary["commit"] != head or summary["tree"] != tree:
        _fail("source evidence summary is not bound to receipt head/tree")
    if summary["audit_contract"] != "authenticated-checkpoint-v3":
        _fail("source evidence summary audit contract drifted")
    contracts_version = _require_string(
        summary["contracts_version"], label="summary.contracts_version", maximum=128
    )
    file_count = _require_int(
        summary["file_count"], label="summary.file_count", minimum=1
    )
    package_count = _require_int(
        summary["package_count"], label="summary.package_count", minimum=1
    )
    for field in (
        "history_commit_count",
        "history_raw_finding_count",
        "history_acknowledged_finding_count",
        "history_finding_count",
        "history_unused_acknowledgement_count",
        "history_unscanned_blob_count",
    ):
        _require_int(summary[field], label=f"summary.{field}")
    for field in (
        "native_sanitizer_digest",
        "provenance_digest",
        "sbom_digest",
    ):
        _require_lower_digest(summary[field], label=f"summary.{field}")
    if summary["history_finding_count"] != 0:
        _fail("source evidence summary reports unacknowledged history findings")
    if summary["history_unused_acknowledgement_count"] != 0:
        _fail("source evidence summary reports unused history acknowledgements")
    if summary["history_unscanned_blob_count"] != 0:
        _fail("source evidence summary reports unscanned history blobs")
    _same_sequence(
        summary["sbom_ecosystems"],
        sorted(EXPECTED_ECOSYSTEMS),
        label="summary.sbom_ecosystems",
    )

    history = _require_object(
        documents["source-history-scan.json"], label="source history scan"
    )
    if history.get("head") != head:
        _fail("history scan is not bound to receipt head")
    if history.get("scope") != "all-fetched-refs-and-deduplicated-blobs":
        _fail("history scan scope is incomplete")
    for field in (
        "commit_count",
        "scanned_blob_count",
        "raw_finding_count",
        "acknowledged_finding_count",
        "finding_count",
        "unused_acknowledgement_count",
        "unscanned_blob_count",
    ):
        _require_int(history.get(field), label=f"history.{field}")
    if (
        history["finding_count"] != 0
        or history["unused_acknowledgement_count"] != 0
        or history["unscanned_blob_count"] != 0
    ):
        _fail("history scan is not terminal-clean")
    count_bindings = {
        "history_commit_count": "commit_count",
        "history_raw_finding_count": "raw_finding_count",
        "history_acknowledged_finding_count": "acknowledged_finding_count",
        "history_finding_count": "finding_count",
        "history_unused_acknowledgement_count": "unused_acknowledgement_count",
        "history_unscanned_blob_count": "unscanned_blob_count",
    }
    for summary_field, history_field in count_bindings.items():
        if summary[summary_field] != history[history_field]:
            _fail(f"history count drifted between summary and report: {history_field}")

    native = _require_object(
        documents["source-native-sanitizer.json"], label="native sanitizer report"
    )
    if native.get("passed") is not True:
        _fail("native sanitizer report did not pass")
    if native.get("lc3_cross_platform_parity") is not True:
        _fail("native sanitizer report lacks LC3 cross-platform parity")

    provenance = _require_object(
        documents["source-provenance.json"],
        label="source provenance",
        exact_keys=PROVENANCE_KEYS,
    )
    if (
        provenance["repository"] != repository
        or provenance["commit"] != head
        or provenance["tree"] != tree
    ):
        _fail("source provenance is not bound to receipt repository/head/tree")
    if provenance["type"] != "unsigned-source-provenance-v1":
        _fail("source provenance type drifted")
    if provenance["attestation"] != "unsigned-ci-generated-source-metadata":
        _fail("source provenance attestation drifted")
    if provenance["builder"] != "github-actions/hepta-source-evidence-v3":
        _fail("source provenance builder drifted")
    if provenance["contracts_version"] != contracts_version:
        _fail("source provenance contracts version drifted")
    generated_at_text = _require_string(
        provenance["generated_at"], label="provenance.generated_at", maximum=64
    )
    try:
        generated_at = datetime.fromisoformat(
            generated_at_text.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ArchiveReceiptError(
            "provenance.generated_at is not a valid timestamp"
        ) from error
    if generated_at.tzinfo is None:
        _fail("provenance.generated_at must include a timezone")
    generated_at = generated_at.astimezone(timezone.utc)
    if generated_at > verification_time:
        _fail("source provenance was generated in the future")
    digest_bindings = {
        "history_scan_digest": "source-history-scan.json",
        "native_sanitizer_digest": "source-native-sanitizer.json",
        "sbom_digest": "source-sbom.spdx.json",
    }
    for field, member in digest_bindings.items():
        if provenance[field] != digests[member]:
            _fail(f"source provenance digest does not bind {member}")
    if summary["provenance_digest"] != digests["source-provenance.json"]:
        _fail("summary provenance digest drifted")
    if summary["native_sanitizer_digest"] != digests["source-native-sanitizer.json"]:
        _fail("summary native sanitizer digest drifted")
    if summary["sbom_digest"] != digests["source-sbom.spdx.json"]:
        _fail("summary SBOM digest drifted")

    release = _require_object(
        documents["source-release-bundle.json"],
        label="source release bundle",
        exact_keys=frozenset({"source"}),
    )
    source = _require_object(
        release["source"],
        label="source release bundle.source",
        exact_keys=SOURCE_BUNDLE_KEYS,
    )
    if source["commit"] != head or source["tree"] != tree:
        _fail("source release bundle is not bound to receipt head/tree")
    if source["contracts_version"] != contracts_version:
        _fail("source release bundle contracts version drifted")
    if source["audit_contract"] != summary["audit_contract"]:
        _fail("source release bundle audit contract drifted")
    if source["provenance_type"] != provenance["type"]:
        _fail("source release bundle provenance type drifted")
    _same_sequence(
        source["sbom_ecosystems"],
        sorted(EXPECTED_ECOSYSTEMS),
        label="source bundle.sbom_ecosystems",
    )
    ci_checks = source["ci_checks"]
    if not isinstance(ci_checks, list) or len(ci_checks) != len(EXPECTED_CI_CHECKS):
        _fail("source release bundle CI inventory is incomplete")
    names: list[str] = []
    for index, raw in enumerate(ci_checks):
        item = _require_object(
            raw,
            label=f"source bundle.ci_checks[{index}]",
            exact_keys=frozenset({"name", "conclusion"}),
        )
        names.append(
            _require_string(item["name"], label=f"ci_checks[{index}].name")
        )
        if item["conclusion"] != "success":
            _fail(f"source CI check did not succeed: {item['name']}")
    if tuple(names) != EXPECTED_CI_CHECKS:
        _fail("source release bundle CI identity or order drifted")

    nested_digest_bindings = {
        ("history_scan", "sha256"): "source-history-scan.json",
        ("native_sanitizer", "sha256"): "source-native-sanitizer.json",
        ("provenance", "sha256"): "source-provenance.json",
        ("sbom", "sha256"): "source-sbom.spdx.json",
    }
    for (field, nested), member in nested_digest_bindings.items():
        value = _require_object(source[field], label=f"source bundle.{field}")
        if value.get(nested) != digests[member]:
            _fail(f"source release bundle digest does not bind {member}")
    history_binding = _require_object(
        source["history_scan"], label="source bundle.history_scan"
    )
    for field in (
        "scope",
        "commit_count",
        "scanned_blob_count",
        "raw_finding_count",
        "acknowledged_finding_count",
        "finding_count",
        "unused_acknowledgement_count",
        "unscanned_blob_count",
    ):
        if history_binding.get(field) != history.get(field):
            _fail(f"source release bundle history binding drifted: {field}")
    native_binding = _require_object(
        source["native_sanitizer"], label="source bundle.native_sanitizer"
    )
    if (
        native_binding.get("passed") is not True
        or native_binding.get("lc3_cross_platform_parity") is not True
    ):
        _fail("source release bundle native result did not pass")

    gate = _require_object(
        documents["source-gate-result.json"],
        label="source gate result",
        exact_keys=GATE_KEYS,
    )
    if gate["mode"] != "source" or gate["passed"] is not True:
        _fail("source gate result did not pass in source mode")
    if gate["missing"] != []:
        _fail("source gate result contains missing checks")
    gate_checks = _require_object(gate["checks"], label="source gate checks")
    if frozenset(gate_checks) != EXPECTED_GATE_CHECKS:
        _fail("source gate check inventory drifted")
    for name, passed in gate_checks.items():
        if _require_bool(passed, label=f"source gate check {name}") is not True:
            _fail(f"source gate check did not pass: {name}")

    sbom = _require_object(
        documents["source-sbom.spdx.json"], label="source SPDX SBOM"
    )
    if sbom.get("SPDXID") != "SPDXRef-DOCUMENT":
        _fail("source SBOM document identity drifted")
    if sbom.get("spdxVersion") != "SPDX-2.3":
        _fail("source SBOM is not SPDX 2.3")
    if sbom.get("dataLicense") != "CC0-1.0":
        _fail("source SBOM data license drifted")
    if sbom.get("name") != f"{repository}@{head}":
        _fail("source SBOM name is not bound to receipt repository/head")
    if sbom.get("documentNamespace") != f"urn:hepta:sbom:{repository}:{head}":
        _fail("source SBOM namespace is not bound to receipt repository/head")
    files = sbom.get("files")
    packages = sbom.get("packages")
    if not isinstance(files, list) or not isinstance(packages, list):
        _fail("source SBOM files/packages must be arrays")
    if len(files) != file_count or len(packages) != package_count:
        _fail("source SBOM counts drifted from summary")
    seen_files: set[str] = set()
    seen_ids: set[str] = set()
    for index, raw in enumerate(files):
        item = _require_object(raw, label=f"source SBOM files[{index}]")
        name = _require_string(item.get("fileName"), label=f"SBOM file[{index}].fileName")
        identifier = _require_string(item.get("SPDXID"), label=f"SBOM file[{index}].SPDXID")
        if name in seen_files or identifier in seen_ids:
            _fail("source SBOM contains duplicate file identity")
        seen_files.add(name)
        seen_ids.add(identifier)
        checksums = item.get("checksums")
        if not isinstance(checksums, list) or len(checksums) != 1:
            _fail("source SBOM file must contain exactly one checksum")
        checksum = _require_object(checksums[0], label=f"SBOM file[{index}].checksum")
        if checksum.get("algorithm") != "SHA256":
            _fail("source SBOM file checksum must use SHA256")
        _require_lower_digest(
            checksum.get("checksumValue"),
            label=f"SBOM file[{index}].checksumValue",
        )
    ecosystems: set[str] = set()
    package_ids: set[str] = set()
    root_package_found = False
    for index, raw in enumerate(packages):
        item = _require_object(raw, label=f"source SBOM packages[{index}]")
        identifier = _require_string(
            item.get("SPDXID"), label=f"SBOM package[{index}].SPDXID"
        )
        if identifier in package_ids or identifier in seen_ids:
            _fail("source SBOM contains duplicate SPDX identity")
        package_ids.add(identifier)
        comment = item.get("comment")
        if isinstance(comment, str) and comment.startswith("ecosystem="):
            ecosystem = comment.removeprefix("ecosystem=")
            if ecosystem == "application":
                root_package_found = (
                    item.get("name") == "hepta-glasses"
                    and identifier == "SPDXRef-Package-HeptaGlasses"
                    and item.get("filesAnalyzed") is True
                )
            else:
                ecosystems.add(ecosystem)
    if not root_package_found:
        _fail("source SBOM lacks the canonical application package")
    if ecosystems != EXPECTED_ECOSYSTEMS:
        _fail("source SBOM ecosystem inventory drifted")
    return len(gate_checks), len(files), len(packages)


def verify_archive_receipt(
    *,
    receipt_path: Path,
    artifact_path: Path,
    trust_registry_path: Path,
    repository_root: Path,
    verification_time: datetime,
    expected_head: str | None = None,
    expected_tree: str | None = None,
) -> VerificationResult:
    verification_time_text = _format_utc(verification_time)
    root = repository_root.resolve(strict=True)
    if not root.is_dir():
        _fail("repository_root must resolve to a directory")

    receipt_bytes = _read_stable_regular_file(
        receipt_path, label="receipt", maximum=MAX_RECEIPT_BYTES
    )
    artifact_bytes = _read_stable_regular_file(
        artifact_path, label="artifact", maximum=MAX_ARTIFACT_BYTES
    )
    trust_bytes = _read_stable_regular_file(
        trust_registry_path, label="trust registry", maximum=MAX_TRUST_BYTES
    )
    trust_resolved = trust_registry_path.resolve(strict=True)
    try:
        trust_resolved.relative_to(root)
    except ValueError:
        pass
    else:
        _fail("trust registry must be administered and supplied outside the repository")

    receipt = _require_object(
        _load_strict_json_bytes(receipt_bytes, label="receipt"),
        label="receipt",
        exact_keys=RECEIPT_KEYS,
    )
    if _require_int(receipt["schema_version"], label="receipt.schema_version") != 1:
        _fail("unsupported receipt schema_version")
    repository = _require_string(
        receipt["repository"], label="receipt.repository", maximum=256
    )
    if repository != REPOSITORY:
        _fail("receipt repository does not identify hepta-glasses")
    head = _require_lower_digest(
        receipt["head_commit"], label="receipt.head_commit", length=40
    )
    tree = _require_lower_digest(
        receipt["source_tree"], label="receipt.source_tree", length=40
    )
    if expected_head is not None and head != expected_head:
        _fail("receipt head_commit does not match expected head")
    if expected_tree is not None and tree != expected_tree:
        _fail("receipt source_tree does not match expected tree")
    name = _require_string(
        receipt["artifact_name"], label="receipt.artifact_name", maximum=128
    )
    if name != f"hepta-source-evidence-{head}":
        _fail("artifact_name is not bound to head_commit")
    stated_digest = _require_lower_digest(
        receipt["artifact_sha256"], label="receipt.artifact_sha256"
    )
    stated_size = _require_int(
        receipt["artifact_size_bytes"],
        label="receipt.artifact_size_bytes",
        minimum=1,
        maximum=MAX_ARTIFACT_BYTES,
    )
    archive_object = _require_string(
        receipt["archive_object"], label="receipt.archive_object", maximum=128
    )
    if archive_object != f"sha256:{stated_digest}":
        _fail("archive_object is not content-addressed to artifact_sha256")
    archived_at = _parse_utc(receipt["archived_at"], label="receipt.archived_at")
    retention_until = _parse_utc(
        receipt["retention_until"], label="receipt.retention_until"
    )
    if archived_at > verification_time:
        _fail("archive receipt is future-dated relative to trusted verification time")
    if retention_until <= archived_at:
        _fail("retention_until must be later than archived_at")
    if retention_until <= verification_time:
        _fail("archive receipt retention has expired")
    custodian = _require_string(
        receipt["custodian"], label="receipt.custodian", maximum=256
    )
    key_id = _require_string(
        receipt["key_id"], label="receipt.key_id", pattern=KEY_ID
    )

    actual_digest = _digest(artifact_bytes)
    if actual_digest != stated_digest:
        _fail("artifact SHA-256 does not match receipt")
    if len(artifact_bytes) != stated_size:
        _fail("artifact size does not match receipt")

    registry = _load_strict_json_bytes(trust_bytes, label="trust registry")
    public_key = _select_trust_key(
        registry,
        key_id=key_id,
        archived_at=archived_at,
    )
    signature = _decode_signature(receipt["signature"])
    unsigned = dict(receipt)
    unsigned.pop("signature")
    _verify_ed25519(public_key, _canonical_json(unsigned), signature)

    payloads = _archive_payloads(artifact_bytes)
    gate_count, file_count, package_count = _validate_source_evidence(
        payloads,
        repository=repository,
        head=head,
        tree=tree,
        verification_time=verification_time,
    )

    return VerificationResult(
        repository=repository,
        head_commit=head,
        source_tree=tree,
        artifact_name=name,
        artifact_sha256=stated_digest,
        artifact_size_bytes=stated_size,
        archive_object=archive_object,
        custodian=custodian,
        key_id=key_id,
        archived_at=receipt["archived_at"],
        retention_until=receipt["retention_until"],
        verification_time=verification_time_text,
        member_count=len(payloads),
        source_gate_check_count=gate_count,
        sbom_file_count=file_count,
        sbom_package_count=package_count,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--trust-registry", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--verification-time", required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-tree")
    args = parser.parse_args(argv)
    for value, label in (
        (args.expected_head, "expected head"),
        (args.expected_tree, "expected tree"),
    ):
        if value is not None and HEX40.fullmatch(value) is None:
            parser.error(f"{label} must be a lowercase 40-hex object ID")
    try:
        trusted_time = _parse_utc(
            args.verification_time, label="verification_time"
        )
        result = verify_archive_receipt(
            receipt_path=args.receipt,
            artifact_path=args.artifact,
            trust_registry_path=args.trust_registry,
            repository_root=args.repository_root,
            verification_time=trusted_time,
            expected_head=args.expected_head,
            expected_tree=args.expected_tree,
        )
    except (ArchiveReceiptError, OSError, ValueError) as error:
        print(
            json.dumps({"passed": False, "error": str(error)}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
