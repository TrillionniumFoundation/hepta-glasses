from __future__ import annotations

import unittest

from services.qualification.release_gate import ReleaseGate
from services.qualification.release_gate_test_support import ReleaseGateFixtures


class ReleaseGateProductTest(ReleaseGateFixtures, unittest.TestCase):
    def test_product_mode_rejects_self_attested_status_fields(self) -> None:
        # These fields used to be accepted as release authority.  They are now
        # ignored unless the trusted G10 validator supplies the closure result.
        bundle = {
            "source": self.source(),
            "branch_protection": {
                "protected": True,
                "required_approvals": 99,
                "force_pushes_allowed": False,
                "required_checks": ["source-evidence"],
            },
            "production": {
                "identity": "verified",
                "attestation": "verified",
                "capabilities": "verified",
                "firmware_authority": "verified",
            },
            "reviews": {
                "security": "approved",
                "privacy": "approved",
                "legal": "approved",
                "accessibility": "approved",
            },
            "drills": {
                "kill_switch": "passed",
                "rollback": "passed",
                "credential_rotation": "passed",
            },
        }
        result = ReleaseGate().evaluate(bundle, mode="product")
        self.assertFalse(result.passed)
        self.assertIn("authenticated_external_evidence", result.missing)
        self.assertIn("android_device_qualification", result.missing)
        self.assertIn("production_identity", result.missing)
        self.assertIn("security_review", result.missing)
        self.assertIn("rollback_drill", result.missing)

    def test_product_mode_accepts_complete_authenticated_closure(self) -> None:
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="product",
            external_evidence_result=self.authenticated_external_result(),
        )
        self.assertTrue(result.passed, result.missing)
        self.assertTrue(result.checks["external_registry_pin"])
        self.assertTrue(result.checks["production_realtime_oauth"])
        self.assertTrue(result.checks["pilot_duplicate_effects"])

    def test_product_mode_rejects_external_candidate_drift(self) -> None:
        external = self.authenticated_external_result()
        external["candidate"] = {
            **external["candidate"],
            "commit": "0" * 40,
        }
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="product",
            external_evidence_result=external,
        )
        self.assertFalse(result.passed)
        self.assertIn("external_candidate_identity", result.missing)
        self.assertIn("authenticated_external_evidence", result.missing)

    def test_product_mode_rejects_missing_authority_gap(self) -> None:
        external = self.authenticated_external_result()
        external["submitted_gaps"] = [
            value for value in external["submitted_gaps"] if value != "HG-0013"
        ]
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="product",
            external_evidence_result=external,
        )
        self.assertFalse(result.passed)
        self.assertIn("all_authority_owned_gaps", result.missing)
        self.assertIn("credential_rotation_drill", result.missing)

    def test_product_mode_rejects_unpinned_registry(self) -> None:
        external = self.authenticated_external_result()
        external["trust_registry"] = {
            **external["trust_registry"],
            "external_pin_verified": False,
        }
        result = ReleaseGate().evaluate(
            {"source": self.source()},
            mode="product",
            external_evidence_result=external,
        )
        self.assertFalse(result.passed)
        self.assertIn("external_registry_pin", result.missing)


if __name__ == "__main__":
    unittest.main()
