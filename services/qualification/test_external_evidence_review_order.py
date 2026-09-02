from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_review_order_test_support",
    SUPPORT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence


class ExternalEvidenceReviewOrderTest(support.ExternalEvidenceFixture):
    def test_valid_review_signature_cannot_predate_issuer_attestations(self) -> None:
        bundle = self._bundle(list(self.contract["allowed_gap_ids"]))
        self._accept(bundle)
        reviewer = bundle["acceptance"]["reviewers"][0]
        reviewer["signed_at"] = "2026-09-01T13:30:00Z"
        reviewer["statement_digest"] = "0" * 64
        reviewer["signature_uri"] = "artifact://placeholder"
        reviewer["signature_sha256"] = "0" * 64
        statement = external_evidence.canonical_review_statement(
            bundle,
            reviewer,
            contract_revision=self.contract["contract_revision"],
        )
        signature = self._sign(
            "release-reviewer",
            statement,
            Path("signatures") / "release-reviewer.early.review.sig",
        )
        reviewer["statement_digest"] = hashlib.sha256(statement).hexdigest()
        reviewer.update(signature)
        bundle["acceptance"]["bundle_digest"] = None
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "predates submitted evidence attestations",
        ):
            self._validate(bundle, complete=True, accepted=True)


if __name__ == "__main__":
    unittest.main()
