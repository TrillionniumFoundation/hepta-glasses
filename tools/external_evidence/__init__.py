"""Authenticated external-evidence validation package."""

from .acceptance import validate_acceptance, validate_bundle
from .core import (
    EvidenceError,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
    safe_artifact_path,
)
from .submission import validate_artifact, validate_candidate, validate_submission
from .trust import TrustKey, TrustRegistry, load_trust_registry

__all__ = [
    "EvidenceError",
    "TrustKey",
    "TrustRegistry",
    "canonical_bundle_digest",
    "canonical_review_statement",
    "canonical_submission_statement",
    "evidence_set_digest",
    "load_trust_registry",
    "safe_artifact_path",
    "validate_acceptance",
    "validate_artifact",
    "validate_bundle",
    "validate_candidate",
    "validate_submission",
]
