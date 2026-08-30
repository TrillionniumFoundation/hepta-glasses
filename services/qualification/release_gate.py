"""Fail-closed source and product release evidence gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
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
        {"android/gradle", "dart/pub", "ios/cocoapods", "native/vendored"}
    )

    def __init__(
        self,
        *,
        expected_contracts_version: str = "2026-08-31-g5",
    ) -> None:
        if not expected_contracts_version:
            raise ReleaseGateError("contracts_version_invalid")
        self.expected_contracts_version = expected_contracts_version

    def evaluate(
        self,
        bundle: Mapping[str, Any],
        *,
        mode: str,
        evidence_dir: Path | None = None,
    ) -> GateResult:
        if mode not in {"source", "product"}:
            raise ReleaseGateError("release_mode_invalid")
        source = bundle.get("source")
        if not isinstance(source, Mapping):
            raise ReleaseGateError("release_source_evidence_missing")
        ci_checks = source.get("ci_checks")
        ci_map = {
            item.get("name"): item.get("conclusion")
            for item in ci_checks
            if isinstance(item, Mapping)
        } if isinstance(ci_checks, list) else {}
        history = source.get("history_scan")
        history = history if isinstance(history, Mapping) else {}
        sanitizer = source.get("native_sanitizer")
        sanitizer = sanitizer if isinstance(sanitizer, Mapping) else {}
        ecosystems = source.get("sbom_ecosystems")
        checks: dict[str, bool] = {
            "exact_commit": self._digest(source.get("commit"), 40),
            "exact_tree": self._digest(source.get("tree"), 40),
            "required_ci": all(
                ci_map.get(name) == "success"
                for name in self.SOURCE_REQUIRED_CI_CHECKS
            ),
            "sbom": self._digest(self._nested(source, "sbom", "sha256"), 64),
            "sbom_ecosystems": isinstance(ecosystems, list)
            and self.REQUIRED_SBOM_ECOSYSTEMS.issubset(set(ecosystems)),
            "history_scan": self._digest(history.get("sha256"), 64)
            and history.get("scope") == "all-fetched-refs-and-deduplicated-blobs"
            and int(history.get("commit_count", 0)) > 0
            and int(history.get("scanned_blob_count", 0)) > 0
            and int(history.get("finding_count", -1)) == 0,
            "native_sanitizer": self._digest(sanitizer.get("sha256"), 64)
            and sanitizer.get("passed") is True
            and sanitizer.get("lc3_cross_platform_parity") is True,
            "audit_contract": source.get("audit_contract")
            == "file-lock-checkpoint-v1",
            "provenance": self._digest(
                self._nested(source, "provenance", "sha256"), 64
            ),
            "provenance_type": source.get("provenance_type")
            == "unsigned-source-provenance-v1",
            "contracts_version": (
                source.get("contracts_version")
                == self.expected_contracts_version
            ),
        }
        if evidence_dir is not None:
            checks.update(self._artifact_checks(source, evidence_dir))
        if mode == "product":
            checks.update(self._product_checks(bundle))
        missing = tuple(sorted(name for name, passed in checks.items() if not passed))
        return GateResult(
            mode=mode,
            passed=not missing,
            checks=checks,
            missing=missing,
        )

    def _artifact_checks(
        self, source: Mapping[str, Any], evidence_dir: Path
    ) -> dict[str, bool]:
        expected = {
            "artifact_sbom_digest": (
                "source-sbom.spdx.json",
                self._nested(source, "sbom", "sha256"),
            ),
            "artifact_provenance_digest": (
                "source-provenance.json",
                self._nested(source, "provenance", "sha256"),
            ),
            "artifact_history_digest": (
                "source-history-scan.json",
                self._nested(source, "history_scan", "sha256"),
            ),
            "artifact_native_digest": (
                "source-native-sanitizer.json",
                self._nested(source, "native_sanitizer", "sha256"),
            ),
        }
        checks: dict[str, bool] = {}
        for name, (filename, digest) in expected.items():
            path = evidence_dir / filename
            checks[name] = (
                path.is_file()
                and isinstance(digest, str)
                and self._sha256_file(path) == digest
            )
        if checks.get("artifact_history_digest"):
            report = json.loads(
                (evidence_dir / "source-history-scan.json").read_text(
                    encoding="utf-8"
                )
            )
            checks["artifact_history_content"] = (
                report.get("finding_count") == 0
                and report.get("head") == source.get("commit")
                and report.get("scope")
                == "all-fetched-refs-and-deduplicated-blobs"
            )
        else:
            checks["artifact_history_content"] = False
        if checks.get("artifact_native_digest"):
            report = json.loads(
                (evidence_dir / "source-native-sanitizer.json").read_text(
                    encoding="utf-8"
                )
            )
            checks["artifact_native_content"] = (
                report.get("passed") is True
                and report.get("lc3_cross_platform_parity") is True
            )
        else:
            checks["artifact_native_content"] = False
        return checks

    def _product_checks(self, bundle: Mapping[str, Any]) -> dict[str, bool]:
        protection = bundle.get("branch_protection")
        protection = protection if isinstance(protection, Mapping) else {}
        required_checks = protection.get("required_checks")
        device = bundle.get("device_qualification")
        device = device if isinstance(device, list) else []
        platform_pass = {
            item.get("platform"): item.get("passed") is True
            for item in device
            if isinstance(item, Mapping)
        }
        reviews = bundle.get("reviews")
        reviews = reviews if isinstance(reviews, Mapping) else {}
        drills = bundle.get("drills")
        drills = drills if isinstance(drills, Mapping) else {}
        signing = bundle.get("signing")
        signing = signing if isinstance(signing, Mapping) else {}
        pilot = bundle.get("pilot")
        pilot = pilot if isinstance(pilot, Mapping) else {}
        production = bundle.get("production")
        production = production if isinstance(production, Mapping) else {}
        return {
            "branch_protected": protection.get("protected") is True,
            "branch_reviews": int(protection.get("required_approvals", 0)) >= 1,
            "branch_force_push_disabled": protection.get("force_pushes_allowed") is False,
            "branch_required_checks": isinstance(required_checks, list)
            and self.PRODUCT_REQUIRED_CI_CHECKS.issubset(set(required_checks)),
            "android_device_qualification": platform_pass.get("android") is True,
            "ios_device_qualification": platform_pass.get("ios") is True,
            "production_identity": production.get("identity") == "verified",
            "production_attestation": production.get("attestation") == "verified",
            "production_capabilities": production.get("capabilities") == "verified",
            "vendor_firmware_authority": production.get("firmware_authority") == "verified",
            "security_review": reviews.get("security") == "approved",
            "privacy_review": reviews.get("privacy") == "approved",
            "legal_review": reviews.get("legal") == "approved",
            "accessibility_review": reviews.get("accessibility") == "approved",
            "kill_switch_drill": drills.get("kill_switch") == "passed",
            "rollback_drill": drills.get("rollback") == "passed",
            "credential_rotation_drill": drills.get("credential_rotation") == "passed",
            "android_signing": self._digest(signing.get("android_digest"), 64),
            "ios_signing": self._digest(signing.get("ios_digest"), 64),
            "release_provenance": self._digest(
                signing.get("provenance_digest"), 64
            ),
            "release_attestation_verified": signing.get("attestation_verified") is True,
            "pilot_cohort": int(pilot.get("cohort_size", 0)) >= 5,
            "pilot_crash_free": float(pilot.get("crash_free_rate", 0)) >= 0.99,
            "pilot_duplicate_effects": int(pilot.get("duplicate_effects", 1)) == 0,
        }

    @staticmethod
    def _nested(value: Mapping[str, Any], first: str, second: str) -> Any:
        nested = value.get(first)
        return nested.get(second) if isinstance(nested, Mapping) else None

    @staticmethod
    def _digest(value: Any, length: int) -> bool:
        return isinstance(value, str) and len(value) == length and all(
            character in "0123456789abcdef" for character in value.lower()
        )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
