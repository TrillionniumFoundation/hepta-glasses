"""Authenticated external-evidence validation package."""

from . import core as _core
from .snapshot_io import install_snapshot_io as _install_snapshot_io

# Install lexical-path snapshot semantics before any validator module imports
# private I/O helpers from ``core``. This gives the entire package one immutable
# byte view even when a symbolic link is retargeted between validation phases.
_install_snapshot_io(_core)

from . import acceptance as _acceptance
from .core import (
    EvidenceError,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
    safe_artifact_path,
    validation_snapshot,
)
from .submission import validate_artifact, validate_candidate, validate_submission
from .trust import TrustKey, TrustRegistry, load_trust_registry

# Every supported entry point validates against one immutable byte snapshot.
# Patching the module function ensures both package callers and
# ``from .acceptance import validate_bundle`` callers (including the CLI) use
# the same TOCTOU-resistant boundary after package initialization.
_acceptance.validate_bundle = validation_snapshot(_acceptance.validate_bundle)
validate_acceptance = _acceptance.validate_acceptance
validate_bundle = _acceptance.validate_bundle

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
