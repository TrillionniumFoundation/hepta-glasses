#!/usr/bin/env python3
"""Authenticate authority-owned evidence using externally pinned Ed25519 keys."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.external_evidence import (  # noqa: E402,F401
    EvidenceError,
    TrustKey,
    TrustRegistry,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
    load_trust_registry,
    safe_artifact_path,
    validate_acceptance,
    validate_artifact,
    validate_bundle,
    validate_candidate,
    validate_submission,
)
from tools.external_evidence.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
