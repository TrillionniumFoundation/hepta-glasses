from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location("external_evidence_test_support", SUPPORT_PATH)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence
ROOT = support.ROOT
FIXED_NOW = support.FIXED_NOW
COMMIT = support.COMMIT
TREE = support.TREE


class ExternalEvidenceValidationTest(support.ExternalEvidenceFixture):
    def test_partial_valid_signed_submission_is_not_closure(self) -> None:
        bundle = self._bundle(["HG-0017"])
        result = self._validate(bundle)
        self.assertTrue(result["ok"])
        self.assertFalse(result["eligible_for_review"])
        self.assertFalse(result["all_authority_owned_gaps_closed"])
        self.assertIn("HG-0010", result["missing_gaps"])
        self.assertIn(
            "github_api_observer",
            result["missing_issuer_authority_classes"]["HG-0017"],
        )

    def test_complete_authenticated_accepted_bundle_closes_rows(self) -> None:
        gap_ids = list(self.contract["allowed_gap_ids"])
        bundle = self._complete_bundle(gap_ids)
        self._accept(bundle)
        result = self._validate(bundle, complete=True, accepted=True)
        expected_artifacts = sum(
            len(self.contract["authority_classes"][gap_id])
            for gap_id in gap_ids
        )
        self.assertTrue(result["eligible_for_review"])
        self.assertTrue(result["all_authority_owned_gaps_closed"])
        self.assertEqual(result["missing_gaps"], [])
        self.assertEqual(result["missing_issuer_authority_classes"], {})
        self.assertEqual(result["artifact_count"], expected_artifacts)
        self.assertTrue(result["trust_registry"]["external_pin_verified"])
        self.assertTrue(result["review_set_integrity"]["verified"])

    def test_physical_gap_rejects_synthetic_evidence(self) -> None:
        bundle = self._bundle(["HG-0010"])
        bundle["submissions"][0]["artifacts"] = [
            self._artifact("HG-0010-synthetic", synthetic=True)
        ]
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "requires physical evidence",
        ):
            self._validate(bundle)

    def test_wrong_authority_class_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0013"])
        bundle["submissions"][0]["issuer"][
            "authority_class"
        ] = "repository_administrator"
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "cannot attest HG-0013",
        ):
            self._validate(bundle)

    def test_digest_mismatch_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0021"])
        bundle["submissions"][0]["artifacts"][0]["sha256"] = "4" * 64
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "digest mismatch",
        ):
            self._validate(bundle)

    def test_candidate_drift_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        bundle["candidate"]["source_commit"] = "5" * 40
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "!= expected",
        ):
            self._validate(bundle)

    def test_invented_key_id_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        bundle["submissions"][0]["issuer"]["key_id"] = "invented-key"
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "unknown trust-registry key",
        ):
            self._validate(bundle)

    def test_random_signature_bytes_with_matching_hash_are_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        attestation = bundle["submissions"][0]["attestation"]
        signature_path = external_evidence.safe_artifact_path(
            self.artifact_root,
            attestation["signature_uri"],
            label="fixture",
        )
        signature_path.write_bytes(b"x" * 64)
        attestation["signature_sha256"] = hashlib.sha256(b"x" * 64).hexdigest()
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "cryptographic verification failed",
        ):
            self._validate(bundle)

    def test_optional_artifact_signature_is_cryptographically_verified(self) -> None:
        bundle = self._bundle(["HG-0017"])
        artifact = bundle["submissions"][0]["artifacts"][0]
        artifact_path = external_evidence.safe_artifact_path(
            self.artifact_root,
            artifact["uri"],
            label="fixture-artifact",
        )
        signature = self._sign(
            "issuer",
            artifact_path.read_bytes(),
            Path("signatures") / "HG-0017.native.sig",
        )
        artifact.update(signature)
        submission = bundle["submissions"][0]
        statement = external_evidence.canonical_submission_statement(
            bundle,
            submission,
            contract_revision=self.contract["contract_revision"],
        )
        issuer_signature = self._sign(
            "issuer",
            statement,
            Path("signatures") / "HG-0017.issuer.resigned.sig",
        )
        submission["attestation"] = {
            "signed_at": "2026-09-01T14:00:00Z",
            "statement_digest": hashlib.sha256(statement).hexdigest(),
            **issuer_signature,
        }
        result = self._validate(bundle)
        self.assertTrue(
            result["submissions"][0]["artifacts"][0][
                "native_signature_verified"
            ]
        )


if __name__ == "__main__":
    unittest.main()
