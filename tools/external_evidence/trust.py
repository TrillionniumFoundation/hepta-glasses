from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import (
    ALLOWED_KEY_USAGES,
    AUTHORITY,
    MAX_PUBLIC_KEY_BYTES,
    MAX_REGISTRY_BYTES,
    _read_bounded_file,
    _resolve_openssl,
    _run_openssl,
    fail,
    parse_time,
    read_object,
    require_exact_keys,
    require_sha,
    require_string,
    require_string_array,
    safe_key_path,
    verify_public_key,
)


@dataclass(frozen=True)
class TrustKey:
    key_id: str
    identity: str
    organization: str
    algorithm: str
    public_key: Path
    public_key_sha256: str
    public_key_spki_sha256: str
    usages: frozenset[str]
    authority_classes: frozenset[str]
    allowed_gap_ids: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class TrustRegistry:
    registry_id: str
    digest: str
    keys: Mapping[str, TrustKey]
    expires_at: datetime

    def require_key(
        self,
        *,
        key_id: str,
        identity: str,
        organization: str,
        authority_class: str,
        gap_ids: Iterable[str],
        usage: str,
        signed_at: datetime,
        now: datetime,
        label: str,
    ) -> TrustKey:
        key = self.keys.get(key_id)
        if key is None:
            fail(f"{label} references an unknown trust-registry key: {key_id}")
        if usage not in key.usages:
            fail(f"{label} key {key_id} is not authorized for {usage}")
        if key.identity != identity or key.organization != organization:
            fail(f"{label} identity or organization differs from the pinned trust registry")
        if authority_class not in key.authority_classes:
            fail(f"{label} authority class is not granted to key {key_id}")
        requested_gaps = set(gap_ids)
        if not requested_gaps or not requested_gaps.issubset(key.allowed_gap_ids):
            fail(f"{label} key {key_id} is not authorized for gaps {sorted(requested_gaps)}")
        if signed_at < key.valid_from or signed_at >= key.valid_until:
            fail(f"{label} key {key_id} was not valid at signature time")
        if now >= key.valid_until:
            fail(f"{label} key {key_id} is expired")
        if key.revoked_at is not None and now >= key.revoked_at:
            fail(f"{label} key {key_id} is revoked")
        if signed_at > now:
            fail(f"{label}.signed_at is in the future")
        return key


def _normalized_public_key_digest(
    public_key: Path,
    *,
    openssl_binary: str,
    label: str,
) -> str:
    der = _run_openssl(
        [
            _resolve_openssl(openssl_binary),
            "pkey",
            "-pubin",
            "-in",
            str(public_key),
            "-pubout",
            "-outform",
            "DER",
        ],
        label=label,
    )
    return hashlib.sha256(der).hexdigest()


def load_trust_registry(
    path: Path | None,
    *,
    expected_digest: str | None,
    bundle_binding: Mapping[str, Any],
    contract: Mapping[str, Any],
    now: datetime,
    openssl_binary: str,
) -> TrustRegistry:
    if path is None:
        fail("an external trust registry is required")
    if expected_digest is None:
        fail("an out-of-band expected trust-registry SHA-256 is required")
    expected = require_sha(
        expected_digest,
        label="expected trust-registry SHA-256",
        width=64,
    )
    raw = _read_bounded_file(path, label="trust registry", maximum=MAX_REGISTRY_BYTES)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        fail(f"trust-registry external pin mismatch: expected {expected}, got {actual}")

    require_exact_keys(
        bundle_binding,
        required={"registry_id", "sha256"},
        optional=set(),
        label="bundle.trust_registry",
    )
    declared_id = require_string(
        bundle_binding["registry_id"],
        label="bundle.trust_registry.registry_id",
        maximum=200,
    )
    declared_digest = require_sha(
        bundle_binding["sha256"],
        label="bundle.trust_registry.sha256",
        width=64,
    )
    if declared_digest != actual:
        fail("bundle trust-registry digest differs from the externally pinned registry")

    registry = read_object(path, "trust registry", maximum_bytes=MAX_REGISTRY_BYTES)
    require_exact_keys(
        registry,
        required={
            "schema_version",
            "registry_id",
            "registry_revision",
            "issued_at",
            "expires_at",
            "keys",
        },
        optional=set(),
        label="trust registry",
    )
    profile = contract["trust_registry_profile"]
    if registry["schema_version"] != profile["schema_version"]:
        fail("trust-registry schema version differs from the evidence contract")
    registry_id = require_string(
        registry["registry_id"],
        label="trust registry.registry_id",
        maximum=200,
    )
    if registry_id != profile["registry_id"] or registry_id != declared_id:
        fail("trust-registry identity differs from the contract or bundle binding")
    require_string(
        registry["registry_revision"],
        label="trust registry.registry_revision",
        maximum=200,
    )
    issued_at = parse_time(registry["issued_at"], label="trust registry.issued_at")
    expires_at = parse_time(registry["expires_at"], label="trust registry.expires_at")
    assert issued_at is not None and expires_at is not None
    if issued_at > now:
        fail("trust registry was issued in the future")
    if expires_at <= now or expires_at <= issued_at:
        fail("trust registry is expired or has an invalid validity interval")

    raw_keys = registry["keys"]
    if not isinstance(raw_keys, list) or not (1 <= len(raw_keys) <= 256):
        fail("trust registry.keys must be a non-empty bounded array")
    allowed_gaps = set(contract["allowed_gap_ids"])
    keys: dict[str, TrustKey] = {}
    seen_public_key_spki: dict[str, str] = {}
    registry_root = path.parent
    for index, raw_key in enumerate(raw_keys):
        label = f"trust registry.keys[{index}]"
        if not isinstance(raw_key, dict):
            fail(f"{label} must be an object")
        require_exact_keys(
            raw_key,
            required={
                "key_id",
                "identity",
                "organization",
                "algorithm",
                "public_key_uri",
                "public_key_sha256",
                "usages",
                "authority_classes",
                "allowed_gap_ids",
                "valid_from",
                "valid_until",
                "revoked_at",
            },
            optional=set(),
            label=label,
        )
        key_id = require_string(raw_key["key_id"], label=f"{label}.key_id", maximum=500)
        if key_id in keys:
            fail(f"duplicate trust-registry key_id: {key_id}")
        identity = require_string(raw_key["identity"], label=f"{label}.identity", maximum=300)
        organization = require_string(
            raw_key["organization"],
            label=f"{label}.organization",
            maximum=300,
        )
        algorithm = require_string(
            raw_key["algorithm"],
            label=f"{label}.algorithm",
            maximum=40,
        )
        if algorithm != "ed25519":
            fail(f"{label}.algorithm must be ed25519")
        usages = frozenset(
            require_string_array(
                raw_key["usages"],
                label=f"{label}.usages",
                maximum=3,
                item_maximum=80,
            )
        )
        if not usages.issubset(ALLOWED_KEY_USAGES):
            fail(f"{label}.usages contains unsupported values")
        authority_classes = frozenset(
            require_string_array(
                raw_key["authority_classes"],
                label=f"{label}.authority_classes",
                maximum=64,
                item_maximum=80,
            )
        )
        if any(AUTHORITY.fullmatch(item) is None for item in authority_classes):
            fail(f"{label}.authority_classes contains a malformed value")
        key_gaps = frozenset(
            require_string_array(
                raw_key["allowed_gap_ids"],
                label=f"{label}.allowed_gap_ids",
                maximum=64,
                item_maximum=20,
            )
        )
        if not key_gaps.issubset(allowed_gaps):
            fail(f"{label}.allowed_gap_ids contains an unknown gap")
        valid_from = parse_time(raw_key["valid_from"], label=f"{label}.valid_from")
        valid_until = parse_time(raw_key["valid_until"], label=f"{label}.valid_until")
        revoked_at = parse_time(
            raw_key["revoked_at"],
            label=f"{label}.revoked_at",
            nullable=True,
        )
        assert valid_from is not None and valid_until is not None
        if valid_until <= valid_from:
            fail(f"{label} has an invalid key validity interval")
        if revoked_at is not None and revoked_at < valid_from:
            fail(f"{label}.revoked_at predates key validity")
        key_uri = require_string(
            raw_key["public_key_uri"],
            label=f"{label}.public_key_uri",
            maximum=1000,
        )
        public_key = safe_key_path(registry_root, key_uri, label=f"{label}.public_key_uri")
        public_bytes = _read_bounded_file(
            public_key,
            label=f"{label}.public_key",
            maximum=MAX_PUBLIC_KEY_BYTES,
        )
        public_digest = require_sha(
            raw_key["public_key_sha256"],
            label=f"{label}.public_key_sha256",
            width=64,
        )
        if hashlib.sha256(public_bytes).hexdigest() != public_digest:
            fail(f"{label} public-key digest mismatch")
        verify_public_key(
            public_key,
            openssl_binary=openssl_binary,
            label=f"{label}.public_key",
        )
        public_spki_digest = _normalized_public_key_digest(
            public_key,
            openssl_binary=openssl_binary,
            label=f"{label}.public_key",
        )
        previous_key_id = seen_public_key_spki.get(public_spki_digest)
        if previous_key_id is not None:
            fail(
                f"{label} reuses the cryptographic public key already bound to "
                f"{previous_key_id}"
            )
        seen_public_key_spki[public_spki_digest] = key_id
        keys[key_id] = TrustKey(
            key_id=key_id,
            identity=identity,
            organization=organization,
            algorithm=algorithm,
            public_key=public_key,
            public_key_sha256=public_digest,
            public_key_spki_sha256=public_spki_digest,
            usages=usages,
            authority_classes=authority_classes,
            allowed_gap_ids=key_gaps,
            valid_from=valid_from,
            valid_until=valid_until,
            revoked_at=revoked_at,
        )
    return TrustRegistry(
        registry_id=registry_id,
        digest=actual,
        keys=keys,
        expires_at=expires_at,
    )
