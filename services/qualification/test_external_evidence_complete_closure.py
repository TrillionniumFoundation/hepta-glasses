from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_complete_test_support",
    SUPPORT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence


class ExternalEvidenceCompleteClosureTest(support.ExternalEvidenceFixture):
    def _all_gap_bundle(self) -> dict[str, object]:
        return self._complete_bundle(
            list(self.contract["allowed_gap_ids"])
        )

    def _resign_all_submissions(self, bundle: dict[str, object]) -> None:
        for index, submission in enumerate(bundle["submissions"]):
            issuer = submission["issuer"]
            key_id = issuer["key_id"]
            key_name = (
                "issuer"
                if key_id == "issuer-key"
                else str(key_id).removesuffix("-key")
            )
            submission["attestation"] = {
                "signed_at": "2026-09-01T14:00:00Z",
                "statement_digest": "0" * 64,
                "signature_uri": "artifact://placeholder",
                "signature_sha256": "0" * 64,
            }
            statement = external_evidence.canonical_submission_statement(
                bundle,
                submission,
                contract_revision=self.contract["contract_revision"],
            )
            signature = self._sign(
                key_name,
                statement,
                Path("signatures") / f"resigned-{index}.sig",
            )
            submission["attestation"] = {
                "signed_at": "2026-09-01T14:00:00Z",
                "statement_digest": hashlib.sha256(statement).hexdigest(),
                **signature,
            }

    def test_complete_bundle_requires_every_named_authority_class(self) -> None:
        bundle = self._all_gap_bundle()
        bundle["submissions"] = [
            submission
            for submission in bundle["submissions"]
            if not (
                submission["gap_id"] == "HG-0017"
                and submission["issuer"]["authority_class"]
                == "github_api_observer"
            )
        ]
        self._accept(bundle)
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "lacks required issuer authority classes.*HG-0017",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_one_key_cannot_fill_two_authority_seats(self) -> None:
        bundle = self._all_gap_bundle()
        admin = next(
            submission
            for submission in bundle["submissions"]
            if submission["gap_id"] == "HG-0017"
            and submission["issuer"]["authority_class"]
            == "repository_administrator"
        )
        observer = next(
            submission
            for submission in bundle["submissions"]
            if submission["gap_id"] == "HG-0017"
            and submission["issuer"]["authority_class"]
            == "github_api_observer"
        )
        admin_key_id = admin["issuer"]["key_id"]
        admin_record = next(
            record
            for record in self.registry_document["keys"]
            if record["key_id"] == admin_key_id
        )
        admin_record["authority_classes"] = [
            "repository_administrator",
            "github_api_observer",
        ]
        observer["issuer"] = {
            **admin["issuer"],
            "authority_class": "github_api_observer",
        }
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        self._resign_all_submissions(bundle)
        self._accept(bundle)
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "reuses issuer key",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_removing_a_signed_dissenting_review_is_detected(self) -> None:
        bundle = self._all_gap_bundle()
        self._accept(bundle, include_dissent=True)
        bundle["acceptance"]["reviewers"] = [
            reviewer
            for reviewer in bundle["acceptance"]["reviewers"]
            if reviewer["key_id"] != "dissent-reviewer-key"
        ]
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "does not bind the final reviewer set",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_reordering_final_reviews_is_detected(self) -> None:
        bundle = self._all_gap_bundle()
        self._accept(bundle)
        reviewers = bundle["acceptance"]["reviewers"]
        reviewers[0], reviewers[1] = reviewers[1], reviewers[0]
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "does not bind the final reviewer set",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_acceptance_limitation_mutation_is_detected(self) -> None:
        bundle = self._all_gap_bundle()
        self._accept(bundle)
        bundle["acceptance"]["limitations"].append(
            "A curator-added limitation after final review."
        )
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "does not bind the final acceptance context",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_complete_closure_reports_review_manifest_digests(self) -> None:
        bundle = self._all_gap_bundle()
        self._accept(bundle)
        result = self._validate(bundle, complete=True, accepted=True)
        integrity = result["review_set_integrity"]
        self.assertTrue(integrity["verified"])
        self.assertEqual(len(integrity["review_set_digest"]), 64)
        self.assertEqual(len(integrity["acceptance_context_digest"]), 64)
        self.assertEqual(
            len(integrity["reviewer_key_ids"]),
            len(bundle["acceptance"]["reviewers"]),
        )


if __name__ == "__main__":
    unittest.main()
