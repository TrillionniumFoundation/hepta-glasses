"""High-level authenticated evidence signing operations and CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (
    EvidenceError,
    MAX_JSON_BYTES,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    read_object,
    require_sha,
    safe_artifact_path,
)
from .signing_io import (
    atomic_replace_bundle,
    bundle_bytes,
    create_exclusive,
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


def _commit_bundle(
    args: argparse.Namespace,
    snapshot: Any,
    bundle: dict[str, Any],
) -> tuple[Path, str, bool]:
    data = bundle_bytes(bundle)
    output_uri = getattr(args, "output_bundle_uri", None)
    if output_uri is None:
        path, digest = atomic_replace_bundle(snapshot, data)
        return path, digest, False
    custody_root = getattr(args, "custody_root", None)
    if not isinstance(custody_root, Path):
        raise ValueError("--custody-root is required with --output-bundle-uri")
    path = safe_artifact_path(
        custody_root,
        output_uri,
        label="output bundle",
        maximum=MAX_JSON_BYTES,
    )
    path, digest = create_exclusive(custody_root, path, data, MAX_JSON_BYTES)
    return path, digest, True


def sign_submission(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_bundle_snapshot(args.bundle)
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
    signature = sign_ed25519(args.private_key, statement)
    submission["attestation"]["statement_digest"] = hashlib.sha256(statement).hexdigest()
    submission["attestation"]["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    signature_path, signature_digest = write_signature(
        args.custody_root,
        args.signature_uri,
        signature,
    )
    bundle_path, bundle_digest, immutable = _commit_bundle(args, snapshot, bundle)
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
    signature = sign_ed25519(args.private_key, statement)
    reviewer["statement_digest"] = hashlib.sha256(statement).hexdigest()
    reviewer["signature_sha256"] = hashlib.sha256(signature).hexdigest()
    signature_path, signature_digest = write_signature(
        args.custody_root,
        args.signature_uri,
        signature,
    )
    bundle_path, bundle_digest, immutable = _commit_bundle(args, snapshot, bundle)
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
    bundle = snapshot.value
    acceptance = bundle.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    acceptance["bundle_digest"] = None
    acceptance["bundle_digest"] = canonical_bundle_digest(bundle)
    path, digest, immutable = _commit_bundle(args, snapshot, bundle)
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
        command.add_argument("--output-bundle-uri")
        command.add_argument("--index", required=True, type=int)
        command.add_argument("--private-key", required=True, type=Path)
        command.add_argument("--signature-uri", required=True)
        command.add_argument("--signed-at")
        if name == "reviewer":
            command.add_argument("--trust-registry-sha256", required=True)
        command.set_defaults(handler=handler)
    digest = commands.add_parser("finalize")
    digest.add_argument("--bundle", required=True, type=Path)
    digest.add_argument("--custody-root", type=Path)
    digest.add_argument("--output-bundle-uri")
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
