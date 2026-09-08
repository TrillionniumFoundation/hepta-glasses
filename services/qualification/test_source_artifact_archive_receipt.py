from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.verify_source_archive_receipt import (
    ArchiveReceiptError,
    canonical_json,
    load_strict_json,
    verify_archive_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
HEAD = "a" * 40
TREE = "b" * 40
KEY_ID = "archive-security-2026-01"


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
class SourceArtifactArchiveReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-archive-test-")
        self.directory = Path(self.temp.name)
        self.private_key = self.directory / "private.pem"
        self.public_key = self.directory / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(self.private_key)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(self.private_key), "-pubout", "-out", str(self.public_key)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.artifact = self.directory / "artifact.zip"
        self.artifact.write_bytes(b"exact source evidence bytes\n")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.registry = self.directory / "external-trust-registry.json"
        self.registry.write_text(json.dumps({
            "schema_version": 1,
            "keys": [{
                "key_id": KEY_ID,
                "algorithm": "ed25519",
                "public_key_pem": self.public_key.read_text(encoding="utf-8"),
                "status": "active",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2028-01-01T00:00:00Z",
            }],
        }, sort_keys=True), encoding="utf-8")
        self.receipt = self.directory / "receipt.json"
        self._write_signed_receipt()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _unsigned(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "repository": "TrillionniumFoundation/hepta-glasses",
            "head_commit": HEAD,
            "source_tree": TREE,
            "artifact_name": f"hepta-source-evidence-{HEAD}",
            "artifact_sha256": self.digest,
            "artifact_size_bytes": self.artifact.stat().st_size,
            "archive_object": f"sha256:{self.digest}",
            "archived_at": "2026-09-09T00:00:00Z",
            "retention_until": "2033-09-09T00:00:00Z",
            "custodian": "independent archive security",
            "key_id": KEY_ID,
        }

    def _write_signed_receipt(self, mutate=None) -> None:
        unsigned = self._unsigned()
        if mutate is not None:
            mutate(unsigned)
        payload = self.directory / "payload.bin"
        signature = self.directory / "signature.bin"
        payload.write_bytes(canonical_json(unsigned))
        subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
             "-rawin", "-in", str(payload), "-out", str(signature)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        receipt = dict(unsigned)
        receipt["signature"] = base64.b64encode(signature.read_bytes()).decode("ascii")
        self.receipt.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    def _verify(self):
        return verify_archive_receipt(
            receipt_path=self.receipt, artifact_path=self.artifact,
            trust_registry_path=self.registry, repository_root=ROOT,
            expected_head=HEAD, expected_tree=TREE,
        )

    def test_valid_external_content_addressed_receipt_passes(self) -> None:
        result = self._verify()
        self.assertEqual(result.head_commit, HEAD)
        self.assertEqual(result.source_tree, TREE)
        self.assertEqual(result.artifact_sha256, self.digest)
        self.assertEqual(result.archive_object, f"sha256:{self.digest}")

    def test_tampered_artifact_fails_closed(self) -> None:
        self.artifact.write_bytes(self.artifact.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ArchiveReceiptError, "SHA-256"):
            self._verify()

    def test_wrong_expected_object_fails_closed(self) -> None:
        with self.assertRaisesRegex(ArchiveReceiptError, "expected head"):
            verify_archive_receipt(
                receipt_path=self.receipt, artifact_path=self.artifact,
                trust_registry_path=self.registry, repository_root=ROOT,
                expected_head="c" * 40, expected_tree=TREE,
            )

    def test_content_address_must_equal_digest(self) -> None:
        self._write_signed_receipt(lambda r: r.__setitem__("archive_object", "sha256:" + "0" * 64))
        with self.assertRaisesRegex(ArchiveReceiptError, "content-addressed"):
            self._verify()

    def test_bool_is_not_artifact_size(self) -> None:
        self._write_signed_receipt(lambda r: r.__setitem__("artifact_size_bytes", True))
        with self.assertRaisesRegex(ArchiveReceiptError, "integer"):
            self._verify()

    def test_inactive_key_fails_closed(self) -> None:
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["keys"][0]["status"] = "revoked"
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "not active"):
            self._verify()

    def test_modified_receipt_signature_fails_closed(self) -> None:
        data = json.loads(self.receipt.read_text(encoding="utf-8"))
        data["custodian"] = "attacker"
        self.receipt.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "signature verification"):
            self._verify()

    def test_duplicate_json_key_is_rejected(self) -> None:
        duplicate = self.directory / "duplicate.json"
        duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "duplicate JSON key"):
            load_strict_json(duplicate)

    def test_repository_contained_trust_registry_is_rejected(self) -> None:
        inside = ROOT / ".hepta-test-trust-registry.json"
        try:
            inside.write_bytes(self.registry.read_bytes())
            with self.assertRaisesRegex(ArchiveReceiptError, "outside the repository"):
                verify_archive_receipt(
                    receipt_path=self.receipt, artifact_path=self.artifact,
                    trust_registry_path=inside, repository_root=ROOT,
                    expected_head=HEAD, expected_tree=TREE,
                )
        finally:
            inside.unlink(missing_ok=True)

    def test_receipt_shape_is_closed(self) -> None:
        data = json.loads(self.receipt.read_text(encoding="utf-8"))
        data["unreviewed_authority"] = True
        self.receipt.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ArchiveReceiptError, "keys are not closed"):
            self._verify()


if __name__ == "__main__":
    unittest.main()
