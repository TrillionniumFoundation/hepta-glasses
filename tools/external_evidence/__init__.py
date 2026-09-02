"""Authenticated external-evidence validation package."""

from . import core as _core
from .snapshot_io import install_snapshot_io as _install_snapshot_io

# Install lexical-path snapshot semantics before any validator imports private
# I/O helpers from ``core``. This gives the complete validation transaction one
# immutable, aggregate-bounded byte view and binds ordinary directory objects,
# not only symbolic-link syntax.
_install_snapshot_io(_core)

from . import acceptance as _acceptance
from . import trust as _trust

# ``trust.py`` historically normalized SPKI by handing the mutable source path
# back to OpenSSL. Replace that module global with the snapshot-backed
# normalizer before any registry is loaded.
_trust._normalized_public_key_digest = _core._normalized_public_key_digest

from . import complete_closure as _complete_closure
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

# Install the immutable validation transaction on the policy module itself.
# This is deliberately stronger than wrapping only the package alias: callers
# that explicitly import ``tools.external_evidence.complete_closure`` must not
# bypass the same aggregate-bounded lexical-path snapshot used by the CLI and
# every package-level entrypoint.
_complete_closure.validate_bundle = validation_snapshot(
    _complete_closure.validate_bundle
)
_acceptance.validate_bundle = _complete_closure.validate_bundle
validate_acceptance = _acceptance.validate_acceptance
validate_bundle = _complete_closure.validate_bundle
review_set_digest = _complete_closure.review_set_digest
acceptance_context_digest = _complete_closure.acceptance_context_digest

__all__ = [
    "EvidenceError",
    "TrustKey",
    "TrustRegistry",
    "acceptance_context_digest",
    "canonical_bundle_digest",
    "canonical_review_statement",
    "canonical_submission_statement",
    "evidence_set_digest",
    "load_trust_registry",
    "review_set_digest",
    "safe_artifact_path",
    "validate_acceptance",
    "validate_artifact",
    "validate_bundle",
    "validate_candidate",
    "validate_submission",
]
