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


class ExternalEvidenceAdversarialTest(support.ExternalEvidenceFixture):
    def test_random_optional_artifact_signature_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        artifact = bundle["submissions"][0]["artifacts"][0]
        relative = Path("signatures") / "HG-0017.native-random.sig"
        signature_path = self.artifact_root / relative
        signature_path.parent.mkdir(parents=True, exist_ok=True)
        signature_path.write_bytes(b"z" * 64)
        artifact["signature_uri"] = f"artifact://{relative.as_posix()}"
        artifact["signature_sha256"] = hashlib.sha256(b"z" * 64).hexdigest()
        with self.assertRaisesRegex(
            external_evidence.EvidenceError, "cryptographic verification failed"
        ):
            self._validate(bundle)

    def test_repository_substituted_public_key_fails_external_pin(self) -> None:
        bundle = self._bundle(["HG-0017"])
        replacement_public, replacement_digest = self._generate_key("replacement")
        issuer_record = self.registry_document["keys"][0]
        target = self.key_root / "issuer.public.pem"
        target.write_bytes(replacement_public.read_bytes())
        issuer_record["public_key_sha256"] = replacement_digest
        new_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = new_digest
        with self.assertRaisesRegex(external_evidence.EvidenceError, "external pin mismatch"):
            self._validate(bundle, registry_digest=self.registry_digest)

    def test_revoked_key_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        self.registry_document["keys"][0]["revoked_at"] = "2026-09-02T08:00:00Z"
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        with self.assertRaisesRegex(external_evidence.EvidenceError, "is revoked"):
            self._validate(bundle)

    def test_expired_key_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        self.registry_document["keys"][0]["valid_until"] = "2026-09-02T11:00:00Z"
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        with self.assertRaisesRegex(external_evidence.EvidenceError, "is expired"):
            self._validate(bundle)

    def test_cross_gap_authority_reuse_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0013"])
        self.registry_document["keys"][0]["allowed_gap_ids"] = ["HG-0010"]
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        with self.assertRaisesRegex(external_evidence.EvidenceError, "not authorized for gaps"):
            self._validate(bundle)

    def test_issuer_as_reviewer_alias_is_rejected(self) -> None:
        bundle = self._bundle(list(self.contract["allowed_gap_ids"]))
        self._accept(bundle)
        reviewer = bundle["acceptance"]["reviewers"][0]
        reviewer["identity"] = "fixture-evidence-authority"
        reviewer["organization"] = "fixture-evidence-org"
        reviewer["key_id"] = "issuer-key"
        with self.assertRaisesRegex(external_evidence.EvidenceError, "issuer alias"):
            self._validate(bundle, complete=True, accepted=True)

    def test_fabricated_accepted_bundle_without_external_pin_is_rejected(self) -> None:
        bundle = self._bundle(list(self.contract["allowed_gap_ids"]))
        self._accept(bundle)
        with self.assertRaisesRegex(external_evidence.EvidenceError, "out-of-band"):
            external_evidence.validate_bundle(
                self._write_bundle(bundle),
                artifact_root=self.artifact_root,
                expected_commit=COMMIT,
                expected_tree=TREE,
                require_complete=True,
                require_accepted=True,
                trust_registry_path=self.registry_path,
                expected_trust_registry_sha256=None,
                now=FIXED_NOW,
            )

    def test_committed_template_is_deliberately_non_attesting(self) -> None:
        template = json.loads(
            (
                ROOT / "evidence/templates/external-evidence-bundle.template.json"
            ).read_text(encoding="utf-8")
        )
        with self.assertRaises(external_evidence.EvidenceError):
            external_evidence.validate_bundle(
                self._write_bundle(template, "template.json"),
                artifact_root=self.artifact_root,
                expected_commit=None,
                expected_tree=None,
                require_complete=False,
                require_accepted=False,
                trust_registry_path=None,
                expected_trust_registry_sha256=None,
                now=FIXED_NOW,
            )


if __name__ == "__main__":
    unittest.main()
