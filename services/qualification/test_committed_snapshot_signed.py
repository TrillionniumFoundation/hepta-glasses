"""G10 integration against cryptographically signed test fixtures only."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from tools import external_evidence
from tools.external_evidence import EvidenceError
from tools.external_evidence.committed_snapshot import (
    AdmissionSnapshotError, validate_committed_packages,
)
from services.qualification.external_evidence_test_support import (
    COMMIT, FIXED_NOW, TREE, ExternalEvidenceFixture,
)


class SignedCommittedSnapshotTests(ExternalEvidenceFixture):
    def prepare_accepted(self) -> Path:
        bundle = self._complete_bundle(list(self.contract["allowed_gap_ids"]))
        self._accept(bundle)
        return self._write_bundle(bundle)

    @staticmethod
    def _fixture_validator(path: Path, **kwargs):
        # Existing private fixture clock is used only inside unittest's patch.
        # Public repository admission exposes no caller-controlled clock.
        return external_evidence._validate_bundle_at_for_tests(
            path, now=FIXED_NOW, **kwargs,
        )

    def test_all_authority_fixture_passes_real_crypto_from_private_snapshot(self):
        self.prepare_accepted()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=self._fixture_validator):
            result = validate_committed_packages(
                self.root, expected_trust_registry_sha256=self.registry_digest,
            )
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["packages"]), 1)
        self.assertEqual(result["packages"][0]["candidate_commit"], COMMIT)
        self.assertEqual(result["packages"][0]["candidate_tree"], TREE)

    def test_tampered_registry_still_fails_real_crypto_pin(self):
        self.prepare_accepted()
        self.registry_path.write_bytes(self.registry_path.read_bytes() + b"\n")
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=self._fixture_validator):
            with self.assertRaises(EvidenceError):
                validate_committed_packages(
                    self.root, expected_trust_registry_sha256=self.registry_digest,
                )

    def test_valid_signed_copy_does_not_accept_changed_original_envelope(self):
        original = self.prepare_accepted()
        def validate_and_replace(path, **kwargs):
            result = self._fixture_validator(path, **kwargs)
            original.write_bytes(original.read_bytes() + b"\n")
            return result
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=validate_and_replace):
            with self.assertRaisesRegex(AdmissionSnapshotError, "post-validation"):
                validate_committed_packages(
                    self.root, expected_trust_registry_sha256=self.registry_digest,
                )
