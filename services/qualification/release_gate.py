"""Fail-closed source and product release evidence gate.

Source mode validates exact-head repository evidence. Product mode additionally
requires independently signed attestations. Plain caller-authored product JSON is
never release authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class ReleaseGateError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class EvidenceKey:
    issuer: str
    allowed_kinds: frozenset[str]
    secret: bytes


class EvidenceTrustStore:
    """Injected product-attestation trust roots.

    The reference format uses HMAC keys so the gate stays dependency-free. A
    production trust-store file must be supplied from a protected secret mount,
    never committed to the repository or embedded in the release bundle.
    """

    def __init__(self, keys: Mapping[str, EvidenceKey]) -> None:
        if not keys:
            raise ReleaseGateError("release_trust_store_empty")
        for key_id, key in keys.items():
            if (
                not key_id
                or not key.issuer
                or not key.allowed_kinds
                or len(key.secret) < 32
            ):
                raise ReleaseGateError("release_trust_key_invalid")
        self._keys = dict(keys)

    @classmethod
    def from_document(cls, value: Mapping[str, Any]) -> "EvidenceTrustStore":
        records = value.get("keys")
        if not isinstance(records, list):
            raise ReleaseGateError("release_trust_store_invalid")
        keys: dict[str, EvidenceKey] = {}
        for record in records:
            if not isinstance(record, Mapping):
                raise ReleaseGateError("release_trust_store_invalid")
            if set(record) != {
                "allowed_kinds",
                "issuer",
                "key_id",
                "secret_hex",
            }:
                raise ReleaseGateError("release_trust_store_invalid")
            key_id = record.get("key_id")
            issuer = record.get("issuer")
            allowed_kinds = record.get("allowed_kinds")
            secret_hex = record.get("secret_hex")
            if (
                not isinstance(key_id, str)
                or not isinstance(issuer, str)
                or not isinstance(allowed_kinds, list)
                or not all(isinstance(item, str) and item for item in allowed_kinds)
                or not isinstance(secret_hex, str)
                or len(secret_hex) < 64
                or len(secret_hex) % 2 != 0
            ):
                raise ReleaseGateError("release_trust_store_invalid")
            try:
                secret = bytes.fromhex(secret_hex)
            except ValueError as error:
                raise ReleaseGateError("release_trust_store_invalid") from error
            if key_id in keys:
                raise ReleaseGateError("release_trust_key_duplicate")
            keys[key_id] = EvidenceKey(
                issuer=issuer,
                allowed_kinds=frozenset(allowed_kinds),
                secret=secret,
            )
        return cls(keys)

    def sign_development(
        self,
        attestation: Mapping[str, Any],
        *,
        key_id: str,
    ) -> dict[str, Any]:
        """Return a signed copy for tests or controlled evidence tooling."""

        key = self._keys.get(key_id)
        if key is None:
            raise ReleaseGateError("release_attestation_key_unknown")
        unsigned = dict(attestation)
        unsigned.pop("signature", None)
        if unsigned.get("issuer") != key.issuer:
            raise ReleaseGateError("release_attestation_issuer_mismatch")
        if unsigned.get("kind") not in key.allowed_kinds:
            raise ReleaseGateError("release_attestation_kind_not_allowed")
        signed = dict(unsigned)
        signed["signature"] = hmac.new(
            key.secret,
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return signed

    def verify(
        self,
        attestation: Mapping[str, Any],
        *,
        expected_repository: str,
        expected_commit: str,
        expected_tree: str,
        now: int,
        maximum_validity_seconds: int,
    ) -> bool:
        required = {
            "commit",
            "expires_at",
            "issued_at",
            "issuer",
            "key_id",
            "kind",
            "payload",
            "repository",
            "schema",
            "signature",
            "tree",
        }
        if set(attestation) != required:
            return False
        key_id = attestation.get("key_id")
        issuer = attestation.get("issuer")
        kind = attestation.get("kind")
        issued_at = attestation.get("issued_at")
        expires_at = attestation.get("expires_at")
        signature = attestation.get("signature")
        payload = attestation.get("payload")
        key = self._keys.get(key_id) if isinstance(key_id, str) else None
        if (
            key is None
            or issuer != key.issuer
            or kind not in key.allowed_kinds
            or attestation.get("schema") != "hepta.product-attestation.v1"
            or attestation.get("repository") != expected_repository
            or attestation.get("commit") != expected_commit
            or attestation.get("tree") != expected_tree
            or not isinstance(payload, Mapping)
            or not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or issued_at > now
            or expires_at <= now
            or expires_at <= issued_at
            or expires_at - issued_at > maximum_validity_seconds
            or not isinstance(signature, str)
            or len(signature) != 64
        ):
            return False
        try:
            bytes.fromhex(signature)
        except ValueError:
            return False
        unsigned = dict(attestation)
        unsigned.pop("signature")
        expected = hmac.new(
            key.secret,
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


@dataclass(frozen=True)
class GateResult:
    mode: str
    passed: bool
    checks: Mapping[str, bool]
    missing: tuple[str, ...]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "checks": dict(self.checks),
            "missing": list(self.missing),
            "mode": self.mode,
            "passed": self.passed,
        }


class ReleaseGate:
    SOURCE_REQUIRED_CI_CHECKS = frozenset(
        {
            "flutter",
            "repository-contracts",
            "secret-and-boundary-scan",
        }
    )
    PRODUCT_REQUIRED_CI_CHECKS = SOURCE_REQUIRED_CI_CHECKS | frozenset(
        {"source-evidence"}
    )
    REQUIRED_ATTESTATION_KINDS = frozenset(
        {
            "branch_protection",
            "device.android",
            "device.ios",
            "drill.kill_switch",
            "drill.rollback",
            "pilot",
            "review.legal",
            "review.privacy",
            "review.security",
            "signing.android",
            "signing.ios",
            "signing.provenance",
        }
    )

    def __init__(
        self,
        *,
        trust_store: EvidenceTrustStore | None = None,
        clock: Callable[[], int] | None = None,
        maximum_attestation_validity_seconds: int = 31 * 24 * 60 * 60,
    ) -> None:
        if maximum_attestation_validity_seconds < 1:
            raise ReleaseGateError("release_attestation_validity_invalid")
        self.trust_store = trust_store
        self.clock = clock or (lambda: int(time.time()))
        self.maximum_attestation_validity_seconds = (
            maximum_attestation_validity_seconds
        )

    def evaluate(self, bundle: Mapping[str, Any], *, mode: str) -> GateResult:
        if mode not in {"source", "product"}:
            raise ReleaseGateError("release_mode_invalid")
        source = bundle.get("source")
        if not isinstance(source, Mapping):
            raise ReleaseGateError("release_source_evidence_missing")
        ci_checks = source.get("ci_checks")
        ci_map = (
            {
                item.get("name"): item.get("conclusion")
                for item in ci_checks
                if isinstance(item, Mapping)
            }
            if isinstance(ci_checks, list)
            else {}
        )
        checks: dict[str, bool] = {
            "exact_repository": isinstance(source.get("repository"), str)
            and bool(source.get("repository")),
            "exact_commit": self._digest(source.get("commit"), 40),
            "exact_tree": self._digest(source.get("tree"), 40),
            "required_ci": all(
                ci_map.get(name) == "success"
                for name in self.SOURCE_REQUIRED_CI_CHECKS
            ),
            "sbom": self._digest(self._nested(source, "sbom", "sha256"), 64),
            "provenance": self._digest(
                self._nested(source, "provenance", "sha256"), 64
            ),
            "contracts_version": isinstance(source.get("contracts_version"), str)
            and bool(source.get("contracts_version")),
        }
        if mode == "product":
            checks.update(self._product_checks(bundle, source, ci_map))
        missing = tuple(sorted(name for name, passed in checks.items() if not passed))
        return GateResult(
            mode=mode,
            passed=not missing,
            checks=checks,
            missing=missing,
        )

    def _product_checks(
        self,
        bundle: Mapping[str, Any],
        source: Mapping[str, Any],
        ci_map: Mapping[Any, Any],
    ) -> dict[str, bool]:
        base = {
            "product_required_ci": all(
                ci_map.get(name) == "success"
                for name in self.PRODUCT_REQUIRED_CI_CHECKS
            ),
            "attestation_set_complete": False,
            "attestation_set_unique": False,
            "branch_protected": False,
            "branch_reviews": False,
            "branch_force_push_disabled": False,
            "branch_required_checks": False,
            "android_device_qualification": False,
            "ios_device_qualification": False,
            "security_review": False,
            "privacy_review": False,
            "legal_review": False,
            "kill_switch_drill": False,
            "rollback_drill": False,
            "android_signing": False,
            "ios_signing": False,
            "release_provenance": False,
            "pilot_cohort": False,
            "pilot_crash_free": False,
            "pilot_duplicate_effects": False,
        }
        attestations = bundle.get("product_attestations")
        if self.trust_store is None or not isinstance(attestations, list):
            return base
        repository = source.get("repository")
        commit = source.get("commit")
        tree = source.get("tree")
        if not all(isinstance(item, str) and item for item in (repository, commit, tree)):
            return base

        verified: dict[str, Mapping[str, Any]] = {}
        duplicate = False
        now = self.clock()
        for item in attestations:
            if not isinstance(item, Mapping):
                continue
            kind = item.get("kind")
            if not isinstance(kind, str):
                continue
            if kind in verified:
                duplicate = True
                continue
            if self.trust_store.verify(
                item,
                expected_repository=repository,
                expected_commit=commit,
                expected_tree=tree,
                now=now,
                maximum_validity_seconds=self.maximum_attestation_validity_seconds,
            ):
                verified[kind] = item

        base["attestation_set_unique"] = not duplicate
        base["attestation_set_complete"] = (
            self.REQUIRED_ATTESTATION_KINDS.issubset(verified)
        )

        branch = self._payload(verified, "branch_protection")
        required_checks = branch.get("required_checks")
        base.update(
            {
                "branch_protected": branch.get("protected") is True,
                "branch_reviews": self._integer_at_least(
                    branch.get("required_approvals"), 1
                ),
                "branch_force_push_disabled": (
                    branch.get("force_pushes_allowed") is False
                ),
                "branch_required_checks": isinstance(required_checks, list)
                and all(isinstance(item, str) for item in required_checks)
                and self.PRODUCT_REQUIRED_CI_CHECKS.issubset(set(required_checks)),
                "android_device_qualification": self._passed_report(
                    self._payload(verified, "device.android")
                ),
                "ios_device_qualification": self._passed_report(
                    self._payload(verified, "device.ios")
                ),
                "security_review": self._approved_review(
                    self._payload(verified, "review.security")
                ),
                "privacy_review": self._approved_review(
                    self._payload(verified, "review.privacy")
                ),
                "legal_review": self._approved_review(
                    self._payload(verified, "review.legal")
                ),
                "kill_switch_drill": self._passed_report(
                    self._payload(verified, "drill.kill_switch")
                ),
                "rollback_drill": self._passed_report(
                    self._payload(verified, "drill.rollback")
                ),
                "android_signing": self._digest(
                    self._payload(verified, "signing.android").get(
                        "artifact_digest"
                    ),
                    64,
                ),
                "ios_signing": self._digest(
                    self._payload(verified, "signing.ios").get(
                        "artifact_digest"
                    ),
                    64,
                ),
                "release_provenance": self._digest(
                    self._payload(verified, "signing.provenance").get(
                        "provenance_digest"
                    ),
                    64,
                ),
            }
        )
        pilot = self._payload(verified, "pilot")
        base.update(
            {
                "pilot_cohort": self._integer_at_least(
                    pilot.get("cohort_size"), 5
                )
                and self._digest(pilot.get("report_digest"), 64),
                "pilot_crash_free": self._number_at_least(
                    pilot.get("crash_free_rate"), 0.99
                ),
                "pilot_duplicate_effects": pilot.get("duplicate_effects") == 0
                and not isinstance(pilot.get("duplicate_effects"), bool),
            }
        )
        return base

    @staticmethod
    def _payload(
        verified: Mapping[str, Mapping[str, Any]],
        kind: str,
    ) -> Mapping[str, Any]:
        attestation = verified.get(kind)
        payload = attestation.get("payload") if attestation else None
        return payload if isinstance(payload, Mapping) else {}

    @classmethod
    def _passed_report(cls, payload: Mapping[str, Any]) -> bool:
        return payload.get("passed") is True and cls._digest(
            payload.get("report_digest"), 64
        )

    @classmethod
    def _approved_review(cls, payload: Mapping[str, Any]) -> bool:
        return payload.get("decision") == "approved" and cls._digest(
            payload.get("review_digest"), 64
        )

    @staticmethod
    def _integer_at_least(value: Any, minimum: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= minimum

    @staticmethod
    def _number_at_least(value: Any, minimum: float) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) >= minimum
        )

    @staticmethod
    def _nested(value: Mapping[str, Any], first: str, second: str) -> Any:
        nested = value.get(first)
        return nested.get(second) if isinstance(nested, Mapping) else None

    @staticmethod
    def _digest(value: Any, length: int) -> bool:
        return (
            isinstance(value, str)
            and len(value) == length
            and value == value.lower()
            and all(character in "0123456789abcdef" for character in value)
        )
