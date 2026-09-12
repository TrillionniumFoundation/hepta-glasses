"""Authenticated external-evidence validation package."""

from . import core as _core
from .snapshot_io import install_snapshot_io as _install_snapshot_io

# Install the bounded byte-snapshot primitives first.
_install_snapshot_io(_core)

# Replace resolve-first scope handling before any validator or signer imports
# core helpers. Every evidence/key/signature path remains lexical and no-follow,
# ancestor identities are pinned across the complete validation transaction,
# and the visible final name must still identify the opened file after reading.
from .lexical_scope_policy import (
    install_lexical_scope_policy as _install_lexical_scope_policy,
)

_install_lexical_scope_policy(_core)

# The executable name is not an authority boundary when PATH, loader variables,
# or OpenSSL configuration remain caller controlled. Pin one root-owned,
# non-writable absolute system binary and a minimal subprocess environment
# before trust, signature, or private-key modules import their helpers.
from .openssl_policy import (
    install_core_openssl_policy as _install_core_openssl_policy,
    install_signing_io_openssl_policy as _install_signing_io_openssl_policy,
)

_install_core_openssl_policy(_core)
from . import signing_io as _signing_io

_install_signing_io_openssl_policy(_signing_io, _core)

# Make private-key reads, bundle reads, detached-signature creation, and
# immutable successor creation one lexical, no-follow directory-generation
# transaction. This installer runs before the high-level signing module imports
# its function references.
from .signing_custody_policy import (
    install_signing_io_policy as _install_signing_io_policy,
    install_signing_module_policy as _install_signing_module_policy,
)

_install_signing_io_policy(_signing_io, _core)

from . import acceptance as _acceptance
from . import submission as _submission
from . import trust as _trust

# Public-key normalization consumes the same pinned lexical byte snapshot used
# for hashing, parsing, and Ed25519 verification.
_trust._normalized_public_key_digest = _core._normalized_public_key_digest

# Bind canonical contract bytes, not only a human-selected revision label, into
# every issuer and reviewer Ed25519 preimage. Patch the module globals used by
# the G9 primitive validators before the G10 policy layer is imported.
from .semantic_binding import install_semantic_binding as _install_semantic_binding

_install_semantic_binding(
    _core,
    _submission,
    _acceptance,
)

from . import complete_closure as _complete_closure
from .authority_seat_policy import (
    install_global_authority_seat_policy as _install_global_authority_seat_policy,
)
from .core import (
    EvidenceError,
    canonical_bundle_digest,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
    safe_artifact_path,
)
from .runtime_policy import install_runtime_policy as _install_runtime_policy
from .submission import validate_artifact, validate_candidate, validate_submission
from .trust import TrustKey, TrustRegistry, load_trust_registry

# A key or identity/organization pair may span multiple gaps only while
# retaining one narrowly scoped authority class. This prevents a broadly
# enrolled key from impersonating unrelated authority seats across the final
# complete package.
_install_global_authority_seat_policy(
    _complete_closure,
    _core,
)

# Public package, direct policy-module and CLI paths use the current trusted
# clock, lexical no-follow object custody, and absolute-path OpenSSL policy. The
# private deterministic hook exists for unit tests only and is deliberately
# absent from ``__all__``.
validate_bundle, _validate_bundle_at_for_tests = _install_runtime_policy(
    _complete_closure,
    _core,
)
_acceptance.validate_bundle = validate_bundle
validate_acceptance = _acceptance.validate_acceptance
review_set_digest = _complete_closure.review_set_digest
acceptance_context_digest = _complete_closure.acceptance_context_digest

# Import and patch the high-level signer only after all canonical statement,
# runtime, executable, and low-level custody policies are installed. Later
# imports of tools.external_evidence.signing receive these wrapped functions.
from . import signing as _signing

_install_signing_module_policy(_signing, _core)

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
