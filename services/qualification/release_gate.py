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
            "repository-contracts",
            "secret-and-boundary-scan",
        }
    )
    PRODUCT_REQUIRED_CI_CHECKS = SOURCE_REQUIRED_CI_CHECKS | frozenset(
        {"source-evidence"}
    )

    def evaluate(self, bundle: Mapping[str, Any], *, mode: str) -> GateResult:
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
        checks: dict[str, bool] = {
            "exact_commit": self._digest(source.get("commit"), 40),
            "exact_tree": self._digest(source.get("tree"), 40),
            "required_ci": all(
                ci_map.get(name) == "success"
                for name in self.SOURCE_REQUIRED_CI_CHECKS
            ),
            "sbom": self._digest(
                self._nested(source, "sbom", "sha256"), 64
            ),
            "provenance": self._digest(
                self._nested(source, "provenance", "sha256"), 64
            ),
            "contracts_version": isinstance(
                source.get("contracts_version"), str
            ) and bool(source.get("contracts_version")),
        }
        if mode == "product":
            checks.update(self._product_checks(bundle))
        missing = tuple(sorted(name for name, passed in checks.items() if not passed))
        return GateResult(
            mode=mode,
            passed=not missing,
            checks=checks,
            missing=missing,
        )

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
        return {
            "branch_protected": protection.get("protected") is True,
            "branch_reviews": int(protection.get("required_approvals", 0)) >= 1,
            "branch_force_push_disabled": protection.get("force_pushes_allowed") is False,
            "branch_required_checks": isinstance(required_checks, list)
            and self.PRODUCT_REQUIRED_CI_CHECKS.issubset(set(required_checks)),
            "android_device_qualification": platform_pass.get("android") is True,
            "ios_device_qualification": platform_pass.get("ios") is True,
            "security_review": reviews.get("security") == "approved",
            "privacy_review": reviews.get("privacy") == "approved",
            "legal_review": reviews.get("legal") == "approved",
            "kill_switch_drill": drills.get("kill_switch") == "passed",
            "rollback_drill": drills.get("rollback") == "passed",
            "android_signing": self._digest(signing.get("android_digest"), 64),
            "ios_signing": self._digest(signing.get("ios_digest"), 64),
            "release_provenance": self._digest(
                signing.get("provenance_digest"), 64
            ),
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
