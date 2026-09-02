from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools/validate_external_evidence.py"
SIGNER_PATH = ROOT / "tools/sign_external_evidence.py"
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"

VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_external_evidence_for_signer_test",
    VALIDATOR_PATH,
)
assert VALIDATOR_SPEC is not None and VALIDATOR_SPEC.loader is not None
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(validator)

SIGNER_SPEC = importlib.util.spec_from_file_location(
    "sign_external_evidence_test",
    SIGNER_PATH,
)
assert SIGNER_SPEC is not None and SIGNER_SPEC.loader is not None
signer = importlib.util.module_from_spec(SIGNER_SPEC)
SIGNER_SPEC.loader.exec_module(signer)


class ExternalEvidenceSigningToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private.pem"
        self.public = self.root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(self.private), "-pubout", "-out", str(self.public)],
            check=True,
            capture_output=True,
        )
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.contract_revision = contract["contract_revision"]
        self.registry_digest = "a" * 64

    def _bundle(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "contract_id": "hepta-external-evidence-envelope-v1",
            "trust_registry": {
                "registry_id": "hepta-external-authority-trust-registry-v1",
                "sha256": self.registry_digest,
            },
            "candidate": {
                "repository": "TrillionniumFoundation/hepta-glasses",
                "source_commit": "1" * 40,
                "source_tree": "2" * 40,
                "contracts_revision": "2026-09-01-g8",
                "release_id": None,
                "binary_digests": [],
                "collected_at": "2026-09-02T00:00:00Z",
            },
            "submissions": [
                {
                    "gap_id": "HG-0017",
                    "evidence_level": "ADMIN",
                    "issuer": {
                        "identity": "repository-admin",
                        "organization": "TrillionniumFoundation",
                        "authority_class": "repository_administrator",
                        "key_id": "key:repository-admin:1",
                        "contact": None,
                    },
                    "environment": {"branch": "main"},
                    "subjects": ["main"],
                    "claims": {"seven_checks_required": True},
                    "artifacts": [],
                    "result": "pass",
                    "limitations": [],
                    "notes": None,
                    "attestation": {
                        "signed_at": "1970-01-01T00:00:00Z",
                        "statement_digest": "0" * 64,
                        "signature_uri": "artifact://signatures/placeholder.sig",
                        "signature_sha256": "0" * 64,
                    },
                }
            ],
            "acceptance": {
                "state": "incomplete",
                "reviewed_at": None,
                "reviewers": [
                    {
                        "identity": "governance-reviewer",
                        "organization": "Independent Governance Lab",
                        "authority_class": "repository_governance_reviewer",
                        "key_id": "key:governance-reviewer:1",
                        "decision": "approve",
                        "reviewed_gap_ids": ["HG-0017"],
                        "review_uri": "artifact://reviews/review.json",
                        "review_sha256": "b" * 64,
                        "signed_at": "1970-01-01T00:00:00Z",
                        "statement_digest": "0" * 64,
                        "signature_uri": "artifact://signatures/reviewer-placeholder.sig",
                        "signature_sha256": "0" * 64,
                    }
                ],
                "bundle_digest": None,
                "decision_reference": None,
                "limitations": [],
            },
        }

    def _write_bundle(self, bundle: dict[str, object]) -> Path:
        path = self.root / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        return path

    def test_sign_ed25519_produces_verifiable_detached_signature(self) -> None:
        payload = b"canonical external evidence payload"
        signature = signer.sign_ed25519(self.private, payload)
        validator.verify_ed25519(
            self.public.read_text(encoding="utf-8"),
            payload,
            signature,
            label="signing-tool-test",
        )
        self.assertEqual(len(signature), 64)

    def test_signer_rejects_rsa_private_key_even_when_signature_is_64_bytes(self) -> None:
        private_key = self.root / "rsa-private.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:512",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
        )
        with self.assertRaisesRegex(ValueError, "actual Ed25519 private key"):
            signer.sign_ed25519(private_key, b"not an Ed25519 statement")

    def test_signer_rejects_duplicate_json_members_before_rewrite(self) -> None:
        path = self.root / "duplicate-bundle.json"
        path.write_text(
            '{"contract_id":"first","contract_id":"second"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            validator.EvidenceError,
            "duplicate JSON object member.*contract_id",
        ):
            signer.read_bundle(path)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            '{"contract_id":"first","contract_id":"second"}',
        )

    def test_write_signature_refuses_overwrite(self) -> None:
        uri = "artifact://signatures/test.sig"
        path, digest = signer.write_signature(
            custody_root=self.root,
            signature_uri=uri,
            signature=b"first",
        )
        self.assertEqual(digest, hashlib.sha256(b"first").hexdigest())
        self.assertEqual(path.read_bytes(), b"first")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            signer.write_signature(
                custody_root=self.root,
                signature_uri=uri,
                signature=b"second",
            )

    def test_sign_submission_uses_current_attestation_contract(self) -> None:
        path = self._write_bundle(self._bundle())
        result = signer.sign_submission(
            Namespace(
                bundle=path,
                custody_root=self.root,
                index=0,
                private_key=self.private,
                signature_uri="artifact://signatures/submission.sig",
                signed_at="2026-09-02T01:00:00Z",
            )
        )
        bundle = json.loads(path.read_text(encoding="utf-8"))
        submission = bundle["submissions"][0]
        attestation = submission["attestation"]
        self.assertEqual(
            set(attestation),
            {"signed_at", "statement_digest", "signature_uri", "signature_sha256"},
        )
        payload = validator.canonical_submission_statement(
            bundle,
            submission,
            contract_revision=self.contract_revision,
        )
        self.assertEqual(attestation["statement_digest"], hashlib.sha256(payload).hexdigest())
        signature = (self.root / "signatures/submission.sig").read_bytes()
        validator.verify_ed25519(
            self.public.read_text(encoding="utf-8"),
            payload,
            signature,
            label="submission-signing-tool-test",
        )
        self.assertEqual(result["statement_digest"], attestation["statement_digest"])

    def test_sign_reviewer_uses_current_review_contract(self) -> None:
        path = self._write_bundle(self._bundle())
        result = signer.sign_reviewer(
            Namespace(
                bundle=path,
                custody_root=self.root,
                index=0,
                private_key=self.private,
                signature_uri="artifact://signatures/reviewer.sig",
                trust_registry_sha256=self.registry_digest,
                signed_at="2026-09-02T01:05:00Z",
            )
        )
        bundle = json.loads(path.read_text(encoding="utf-8"))
        reviewer = bundle["acceptance"]["reviewers"][0]
        payload = validator.canonical_review_statement(
            bundle,
            reviewer,
            contract_revision=self.contract_revision,
        )
        self.assertEqual(reviewer["statement_digest"], hashlib.sha256(payload).hexdigest())
        signature = (self.root / "signatures/reviewer.sig").read_bytes()
        validator.verify_ed25519(
            self.public.read_text(encoding="utf-8"),
            payload,
            signature,
            label="reviewer-signing-tool-test",
        )
        self.assertEqual(result["statement_digest"], reviewer["statement_digest"])

    def test_reviewer_signing_rejects_wrong_out_of_band_registry_pin(self) -> None:
        path = self._write_bundle(self._bundle())
        with self.assertRaisesRegex(ValueError, "differs from bundle binding"):
            signer.sign_reviewer(
                Namespace(
                    bundle=path,
                    custody_root=self.root,
                    index=0,
                    private_key=self.private,
                    signature_uri="artifact://signatures/reviewer.sig",
                    trust_registry_sha256="c" * 64,
                    signed_at="2026-09-02T01:05:00Z",
                )
            )

    def test_finalize_writes_self_consistent_bundle_digest(self) -> None:
        path = self._write_bundle(self._bundle())
        result = signer.finalize(Namespace(bundle=path))
        finalized = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["bundle_digest"], finalized["acceptance"]["bundle_digest"])
        self.assertEqual(
            finalized["acceptance"]["bundle_digest"],
            validator.canonical_bundle_digest(finalized),
        )


if __name__ == "__main__":
    unittest.main()
