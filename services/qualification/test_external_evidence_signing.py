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

    def test_finalize_writes_self_consistent_bundle_digest(self) -> None:
        bundle = {
            "schema_version": 1,
            "contract_id": "hepta-external-evidence-envelope-v1",
            "candidate": {"source_commit": "1" * 40},
            "submissions": [],
            "acceptance": {
                "state": "incomplete",
                "reviewed_at": None,
                "reviewers": [],
                "bundle_digest": None,
                "decision_reference": None,
                "limitations": [],
            },
        }
        path = self.root / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        result = signer.finalize(Namespace(bundle=path))
        finalized = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["bundle_digest"], finalized["acceptance"]["bundle_digest"])
        self.assertEqual(
            finalized["acceptance"]["bundle_digest"],
            validator.canonical_bundle_digest(finalized),
        )


if __name__ == "__main__":
    unittest.main()
