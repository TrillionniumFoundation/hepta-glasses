#!/usr/bin/env python3
"""Create canonical Ed25519 submission/reviewer signatures for G9 evidence.

Private keys stay outside the repository. This utility writes only detached signature
bytes and the matching digest metadata into a custody bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools/validate_external_evidence.py"
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"
SPEC = importlib.util.spec_from_file_location("hepta_external_evidence", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
external = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(external)

from tools.external_evidence.core import (  # noqa: E402
    ED25519_SPKI_BYTES,
    ED25519_SPKI_PREFIX,
    MAX_PUBLIC_KEY_BYTES,
    read_object,
)


def read_bundle(path: Path) -> dict[str, Any]:
    return read_object(path, "external evidence bundle")


def contract_revision() -> str:
    value = read_object(CONTRACT_PATH, "external evidence contract")
    revision = value.get("contract_revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError("external evidence contract_revision is unavailable")
    return revision


def normalize_time(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("signature time must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_private_key_ed25519(private_key: Path) -> None:
    if not private_key.is_file():
        raise ValueError("private key is missing")
    if private_key.stat().st_size > MAX_PUBLIC_KEY_BYTES:
        raise ValueError("private key exceeds the bounded key-file size")
    data = private_key.read_bytes()
    if b"PRIVATE KEY" not in data:
        raise ValueError("private key file does not contain PEM private-key material")
    result = subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-outform",
            "DER",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("private key cannot be parsed non-interactively")
    if (
        len(result.stdout) != ED25519_SPKI_BYTES
        or not result.stdout.startswith(ED25519_SPKI_PREFIX)
    ):
        raise ValueError("private key must be an actual Ed25519 private key")


def sign_ed25519(private_key: Path, payload: bytes) -> bytes:
    verify_private_key_ed25519(private_key)
    with tempfile.TemporaryDirectory(prefix="hepta-evidence-sign-") as directory:
        root = Path(directory)
        payload_path = root / "payload.bin"
        signature_path = root / "signature.bin"
        payload_path.write_bytes(payload)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(private_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0 or not signature_path.is_file():
            raise RuntimeError("OpenSSL Ed25519 signing failed")
        signature = signature_path.read_bytes()
        if len(signature) != 64:
            raise RuntimeError("OpenSSL produced a non-Ed25519 signature")
        return signature


def _require_secure_directory_api() -> None:
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, name) for name in required_flags):
        raise ValueError(
            "platform cannot securely create a detached signature below custody root"
        )
    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    if os.open not in supports_dir_fd or os.mkdir not in supports_dir_fd:
        raise ValueError(
            "platform lacks directory-descriptor support for detached signatures"
        )


def _directory_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_or_create_directory(parent_fd: int, component: str) -> int:
    try:
        return os.open(component, _directory_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            return os.open(component, _directory_flags(), dir_fd=parent_fd)
        except OSError as error:
            raise ValueError(
                f"detached signature path contains an unsafe directory: {component}"
            ) from error
    except OSError as error:
        raise ValueError(
            f"detached signature path contains an unsafe directory: {component}"
        ) from error


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("detached signature write made no progress")
        remaining = remaining[written:]


def _create_scoped_file_exclusive(
    *,
    custody_root: Path,
    path: Path,
    data: bytes,
) -> Path:
    _require_secure_directory_api()
    try:
        resolved_root = custody_root.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"custody root is unavailable: {error}") from error
    if not resolved_root.is_dir():
        raise ValueError("custody root must be a directory")
    try:
        relative = path.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("detached signature escapes custody root") from error
    if not relative.parts or relative.name in {"", ".", ".."}:
        raise ValueError("detached signature path is invalid")

    opened_directories: list[int] = []
    output_fd: int | None = None
    created = False
    try:
        root_fd = os.open(resolved_root, _directory_flags())
        opened_directories.append(root_fd)
        current_fd = root_fd
        for component in relative.parts[:-1]:
            current_fd = _open_or_create_directory(current_fd, component)
            opened_directories.append(current_fd)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            output_fd = os.open(
                relative.name,
                flags,
                0o600,
                dir_fd=current_fd,
            )
            created = True
        except FileExistsError as error:
            raise ValueError(
                f"refusing to overwrite detached signature: {path}"
            ) from error
        except OSError as error:
            raise ValueError(
                f"cannot securely create detached signature: {path}"
            ) from error

        _write_all(output_fd, data)
        os.fsync(output_fd)
        created_state = os.fstat(output_fd)
        if not stat.S_ISREG(created_state.st_mode) or created_state.st_size != len(data):
            raise RuntimeError("detached signature was not written as one regular file")
    except Exception:
        if created and opened_directories:
            try:
                os.unlink(relative.name, dir_fd=opened_directories[-1])
            except OSError:
                pass
        raise
    finally:
        if output_fd is not None:
            os.close(output_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
    return resolved_root / relative


def write_signature(
    *,
    custody_root: Path,
    signature_uri: str,
    signature: bytes,
) -> tuple[Path, str]:
    path = external.safe_artifact_path(
        custody_root,
        signature_uri,
        label="detached signature",
    )
    created = _create_scoped_file_exclusive(
        custody_root=custody_root,
        path=path,
        data=signature,
    )
    return created, hashlib.sha256(signature).hexdigest()


def sign_submission(args: argparse.Namespace) -> dict[str, Any]:
    bundle = read_bundle(args.bundle)
    submissions = bundle.get("submissions")
    if not isinstance(submissions, list) or not 0 <= args.index < len(submissions):
        raise ValueError("submission index is out of range")
    submission = submissions[args.index]
    if not isinstance(submission, dict):
        raise ValueError("submission must be an object")
    issuer = submission.get("issuer")
    if not isinstance(issuer, dict) or not isinstance(issuer.get("key_id"), str):
        raise ValueError("submission issuer.key_id is required")

    signed_at = normalize_time(args.signed_at)
    submission["attestation"] = {
        "signed_at": signed_at,
        "statement_digest": "0" * 64,
        "signature_uri": args.signature_uri,
        "signature_sha256": "0" * 64,
    }
    payload = external.canonical_submission_statement(
        bundle,
        submission,
        contract_revision=contract_revision(),
    )
    signature = sign_ed25519(args.private_key, payload)
    path, signature_digest = write_signature(
        custody_root=args.custody_root,
        signature_uri=args.signature_uri,
        signature=signature,
    )
    submission["attestation"]["statement_digest"] = hashlib.sha256(payload).hexdigest()
    submission["attestation"]["signature_sha256"] = signature_digest
    args.bundle.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "kind": "submission",
        "index": args.index,
        "gap_id": submission.get("gap_id"),
        "signature_path": str(path),
        "statement_digest": submission["attestation"]["statement_digest"],
        "signature_sha256": signature_digest,
    }


def sign_reviewer(args: argparse.Namespace) -> dict[str, Any]:
    bundle = read_bundle(args.bundle)
    acceptance = bundle.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    reviewers = acceptance.get("reviewers")
    if not isinstance(reviewers, list) or not 0 <= args.index < len(reviewers):
        raise ValueError("reviewer index is out of range")
    reviewer = reviewers[args.index]
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("key_id"), str):
        raise ValueError("reviewer key_id is required")

    registry_digest = external.require_sha(
        args.trust_registry_sha256,
        label="--trust-registry-sha256",
        width=64,
    )
    trust_registry = bundle.get("trust_registry")
    if not isinstance(trust_registry, dict) or trust_registry.get("sha256") != registry_digest:
        raise ValueError("out-of-band trust registry digest differs from bundle binding")

    reviewer["signed_at"] = normalize_time(args.signed_at or reviewer.get("signed_at"))
    reviewer["statement_digest"] = "0" * 64
    reviewer["signature_uri"] = args.signature_uri
    reviewer["signature_sha256"] = "0" * 64
    payload = external.canonical_review_statement(
        bundle,
        reviewer,
        contract_revision=contract_revision(),
    )
    signature = sign_ed25519(args.private_key, payload)
    path, signature_digest = write_signature(
        custody_root=args.custody_root,
        signature_uri=args.signature_uri,
        signature=signature,
    )
    reviewer["statement_digest"] = hashlib.sha256(payload).hexdigest()
    reviewer["signature_sha256"] = signature_digest
    args.bundle.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "kind": "reviewer",
        "index": args.index,
        "identity": reviewer.get("identity"),
        "signature_path": str(path),
        "statement_digest": reviewer["statement_digest"],
        "signature_sha256": signature_digest,
    }


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    bundle = read_bundle(args.bundle)
    acceptance = bundle.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    acceptance["bundle_digest"] = None
    acceptance["bundle_digest"] = external.canonical_bundle_digest(bundle)
    args.bundle.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "kind": "bundle-digest",
        "bundle_digest": acceptance["bundle_digest"],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subcommands = root.add_subparsers(dest="command", required=True)

    submission = subcommands.add_parser("submission")
    submission.add_argument("--bundle", required=True, type=Path)
    submission.add_argument("--custody-root", required=True, type=Path)
    submission.add_argument("--index", required=True, type=int)
    submission.add_argument("--private-key", required=True, type=Path)
    submission.add_argument("--signature-uri", required=True)
    submission.add_argument("--signed-at")
    submission.set_defaults(handler=sign_submission)

    reviewer = subcommands.add_parser("reviewer")
    reviewer.add_argument("--bundle", required=True, type=Path)
    reviewer.add_argument("--custody-root", required=True, type=Path)
    reviewer.add_argument("--index", required=True, type=int)
    reviewer.add_argument("--private-key", required=True, type=Path)
    reviewer.add_argument("--signature-uri", required=True)
    reviewer.add_argument("--trust-registry-sha256", required=True)
    reviewer.add_argument("--signed-at")
    reviewer.set_defaults(handler=sign_reviewer)

    digest = subcommands.add_parser("finalize")
    digest.add_argument("--bundle", required=True, type=Path)
    digest.set_defaults(handler=finalize)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv or sys.argv[1:])
    try:
        result = args.handler(args)
    except (ValueError, RuntimeError, external.EvidenceError) as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
