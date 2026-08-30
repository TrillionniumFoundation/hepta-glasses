"""Fail-closed source and product release evidence gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ReleaseGateError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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
            "android-native",
            "flutter",
            "ios-native",
            "native-sanitizers",
            "repository-contracts",
            "secret-and-boundary-scan",
        }
    )
    PRODUCT_REQUIRED_CI_CHECKS = SOURCE_REQUIRED_CI_CHECKS | frozenset(
        {"source-evidence"}
    )
    REQUIRED_SBOM_ECOSYSTEMS = frozenset(
        {
            "application",
            "build-tool",
            "cocoapods",
            "gradle-plugin",
            "maven",
            "pub",
            "vendored",
        }
    )

    def __init__(
        self,
        *,
        expected_contracts_version: str = "2026-08-30-g5",
    ) -> None:
        if not expected_contracts_version:
            raise ReleaseGateError("contracts_version_invalid")
        self.expected_contracts_version = expected_contracts_version

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
        sbom = self._mapping(source.get("sbom"))
        ecosystems = self._mapping(sbom.get("ecosystem_counts"))
        history = self._mapping(source.get("credential_history"))
        file_count = self._integer(sbom.get("file_count"))
        package_count = self._integer(sbom.get("package_count"))
        relationship_count = self._integer(sbom.get("relationship_count"))
        vendored_count = self._integer(sbom.get("vendored_component_count"))

        checks: dict[str, bool] = {
            "exact_commit": self._digest(source.get("commit"), 40),
            "exact_tree": self._digest(source.get("tree"), 40),
            "required_ci": all(
                ci_map.get(name) == "success"
                for name in self.SOURCE_REQUIRED_CI_CHECKS
            ),
            "sbom": self._digest(sbom.get("sha256"), 64),
            "sbom_inventory": (
                file_count > 0
                and package_count > 0
                and relationship_count >= file_count
                and vendored_count >= 2
                and self.REQUIRED_SBOM_ECOSYSTEMS.issubset(ecosystems)
            ),
            "provenance": self._digest(
                self._nested(source, "provenance", "sha256"),
                64,
            ),
            "credential_history": (
                self._digest(history.get("sha256"), 64)
                and self._integer(history.get("current_tree_findings")) == 0
                and self._integer(
                    history.get("historical_unique_fingerprints")
                )
                >= 0
            ),
            "third_party_manifest": self._digest(
                self._nested(source, "third_party_manifest", "sha256"),
                64,
            ),
            "contracts_version": (
                source.get("contracts_version")
                == self.expected_contracts_version
            ),
        }
        if mode == "product":
            checks.update(self._product_checks(bundle))
        missing = tuple(
            sorted(name for name, passed in checks.items() if not passed)
        )
        return GateResult(
            mode=mode,
            passed=not missing,
            checks=checks,
            missing=missing,
        )

    def _product_checks(self, bundle: Mapping[str, Any]) -> dict[str, bool]:
        protection = self._mapping(bundle.get("branch_protection"))
        required_checks = protection.get("required_checks")
        device = bundle.get("device_qualification")
        device = device if isinstance(device, list) else []
        platform_pass = {
            item.get("platform"): item.get("passed") is True
            for item in device
            if isinstance(item, Mapping)
        }
        reviews = self._mapping(bundle.get("reviews"))
        drills = self._mapping(bundle.get("drills"))
        signing = self._mapping(bundle.get("signing"))
        pilot = self._mapping(bundle.get("pilot"))
        credential_incident = self._mapping(
            bundle.get("credential_incident")
        )
        return {
            "branch_protected": protection.get("protected") is True,
            "branch_reviews": self._integer(
                protection.get("required_approvals")
            )
            >= 1,
            "branch_force_push_disabled": (
                protection.get("force_pushes_allowed") is False
            ),
            "branch_required_checks": (
                isinstance(required_checks, list)
                and self.PRODUCT_REQUIRED_CI_CHECKS.issubset(
                    set(required_checks)
                )
            ),
            "android_device_qualification": (
                platform_pass.get("android") is True
            ),
            "ios_device_qualification": platform_pass.get("ios") is True,
            "security_review": reviews.get("security") == "approved",
            "privacy_review": reviews.get("privacy") == "approved",
            "legal_review": reviews.get("legal") == "approved",
            "kill_switch_drill": drills.get("kill_switch") == "passed",
            "rollback_drill": drills.get("rollback") == "passed",
            "android_signing": self._digest(
                signing.get("android_digest"),
                64,
            ),
            "ios_signing": self._digest(signing.get("ios_digest"), 64),
            "release_provenance": self._digest(
                signing.get("provenance_digest"),
                64,
            ),
            "binary_sbom": self._digest(
                signing.get("binary_sbom_digest"),
                64,
            ),
            "artifact_attestation": self._digest(
                signing.get("artifact_attestation_digest"),
                64,
            ),
            "credential_incident_closed": (
                credential_incident.get("status") == "closed"
            ),
            "credential_revocation_receipt": self._digest(
                credential_incident.get(
                    "provider_revocation_receipt_digest"
                ),
                64,
            ),
            "pilot_cohort": self._integer(pilot.get("cohort_size")) >= 5,
            "pilot_crash_free": self._number(
                pilot.get("crash_free_rate")
            )
            >= 0.99,
            "pilot_duplicate_effects": self._integer(
                pilot.get("duplicate_effects"),
                default=1,
            )
            == 0,
        }

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _nested(
        value: Mapping[str, Any],
        first: str,
        second: str,
    ) -> Any:
        nested = value.get(first)
        return nested.get(second) if isinstance(nested, Mapping) else None

    @staticmethod
    def _integer(value: Any, *, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        return value if isinstance(value, int) else default

    @staticmethod
    def _number(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @staticmethod
    def _digest(value: Any, length: int) -> bool:
        return (
            isinstance(value, str)
            and len(value) == length
            and all(
                character in "0123456789abcdef"
                for character in value.lower()
            )
        )
