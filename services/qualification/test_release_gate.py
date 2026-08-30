from __future__ import annotations

import unittest

from services.qualification.release_gate import (
    EvidenceKey,
    EvidenceTrustStore,
    ReleaseGate,
)


class ReleaseGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000
        self.key_id = "test-authority-key"
        self.issuer = "test-independent-authority"
        self.trust = EvidenceTrustStore(
            {
                self.key_id: EvidenceKey(
                    issuer=self.issuer,
                    allowed_kinds=ReleaseGate.REQUIRED_ATTESTATION_KINDS,
                    secret=b"t" * 32,
                )
            }
        )
        self.gate = ReleaseGate(
            trust_store=self.trust,
            clock=lambda: self.now,
        )

    def source(self) -> dict[str, object]:
        return {
            "repository": "TrillionniumFoundation/hepta-glasses",
            "commit": "a" * 40,
            "tree": "b" * 40,
            "ci_checks": [
                {"name": "flutter", "conclusion": "success"},
                {"name": "repository-contracts", "conclusion": "success"},
                {"name": "secret-and-boundary-scan", "conclusion": "success"},
                {"name": "source-evidence", "conclusion": "success"},
            ],
            "sbom": {"sha256": "c" * 64},
            "provenance": {"sha256": "d" * 64},
            "contracts_version": "2026-08-30-g2",
        }

    def signed(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        return self.trust.sign_development(
            {
                "schema": "hepta.product-attestation.v1",
                "kind": kind,
                "issuer": self.issuer,
                "key_id": self.key_id,
                "repository": "TrillionniumFoundation/hepta-glasses",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "issued_at": self.now - 60,
                "expires_at": self.now + 3_600,
                "payload": payload,
            },
            key_id=self.key_id,
        )

    def product_attestations(self) -> list[dict[str, object]]:
        return [
            self.signed(
                "branch_protection",
                {
                    "protected": True,
                    "required_approvals": 1,
                    "force_pushes_allowed": False,
                    "required_checks": [
                        "flutter",
                        "repository-contracts",
                        "secret-and-boundary-scan",
                        "source-evidence",
                    ],
                },
            ),
            self.signed(
                "device.android",
                {"passed": True, "report_digest": "1" * 64},
            ),
            self.signed(
                "device.ios",
                {"passed": True, "report_digest": "2" * 64},
            ),
            self.signed(
                "review.security",
                {"decision": "approved", "review_digest": "3" * 64},
            ),
            self.signed(
                "review.privacy",
                {"decision": "approved", "review_digest": "4" * 64},
            ),
            self.signed(
                "review.legal",
                {"decision": "approved", "review_digest": "5" * 64},
            ),
            self.signed(
                "drill.kill_switch",
                {"passed": True, "report_digest": "6" * 64},
            ),
            self.signed(
                "drill.rollback",
                {"passed": True, "report_digest": "7" * 64},
            ),
            self.signed(
                "signing.android",
                {"artifact_digest": "8" * 64},
            ),
            self.signed(
                "signing.ios",
                {"artifact_digest": "9" * 64},
            ),
            self.signed(
                "signing.provenance",
                {"provenance_digest": "e" * 64},
            ),
            self.signed(
                "pilot",
                {
                    "cohort_size": 10,
                    "crash_free_rate": 0.995,
                    "duplicate_effects": 0,
                    "report_digest": "f" * 64,
                },
            ),
        ]

    def test_source_mode_passes_without_claiming_product_release(self) -> None:
        result = ReleaseGate().evaluate({"source": self.source()}, mode="source")
        self.assertTrue(result.passed)

    def test_product_mode_rejects_unsigned_caller_authored_fields(self) -> None:
        result = self.gate.evaluate(
            {
                "source": self.source(),
                "branch_protection": {
                    "protected": True,
                    "required_approvals": 99,
                    "force_pushes_allowed": False,
                    "required_checks": list(ReleaseGate.PRODUCT_REQUIRED_CI_CHECKS),
                },
                "reviews": {
                    "security": "approved",
                    "privacy": "approved",
                    "legal": "approved",
                },
            },
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("attestation_set_complete", result.missing)
        self.assertIn("security_review", result.missing)

    def test_complete_signed_product_bundle_passes(self) -> None:
        result = self.gate.evaluate(
            {
                "source": self.source(),
                "product_attestations": self.product_attestations(),
            },
            mode="product",
        )
        self.assertTrue(result.passed, result.missing)

    def test_tampered_signed_payload_fails_closed(self) -> None:
        attestations = self.product_attestations()
        tampered = dict(attestations[0])
        payload = dict(tampered["payload"])  # type: ignore[arg-type]
        payload["required_approvals"] = 0
        tampered["payload"] = payload
        attestations[0] = tampered
        result = self.gate.evaluate(
            {"source": self.source(), "product_attestations": attestations},
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("attestation_set_complete", result.missing)
        self.assertIn("branch_protected", result.missing)

    def test_attestation_bound_to_wrong_head_fails_closed(self) -> None:
        attestations = self.product_attestations()
        wrong = dict(attestations[1])
        wrong["commit"] = "0" * 40
        attestations[1] = self.trust.sign_development(
            wrong,
            key_id=self.key_id,
        )
        result = self.gate.evaluate(
            {"source": self.source(), "product_attestations": attestations},
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("android_device_qualification", result.missing)

    def test_duplicate_attestation_kind_fails_closed(self) -> None:
        attestations = self.product_attestations()
        attestations.append(dict(attestations[0]))
        result = self.gate.evaluate(
            {"source": self.source(), "product_attestations": attestations},
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("attestation_set_unique", result.missing)

    def test_expired_attestation_fails_closed(self) -> None:
        attestations = self.product_attestations()
        expired = dict(attestations[-1])
        expired["issued_at"] = self.now - 7_200
        expired["expires_at"] = self.now - 1
        attestations[-1] = self.trust.sign_development(
            expired,
            key_id=self.key_id,
        )
        result = self.gate.evaluate(
            {"source": self.source(), "product_attestations": attestations},
            mode="product",
        )
        self.assertFalse(result.passed)
        self.assertIn("pilot_cohort", result.missing)


if __name__ == "__main__":
    unittest.main()
