#!/usr/bin/env python3
"""Authenticate authority-owned evidence using externally pinned Ed25519 keys."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.external_evidence import (  # noqa: E402,F401
    EvidenceError,
    TrustKey,
    TrustRegistry,
    _validate_bundle_at_for_tests,
    acceptance_context_digest,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
    load_trust_registry,
    review_set_digest,
    safe_artifact_path,
    validate_acceptance,
    validate_artifact,
    validate_bundle as _runtime_validate_bundle,
    validate_candidate,
    validate_submission,
)
from tools.external_evidence.cli import main  # noqa: E402
from tools.external_evidence.core import (  # noqa: E402,F401
    canonical_bytes,
    require_sha,
    safe_key_path,
    verify_ed25519_bytes,
    verify_ed25519_file,
)

# The historical qualification fixture loads this source file under this exact
# non-package module name and injects a fixed clock. Preserve that deterministic
# test surface without exporting clock authority from the package, direct
# policy-module, or executable CLI entrypoints.
validate_bundle = (
    _validate_bundle_at_for_tests
    if __name__ == "validate_external_evidence"
    else _runtime_validate_bundle
)


def safe_custody_path(root: Path, uri: str, *, label: str) -> Path:
    """Backward-compatible alias for artifact-scoped custody paths."""

    return safe_artifact_path(root, uri, label=label)


def verify_ed25519(
    public_key_pem: str,
    message: bytes,
    signature: bytes,
    *,
    label: str,
    openssl_binary: str = "openssl",
) -> None:
    """Verify in-memory Ed25519 inputs through the canonical file verifier."""

    if openssl_binary != "openssl":
        raise EvidenceError(
            "custom OpenSSL executable selection is prohibited on the "
            "authority-bearing validation path"
        )
    if not isinstance(public_key_pem, str) or not public_key_pem.strip():
        raise TypeError("public_key_pem must be a non-empty string")
    if not isinstance(message, bytes):
        raise TypeError("message must be bytes")
    if not isinstance(signature, bytes):
        raise TypeError("signature must be bytes")

    with tempfile.TemporaryDirectory(prefix="hepta-evidence-verify-") as directory:
        root = Path(directory)
        public_key = root / "public.pem"
        signature_path = root / "signature.bin"
        public_key.write_text(public_key_pem, encoding="utf-8")
        signature_path.write_bytes(signature)
        verify_ed25519_bytes(
            public_key=public_key,
            message=message,
            signature_path=signature_path,
            openssl_binary="openssl",
            label=label,
        )


if __name__ == "__main__":
    raise SystemExit(main())
