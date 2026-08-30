from __future__ import annotations

import unittest

from services.qualification.release_gate import ReleaseGate


class ReleaseGateTest(unittest.TestCase):
    def source(self) -> dict[str, object]:
        return {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "ci_checks": [
                {"name": "android-native", "conclusion": "success"},
                {"name": "flutter", "conclusion": "success"},
                {"name": "ios-native", "conclusion": "success"},
                {"name": "native-sanitizers", "conclusion": "success"},
                {"name": "repository-contracts", "conclusion": "success"},
                {
                    "name": "secret-and-boundary-scan",
                    "conclusion": "success",
                },
                {"name": "source-evidence", "conclusion": "success"},
            ],
            "sbom": {
                "sha256": "c" * 64,
                "file_count": 10,
                "package_count": 10,
                "relationship_count": 20,
                "vendored_component_count": 2,
                "ecosystem_counts": {
                    "application": 1,
                    "build-tool": 2,
                    "cocoapods": 1,
                    "gradle-plugin": 1,
                    "maven": 1,
                    "pub": 2,
                    "vendored": 2,
                },
            },
            "provenance": {"sha256": "d" * 64},
            "credential_history": {
                "sha256": "e" * 64,
                "current_tree_findings": 0,
                "historical_findings": 4,
                "historical_unique_fingerprints": 1,
            },
            "third_party_manifest": {"sha256": "f" * 64},
            "contracts_version": "2026-08-30-g5",
        }

    def test_source_mode_passes_without_claiming_product_release(self) -> None:
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="source",
        )
        self.assertTrue(result.passed, result.missing)

    def test_source_mode_rejects_stale_contracts_version(self) -> None:
        source = self.source()
        source["contracts_version"] = "2026-08-30-g4"
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("contracts_version", result.missing)

    def test_source_mode_fails_when_native_sanitizers_do_not_run(self) -> None:
        source = self.source()
        source["ci_checks"] = [
            item
            for item in source["ci_checks"]
            if isinstance(item, dict)
            and item["name"] != "native-sanitizers"
        ]
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("required_ci", result.missing)

    def test_source_mode_rejects_incomplete_sbom_inventory(self) -> None:
        source = self.source()
        sbom = dict(source["sbom"])
        sbom["ecosystem_counts"] = {"pub": 2}
        source["sbom"] = sbom
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("sbom_inventory", result.missing)

    def test_source_mode_rejects_current_tree_credentials(self) -> None:
        source = self.source()
        history = dict(source["credential_history"])
        history["current_tree_findings"] = 1
        source["credential_history"] = history
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("credential_history", result.missing)

    def test_product_mode_requires_every_external_evidence_class(self) -> None:
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("android_device_qualification", result.missing)
        self.assertIn("security_review", result.missing)
        self.assertIn("rollback_drill", result.missing)
        self.assertIn("credential_incident_closed", result.missing)
        self.assertIn("binary_sbom", result.missing)

    def test_complete_product_bundle_passes(self) -> None:
        bundle = {
            "source": self.source(),
            "branch_protection": {
                "protected": True,
                "required_approvals": 1,
                "force_pushes_allowed": False,
                "required_checks": [
                    "android-native",
                    "flutter",
                    "ios-native",
                    "native-sanitizers",
                    "repository-contracts",
                    "secret-and-boundary-scan",
                    "source-evidence",
                ],
            },
            "device_qualification": [
                {"platform": "android", "passed": True},
                {"platform": "ios", "passed": True},
            ],
            "reviews": {
                "security": "approved",
                "privacy": "approved",
                "legal": "approved",
            },
            "drills": {
                "kill_switch": "passed",
                "rollback": "passed",
            },
            "signing": {
                "android_digest": "1" * 64,
                "ios_digest": "2" * 64,
                "provenance_digest": "3" * 64,
                "binary_sbom_digest": "4" * 64,
                "artifact_attestation_digest": "5" * 64,
            },
            "credential_incident": {
                "status": "closed",
                "provider_revocation_receipt_digest": "6" * 64,
            },
            "pilot": {
                "cohort_size": 10,
                "crash_free_rate": 0.995,
                "duplicate_effects": 0,
            },
        }
        result = ReleaseGate().evaluate(bundle, mode="product")
        self.assertTrue(result.passed, result.missing)


if __name__ == "__main__":
    unittest.main()
