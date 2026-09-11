from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_signature_time_test_support",
    SUPPORT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence


class ExternalEvidenceSignatureTimeTest(support.ExternalEvidenceFixture):
    def test_submission_signature_time_cannot_be_changed_after_signing(self) -> None:
        bundle = self._bundle(["HG-0017"])
        submission = bundle["submissions"][0]
        self.assertEqual(
            submission["attestation"]["signed_at"],
            "2026-09-01T14:00:00Z",
        )
        submission["attestation"]["signed_at"] = "2026-09-01T15:00:00Z"

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "statement digest mismatch",
        ):
            self._validate(bundle)

    def test_submission_signature_time_cannot_be_backdated_after_signing(self) -> None:
        bundle = self._bundle(["HG-0017"])
        submission = bundle["submissions"][0]
        submission["attestation"]["signed_at"] = "2026-09-01T13:30:00Z"

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "statement digest mismatch",
        ):
            self._validate(bundle)


if __name__ == "__main__":
    unittest.main()
