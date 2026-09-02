"""High-level authenticated evidence signing operations and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .core import (
    ARTIFACT_URI,
    EvidenceError,
    MAX_JSON_BYTES,
    MAX_SIGNATURE_BYTES,
    _stable_read_target,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    read_object,
    require_sha,
)
from .signing_io import (
    bundle_bytes,
    create_scoped_uri_exclusive,
    load_bundle_snapshot,
    read_bundle,
    read_private_key_snapshot as _read_private_key_snapshot,
    sign_ed25519,
    verify_private_key_ed25519,
    write_signature,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"


def contract_revision() -> str:
    revision = read_object(CONTRACT_PATH, "external evidence contract").get(
        "contract_revision"
    )
    if not isinstance(revision, str) or not revision:
        raise ValueError("external evidence contract_revision is unavailable")
    return revision


def normalize_time(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not value or value != value.strip():
        raise ValueError("signature time must be canonical and non-empty")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("signature time must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolved_custody_root(root: Any) -> Path:
    if not isinstance(root, Path):
        raise ValueError("--custody-root is required")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"custody root is unavailable: {error}") from error
    if not resolved.is_dir():
        raise ValueError("custody root must be a directory")
    return resolved


def _require_bundle_inside_custody(snapshot: Any, root: Any) -> Path:
    resolved = _resolved_custody_root(root)
    try:
        snapshot.path.relative_to(resolved)
    except ValueError as error:
        raise ValueError(
            "input evidence bundle must be located below --custody-root"
        ) from error
    return resolved


def _canonical_output_uri(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty artifact URI")
    match = ARTIFACT_URI.fullmatch(value)
    if match is None:
        raise ValueError(f"{label} must use artifact:// with a scoped relative path")
    raw = match.group(1)
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != raw
    ):
        raise ValueError(f"{label} must use a canonical scoped relative path")
    return value


def _preflight_output_uris(args: argparse.Namespace, *, include_signature: bool) -> None:
    successor_uri = _canonical_output_uri(
        getattr(args, "output_bundle_uri", None),
        label="output bundle",
    )
    if not include_signature:
        return
    signature_uri = _canonical_output_uri(
        getattr(args, "signature_uri", None),
        label="detached signature",
    )
    if signature_uri == successor_uri:
        raise ValueError("detached signature and output bundle must use distinct URIs")


def _verify_created_output(
    *,
    custody_root: Path,
    path: Path,
    expected: bytes,
    maximum: int,
    label: str,
) -> str:
    """Re-read the visible canonical output before reporting command success."""

    lexical = Path(os.path.abspath(os.fspath(path)))
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(f"{label} is not visible after creation: {error}") from error
    if resolved != lexical:
        raise RuntimeError(f"{label} was redirected after creation")
    try:
        resolved.relative_to(custody_root)
    except ValueError as error:
        raise RuntimeError(f"{label} escaped custody after creation") from error
    state = os.stat(lexical, follow_symlinks=False)
    if not stat.S_ISREG(state.st_mode):
        raise RuntimeError(f"{label} is no longer a regular file")
    if state.st_mode & 0o077:
        raise RuntimeError(f"{label} permissions are not private")
    observed = _stable_read_target(
        lexical,
        label=label,
        maximum=maximum,
    )
    if observed != expected:
        raise RuntimeError(f"{label} changed before command completion")
    return hashlib.sha256(observed).hexdigest()


def _commit_bundle(
    args: argparse.Namespace,
    snapshot: Any,
    serialized: bytes,
    custody_root: Path,
) -> tuple[Path, str, bool]:
    """Create an immutable successor and leave the signed input untouched.

    Portable POSIX rename operations do not provide a conditional
    compare-and-swap against an expected inode. Authority-bearing evidence
    therefore advances only through fresh, exclusive successor objects.
    """

    del snapshot
    output_uri = _canonical_output_uri(
        getattr(args, "output_bundle_uri", None),
        label="output bundle",
    )
    path, digest = create_scoped_uri_exclusive(
        custody_root,
        output_uri,
        serialized,
        MAX_JSON_BYTES,
        label="output bundle",
    )
    observed_digest = _verify_created_output(
        custody_root=custody_root,
        path=path,
        expected=serialized,
        maximum=MAX_JSON_BYTES,
        label="output bundle",
    )
    if observed_digest != digest:
        raise RuntimeError("output bundle digest changed before command completion")
    return path, digest, True


def sign_submission(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_bundle_snapshot(args.bundle)
    custody_root = _require_bundle_inside_custody(snapshot, args.custody_root)
    _preflight_output_uris(args, include_signature=True)
    bundle = snapshot.value
    submissions = bundle.get("submissions")
    if not isinstance(submissions, list) or not 0 <= args.index < len(submissions):
        raise ValueError("submission index is out of range")
    submission = submissions[args.index]
    if not isinstance(submission, dict):
        raise ValueError("submission must be an object")
    issuer = submission.get("issuer")
    if not isinstance(issuer, dict) or not isinstance(issuer.get("key_id"), str):
        raise ValueError("submission issuer.key_id is required")

    submission["attestation"] = {
        "signed_at": normalize_time(args.signed_at),
        "statement_digest": "0" * 64,
        "signature_uri": args.signature_uri,
        "signature_sha256": "0" * 64,
    }
    statement = canonical_submission_statement(
        bundle,
        submission,
        contract_revision=contract_revision(),
    )
    signature = sign_ed25519(
        args.private_key,
        statement,
        forbidden_root=custody_root,
    )
    submission["attestation"]["statement_digest"] = hashlib.sha256(statement).hexdigest()
    submission["attestation"]["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    serialized = bundle_bytes(bundle)

    signature_path, signature_digest = write_signature(
        custody_root,
        args.signature_uri,
        signature,
    )
    observed_signature_digest = _verify_created_output(
        custody_root=custody_root,
        path=signature_path,
        expected=signature,
        maximum=MAX_SIGNATURE_BYTES,
        label="detached signature",
    )
    if observed_signature_digest != signature_digest:
        raise RuntimeError("detached signature digest changed before command completion")

    bundle_path, bundle_digest, immutable = _commit_bundle(
        args,
        snapshot,
        serialized,
        custody_root,
    )
    return {
        "ok": True,
        "kind": "submission",
        "index": args.index,
        "gap_id": submission.get("gap_id"),
        "signature_path": str(signature_path),
        "statement_digest": submission["attestation"]["statement_digest"],
        "signature_sha256": signature_digest,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_digest,
        "input_bundle_unchanged": immutable,
    }


def sign_reviewer(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_bundle_snapshot(args.bundle)
    custody_root = _require_bundle_inside_custody(snapshot, args.custody_root)
    _preflight_output_uris(args, include_signature=True)
    bundle = snapshot.value
    acceptance = bundle.get("acceptance")
    reviewers = acceptance.get("reviewers") if isinstance(acceptance, dict) else None
    if not isinstance(reviewers, list) or not 0 <= args.index < len(reviewers):
        raise ValueError("reviewer index is out of range")
    reviewer = reviewers[args.index]
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("key_id"), str):
        raise ValueError("reviewer key_id is required")

    registry_digest = require_sha(
        args.trust_registry_sha256,
        label="--trust-registry-sha256",
        width=64,
    )
    registry = bundle.get("trust_registry")
    if not isinstance(registry, dict) or registry.get("sha256") != registry_digest:
        raise ValueError("out-of-band trust registry digest differs from bundle binding")
    reviewer["signed_at"] = normalize_time(args.signed_at or reviewer.get("signed_at"))
    reviewer["statement_digest"] = "0" * 64
    reviewer["signature_uri"] = args.signature_uri
    reviewer["signature_sha256"] = "0" * 64

    statement = canonical_review_statement(
        bundle,
        reviewer,
        contract_revision=contract_revision(),
    )
    signature = sign_ed25519(
        args.private_key,
        statement,
        forbidden_root=custody_root,
    )
    reviewer["statement_digest"] = hashlib.sha256(statement).hexdigest()
    reviewer["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    serialized = bundle_bytes(bundle)

    signature_path, signature_digest = write_signature(
        custody_root,
        args.signature_uri,
        signature,
    )
    observed_signature_digest = _verify_created_output(
        custody_root=custody_root,
        path=signature_path,
        expected=signature,
        maximum=MAX_SIGNATURE_BYTES,
        label="detached signature",
    )
    if observed_signature_digest != signature_digest:
        raise RuntimeError("detached signature digest changed before command completion")

    bundle_path, bundle_digest, immutable = _commit_bundle(
        args,
        snapshot,
        serialized,
        custody_root,
    )
    return {
        "ok": True,
        "kind": "reviewer",
        "index": args.index,
        "identity": reviewer.get("identity"),
        "signature_path": str(signature_path),
        "statement_digest": reviewer["statement_digest"],
        "signature_sha256": signature_digest,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_digest,
        "input_bundle_unchanged": immutable,
    }


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_bundle_snapshot(args.bundle)
    custody_root = _require_bundle_inside_custody(snapshot, args.custody_root)
    _preflight_output_uris(args, include_signature=False)
    bundle = snapshot.value
    acceptance = bundle.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    acceptance["bundle_digest"] = None
    acceptance["bundle_digest"] = canonical_bundle_digest(bundle)
    serialized = bundle_bytes(bundle)
    path, digest, immutable = _commit_bundle(
        args,
        snapshot,
        serialized,
        custody_root,
    )
    return {
        "ok": True,
        "kind": "bundle-digest",
        "bundle_digest": acceptance["bundle_digest"],
        "bundle_path": str(path),
        "bundle_sha256": digest,
        "input_bundle_unchanged": immutable,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name, handler in (("submission", sign_submission), ("reviewer", sign_reviewer)):
        command = commands.add_parser(name)
        command.add_argument("--bundle", required=True, type=Path)
        command.add_argument("--custody-root", required=True, type=Path)
        command.add_argument("--output-bundle-uri", required=True)
        command.add_argument("--index", required=True, type=int)
        command.add_argument("--private-key", required=True, type=Path)
        command.add_argument("--signature-uri", required=True)
        command.add_argument("--signed-at")
        if name == "reviewer":
            command.add_argument("--trust-registry-sha256", required=True)
        command.set_defaults(handler=handler)
    digest = commands.add_parser("finalize")
    digest.add_argument("--bundle", required=True, type=Path)
    digest.add_argument("--custody-root", required=True, type=Path)
    digest.add_argument("--output-bundle-uri", required=True)
    digest.set_defaults(handler=finalize)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv or sys.argv[1:])
    try:
        result = args.handler(args)
    except (ValueError, RuntimeError, OSError, EvidenceError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


__all__ = [
    "_read_private_key_snapshot",
    "contract_revision",
    "finalize",
    "main",
    "normalize_time",
    "parser",
    "read_bundle",
    "sign_ed25519",
    "sign_reviewer",
    "sign_submission",
    "verify_private_key_ed25519",
    "write_signature",
]
