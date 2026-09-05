"""Fail-closed source and product release evidence gate.

Product mode intentionally accepts authority-owned facts only from the result of
``tools.external_evidence.validate_bundle``.  Human-authored booleans and status
strings in a release JSON document are descriptive data, never release authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .trusted_release_gate import (
    EXTERNAL_POLICY_ID,
    EXTERNAL_POLICY_REVISION,
    REQUIRED_AUTHORITY_GAPS,
    authenticated_product_checks,
)


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
    """Evaluate source artifacts and authenticated product evidence.

    The source bundle is generated inside exact-head CI and is content-verified
    against the artifact directory.  Product facts are accepted only through a
    live result returned by the externally pinned G10 evidence validator.  This
    prevents a repository writer from closing physical, provider, governance,
    review, signing, pilot, or store gates by writing ``"verified"`` into JSON.
    """

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
    REQUIRED_SBOM_ECOSYSTEMS = frozenset(
        {"android/gradle", "dart/pub", "ios/cocoapods", "native/vendored"}
    )
    REQUIRED_AUTHORITY_GAPS = REQUIRED_AUTHORITY_GAPS
    EXTERNAL_POLICY_ID = EXTERNAL_POLICY_ID
    EXTERNAL_POLICY_REVISION = EXTERNAL_POLICY_REVISION


    def __init__(
        self,
        *,
        expected_contracts_version: str = "2026-08-31-g7",
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
        external_evidence_result: Mapping[str, Any] | None = None,
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
            and int(history.get("finding_count", -1)) == 0
            and int(history.get("unscanned_blob_count", -1)) == 0,
            "native_sanitizer": self._digest(sanitizer.get("sha256"), 64)
            and sanitizer.get("passed") is True
            and sanitizer.get("lc3_cross_platform_parity") is True,
            "audit_contract": source.get("audit_contract")
            == "authenticated-checkpoint-v3",
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
            # The trusted helper requires all_authority_owned_gaps_closed,
            # trust_registry.external_pin_verified, and review_set_integrity.
            checks.update(
                authenticated_product_checks(
                    source=source,
                    external_evidence_result=external_evidence_result,
                    required_authority_gaps=self.REQUIRED_AUTHORITY_GAPS,
                    policy_id=self.EXTERNAL_POLICY_ID,
                    policy_revision=self.EXTERNAL_POLICY_REVISION,
                )
            )
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
                and report.get("unscanned_blob_count") == 0
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
