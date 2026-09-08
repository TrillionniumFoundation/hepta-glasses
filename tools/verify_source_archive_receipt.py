#!/usr/bin/env python3
"""Verify a content-addressed, externally signed source Artifact archive receipt.

The repository is an untrusted subject. The trust registry must be supplied
out-of-band and resolve outside the repository root. Passing proves only the
exact bytes and tuple supplied; it creates no external authority or release
approval.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KEY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REPOSITORY = "TrillionniumFoundation/hepta-glasses"
RECEIPT_KEYS = {
    "schema_version", "repository", "head_commit", "source_tree",
    "artifact_name", "artifact_sha256", "artifact_size_bytes",
    "archive_object", "archived_at", "retention_until", "custodian",
    "key_id", "signature",
}
TRUST_KEYS = {"schema_version", "keys"}
TRUST_ENTRY_KEYS = {
    "key_id", "algorithm", "public_key_pem", "status", "valid_from",
    "valid_until",
}


class ArchiveReceiptError(ValueError):
    """Raised when an archive receipt cannot be trusted."""


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

    def as_dict(self) -> dict[str, Any]:
        return {"passed": True, **asdict(self)}


def _reject_constant(value: str) -> None:
    raise ArchiveReceiptError(f"non-finite JSON number is prohibited: {value}")


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveReceiptError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_strict_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchiveReceiptError(f"cannot read JSON file: {path}") from exc
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except ArchiveReceiptError:
        raise
    except json.JSONDecodeError as exc:
        raise ArchiveReceiptError(f"invalid JSON in {path}: {exc.msg}") from exc


def canonical_json(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ArchiveReceiptError("receipt cannot be canonically encoded") from exc
    return encoded.encode("utf-8")


def _require_object(value: Any, label: str, exact_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArchiveReceiptError(f"{label} must be a JSON object")
    keys = set(value)
    if keys != exact_keys:
        raise ArchiveReceiptError(
            f"{label} keys are not closed; missing={sorted(exact_keys - keys)}, "
            f"extra={sorted(keys - exact_keys)}"
        )
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArchiveReceiptError(f"{label} must be a non-empty string")
    return value


def _require_exact_int(value: Any, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveReceiptError(f"{label} must be an integer, not bool/float/string")
    if minimum is not None and value < minimum:
        raise ArchiveReceiptError(f"{label} must be >= {minimum}")
    return value


def _parse_utc(value: Any, label: str) -> datetime:
    text = _require_string(value, label)
    if not text.endswith("Z"):
        raise ArchiveReceiptError(f"{label} must use an explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ArchiveReceiptError(f"{label} is not RFC3339 UTC") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ArchiveReceiptError(f"{label} must be UTC")
    return parsed


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ArchiveReceiptError(f"{label} must be a non-symlink regular file")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArchiveReceiptError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise ArchiveReceiptError(f"{label} must be a non-symlink regular file")
    return resolved


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise ArchiveReceiptError(f"cannot hash artifact: {path}") from exc
    return digest.hexdigest(), size


def _decode_signature(value: Any) -> bytes:
    text = _require_string(value, "signature")
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ArchiveReceiptError("signature is not canonical base64") from exc
    if len(decoded) != 64:
        raise ArchiveReceiptError("Ed25519 signature must be exactly 64 bytes")
    if base64.b64encode(decoded).decode("ascii") != text:
        raise ArchiveReceiptError("signature base64 is not canonical")
    return decoded


def _select_trust_key(registry: Any, key_id: str, archived_at: datetime) -> str:
    obj = _require_object(registry, "trust registry", TRUST_KEYS)
    if _require_exact_int(obj["schema_version"], "trust schema_version") != 1:
        raise ArchiveReceiptError("unsupported trust registry schema_version")
    entries = obj["keys"]
    if not isinstance(entries, list) or not entries:
        raise ArchiveReceiptError("trust registry keys must be a non-empty array")
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        entry = _require_object(raw, f"trust key[{index}]", TRUST_ENTRY_KEYS)
        current_id = _require_string(entry["key_id"], f"trust key[{index}].key_id")
        if not KEY_ID.fullmatch(current_id):
            raise ArchiveReceiptError(f"invalid trust key_id: {current_id}")
        if current_id in seen:
            raise ArchiveReceiptError(f"duplicate trust key_id: {current_id}")
        seen.add(current_id)
        if current_id == key_id:
            matched.append(entry)
    if len(matched) != 1:
        raise ArchiveReceiptError("receipt key_id is not uniquely trusted")
    entry = matched[0]
    if entry["algorithm"] != "ed25519":
        raise ArchiveReceiptError("archive receipt key must use ed25519")
    if entry["status"] != "active":
        raise ArchiveReceiptError("archive receipt key is not active")
    valid_from = _parse_utc(entry["valid_from"], "trust key valid_from")
    valid_until = _parse_utc(entry["valid_until"], "trust key valid_until")
    if not valid_from <= archived_at < valid_until:
        raise ArchiveReceiptError("archive receipt was signed outside key validity")
    pem = _require_string(entry["public_key_pem"], "trust key public_key_pem")
    if "BEGIN PUBLIC KEY" not in pem or "END PUBLIC KEY" not in pem:
        raise ArchiveReceiptError("trust key is not a public-key PEM")
    return pem


def _verify_ed25519(public_key_pem: str, payload: bytes, signature: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="hepta-archive-verify-") as tmp:
        directory = Path(tmp)
        key_path = directory / "public.pem"
        payload_path = directory / "payload.bin"
        signature_path = directory / "signature.bin"
        key_path.write_text(public_key_pem, encoding="utf-8")
        payload_path.write_bytes(payload)
        signature_path.write_bytes(signature)
        try:
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey",
                 str(key_path), "-sigfile", str(signature_path), "-rawin",
                 "-in", str(payload_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ArchiveReceiptError("OpenSSL Ed25519 verifier is unavailable") from exc
        if result.returncode != 0:
            raise ArchiveReceiptError("archive receipt signature verification failed")


def verify_archive_receipt(
    *, receipt_path: Path, artifact_path: Path, trust_registry_path: Path,
    repository_root: Path, expected_head: str | None = None,
    expected_tree: str | None = None,
) -> VerificationResult:
    root = repository_root.resolve(strict=True)
    receipt_file = _regular_file(receipt_path, "receipt")
    artifact_file = _regular_file(artifact_path, "artifact")
    trust_file = _regular_file(trust_registry_path, "trust registry")
    if _inside(trust_file, root):
        raise ArchiveReceiptError(
            "trust registry must be administered and supplied outside the repository"
        )
    if receipt_file == trust_file or artifact_file == trust_file:
        raise ArchiveReceiptError("trust registry must be a distinct external object")

    receipt = _require_object(load_strict_json(receipt_file), "receipt", RECEIPT_KEYS)
    if _require_exact_int(receipt["schema_version"], "schema_version") != 1:
        raise ArchiveReceiptError("unsupported receipt schema_version")
    repository = _require_string(receipt["repository"], "repository")
    if repository != REPOSITORY:
        raise ArchiveReceiptError("receipt repository does not identify hepta-glasses")
    head = _require_string(receipt["head_commit"], "head_commit")
    tree = _require_string(receipt["source_tree"], "source_tree")
    if not HEX40.fullmatch(head) or not HEX40.fullmatch(tree):
        raise ArchiveReceiptError("head_commit and source_tree must be lowercase object IDs")
    if expected_head is not None and head != expected_head:
        raise ArchiveReceiptError("receipt head_commit does not match expected head")
    if expected_tree is not None and tree != expected_tree:
        raise ArchiveReceiptError("receipt source_tree does not match expected tree")

    name = _require_string(receipt["artifact_name"], "artifact_name")
    if name != f"hepta-source-evidence-{head}":
        raise ArchiveReceiptError("artifact_name is not bound to head_commit")
    stated_digest = _require_string(receipt["artifact_sha256"], "artifact_sha256")
    if not HEX64.fullmatch(stated_digest):
        raise ArchiveReceiptError("artifact_sha256 must be lowercase SHA-256")
    stated_size = _require_exact_int(receipt["artifact_size_bytes"], "artifact_size_bytes", 1)
    archive_object = _require_string(receipt["archive_object"], "archive_object")
    if archive_object != f"sha256:{stated_digest}":
        raise ArchiveReceiptError("archive_object is not content-addressed to artifact_sha256")

    archived_at = _parse_utc(receipt["archived_at"], "archived_at")
    retention_until = _parse_utc(receipt["retention_until"], "retention_until")
    if retention_until <= archived_at:
        raise ArchiveReceiptError("retention_until must be later than archived_at")
    custodian = _require_string(receipt["custodian"], "custodian")
    if len(custodian) > 256:
        raise ArchiveReceiptError("custodian is too long")
    key_id = _require_string(receipt["key_id"], "key_id")
    if not KEY_ID.fullmatch(key_id):
        raise ArchiveReceiptError("key_id has an invalid shape")

    actual_digest, actual_size = _sha256_and_size(artifact_file)
    if actual_digest != stated_digest:
        raise ArchiveReceiptError("artifact SHA-256 does not match receipt")
    if actual_size != stated_size:
        raise ArchiveReceiptError("artifact size does not match receipt")

    signature = _decode_signature(receipt["signature"])
    unsigned = dict(receipt)
    unsigned.pop("signature")
    public_key = _select_trust_key(load_strict_json(trust_file), key_id, archived_at)
    _verify_ed25519(public_key, canonical_json(unsigned), signature)
    return VerificationResult(
        repository, head, tree, name, stated_digest, stated_size, archive_object,
        custodian, key_id, receipt["archived_at"], receipt["retention_until"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--trust-registry", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-tree")
    args = parser.parse_args(argv)
    for value, label in ((args.expected_head, "expected head"), (args.expected_tree, "expected tree")):
        if value is not None and not HEX40.fullmatch(value):
            parser.error(f"{label} must be a lowercase 40-hex object ID")
    try:
        result = verify_archive_receipt(
            receipt_path=args.receipt, artifact_path=args.artifact,
            trust_registry_path=args.trust_registry,
            repository_root=args.repository_root, expected_head=args.expected_head,
            expected_tree=args.expected_tree,
        )
    except ArchiveReceiptError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
