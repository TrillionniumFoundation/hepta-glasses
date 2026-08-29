"""Signed skill manifest admission, capability-diff consent, and revocation."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping


class SkillError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


class SkillState(str, Enum):
    INSTALLED = "installed"
    REVOKED = "revoked"


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    version: str
    publisher: str
    entrypoint: str
    required_capabilities: frozenset[str]
    risk_tier: str
    data_classes: frozenset[str]
    allowed_network_domains: frozenset[str]
    timeout_ms: int
    package_digest: str
    signature_key_id: str
    signature: str

    def unsigned_document(self) -> dict[str, Any]:
        return {
            "allowed_network_domains": sorted(self.allowed_network_domains),
            "data_classes": sorted(self.data_classes),
            "entrypoint": self.entrypoint,
            "package_digest": self.package_digest,
            "publisher": self.publisher,
            "required_capabilities": sorted(self.required_capabilities),
            "risk_tier": self.risk_tier,
            "signature_key_id": self.signature_key_id,
            "skill_id": self.skill_id,
            "timeout_ms": self.timeout_ms,
            "version": self.version,
        }

    @property
    def manifest_digest(self) -> str:
        return hashlib.sha256(_canonical(self.unsigned_document())).hexdigest()


@dataclass(frozen=True)
class InstalledSkill:
    manifest: SkillManifest
    state: SkillState
    installed_at: int
    consent_digest: str


class SkillTrustStore:
    """Key-id based verifier; production keys should be public signing keys."""

    def __init__(self, keys: Mapping[str, bytes]) -> None:
        if not keys or any(len(secret) < 32 for secret in keys.values()):
            raise SkillError("skill_trust_store_invalid")
        self._keys = dict(keys)

    def sign_development(self, manifest: SkillManifest) -> SkillManifest:
        secret = self._keys.get(manifest.signature_key_id)
        if secret is None:
            raise SkillError("skill_signing_key_unknown")
        signature = hmac.new(
            secret,
            _canonical(manifest.unsigned_document()),
            hashlib.sha256,
        ).hexdigest()
        return replace(manifest, signature=signature)

    def verify(self, manifest: SkillManifest) -> None:
        secret = self._keys.get(manifest.signature_key_id)
        if secret is None:
            raise SkillError("skill_signing_key_unknown")
        expected = hmac.new(
            secret,
            _canonical(manifest.unsigned_document()),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, manifest.signature):
            raise SkillError("skill_signature_invalid")


class SkillRegistry:
    def __init__(
        self,
        *,
        trust_store: SkillTrustStore,
        allowed_publishers: frozenset[str],
        allowed_network_domains: frozenset[str],
    ) -> None:
        self.trust_store = trust_store
        self.allowed_publishers = allowed_publishers
        self.allowed_network_domains = allowed_network_domains
        self._skills: dict[str, InstalledSkill] = {}

    def install(
        self,
        manifest: SkillManifest,
        *,
        consented_capabilities: frozenset[str],
        consented_data_classes: frozenset[str],
        now: int,
    ) -> InstalledSkill:
        self._validate_manifest(manifest)
        if not manifest.required_capabilities.issubset(consented_capabilities):
            raise SkillError("skill_capability_consent_missing")
        if not manifest.data_classes.issubset(consented_data_classes):
            raise SkillError("skill_data_consent_missing")
        existing = self._skills.get(manifest.skill_id)
        if existing is not None:
            if existing.state is SkillState.REVOKED:
                raise SkillError("skill_revoked")
            added_capabilities = (
                manifest.required_capabilities
                - existing.manifest.required_capabilities
            )
            added_data = manifest.data_classes - existing.manifest.data_classes
            if not added_capabilities.issubset(consented_capabilities):
                raise SkillError("skill_upgrade_capability_reconsent_required")
            if not added_data.issubset(consented_data_classes):
                raise SkillError("skill_upgrade_data_reconsent_required")
        consent_digest = hashlib.sha256(
            _canonical(
                {
                    "capabilities": sorted(consented_capabilities),
                    "data_classes": sorted(consented_data_classes),
                    "manifest_digest": manifest.manifest_digest,
                }
            )
        ).hexdigest()
        installed = InstalledSkill(
            manifest=manifest,
            state=SkillState.INSTALLED,
            installed_at=now,
            consent_digest=consent_digest,
        )
        self._skills[manifest.skill_id] = installed
        return installed

    def revoke(self, skill_id: str) -> InstalledSkill:
        installed = self._skills.get(skill_id)
        if installed is None:
            raise SkillError("skill_unknown")
        revoked = replace(installed, state=SkillState.REVOKED)
        self._skills[skill_id] = revoked
        return revoked

    def resolve(self, skill_id: str) -> InstalledSkill:
        installed = self._skills.get(skill_id)
        if installed is None:
            raise SkillError("skill_unknown")
        if installed.state is SkillState.REVOKED:
            raise SkillError("skill_revoked")
        return installed

    def _validate_manifest(self, manifest: SkillManifest) -> None:
        self.trust_store.verify(manifest)
        if manifest.publisher not in self.allowed_publishers:
            raise SkillError("skill_publisher_not_allowed")
        if manifest.risk_tier == "R4":
            raise SkillError("skill_r4_forbidden")
        if not manifest.allowed_network_domains.issubset(
            self.allowed_network_domains
        ):
            raise SkillError("skill_network_domain_not_allowed")
        if manifest.timeout_ms < 1 or manifest.timeout_ms > 300_000:
            raise SkillError("skill_timeout_invalid")
        if len(manifest.package_digest) != 64:
            raise SkillError("skill_package_digest_invalid")
