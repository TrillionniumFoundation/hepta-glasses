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
                {"name": "repository-contracts", "conclusion": "success"},
                {"name": "secret-and-boundary-scan", "conclusion": "success"},
                {"name": "source-evidence", "conclusion": "success"},
            ],
            "sbom": {"sha256": "c" * 64},
            "provenance": {"sha256": "d" * 64},
            "contracts_version": "2026-08-30-g2",
        }

    def test_source_mode_passes_without_claiming_product_release(self) -> None:
        result = ReleaseGate().evaluate({"source": self.source()}, mode="source")
        self.assertTrue(result.passed)

    def test_source_mode_fails_when_native_platform_does_not_build(self) -> None:
        source = self.source()
        source["ci_checks"] = [
            item
            for item in source["ci_checks"]
            if isinstance(item, dict) and item["name"] != "ios-native"
        ]
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("required_ci", result.missing)

    def test_product_mode_requires_every_external_evidence_class(self) -> None:
        result = ReleaseGate().evaluate({"source": self.source()}, mode="product")
        self.assertFalse(result.passed)
        self.assertIn("android_device_qualification", result.missing)
        self.assertIn("security_review", result.missing)
        self.assertIn("rollback_drill", result.missing)

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
            "drills": {"kill_switch": "passed", "rollback": "passed"},
            "signing": {
                "android_digest": "e" * 64,
                "ios_digest": "f" * 64,
                "provenance_digest": "1" * 64,
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
