from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import tools.external_evidence.signing_io as signing_io
import tools.sign_external_evidence as signer
import tools.validate_external_evidence as validator


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
class ExternalEvidenceSignerCustodyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _generate_keypair(self, stem: str) -> tuple[Path, Path]:
        private = self.root / f"{stem}-private.pem"
        public = self.root / f"{stem}-public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
            check=True,
            capture_output=True,
        )
        return private, public

    def _bundle(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "contract_id": "hepta-external-evidence-envelope-v1",
            "trust_registry": {
                "registry_id": "hepta-external-authority-trust-registry-v1",
                "sha256": "a" * 64,
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

    def _write_bundle(self, directory: Path | None = None) -> Path:
        root = directory or self.root
        root.mkdir(parents=True, exist_ok=True)
        path = root / "bundle.json"
        path.write_text(json.dumps(self._bundle()), encoding="utf-8")
        return path

    def test_private_key_replacement_after_snapshot_cannot_change_signer(self) -> None:
        first_private, first_public = self._generate_keypair("first")
        second_private, second_public = self._generate_keypair("second")
        second_bytes = second_private.read_bytes()
        original_verify = signing_io._verify_private_bytes

        def replace_then_verify(snapshot: bytes) -> None:
            first_private.write_bytes(second_bytes)
            original_verify(snapshot)

        payload = b"candidate-bound evidence statement"
        with patch.object(
            signing_io,
            "_verify_private_bytes",
            side_effect=replace_then_verify,
        ):
            signature = signer.sign_ed25519(first_private, payload)

        validator.verify_ed25519(
            first_public.read_text(encoding="utf-8"),
            payload,
            signature,
            label="first-key",
        )
        with self.assertRaises(validator.EvidenceError):
            validator.verify_ed25519(
                second_public.read_text(encoding="utf-8"),
                payload,
                signature,
                label="second-key",
            )

    def test_finalize_atomically_replaces_the_exact_input_object(self) -> None:
        bundle_path = self._write_bundle()
        before_inode = bundle_path.stat().st_ino
        result = signer.finalize(Namespace(bundle=bundle_path))
        finalized = json.loads(bundle_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"])
        self.assertFalse(result["input_bundle_unchanged"])
        self.assertNotEqual(bundle_path.stat().st_ino, before_inode)
        self.assertEqual(
            finalized["acceptance"]["bundle_digest"],
            validator.canonical_bundle_digest(finalized),
        )

    def test_finalize_can_create_immutable_successor_without_mutating_input(self) -> None:
        bundle_path = self._write_bundle()
        original = bundle_path.read_bytes()
        result = signer.finalize(
            Namespace(
                bundle=bundle_path,
                custody_root=self.root,
                output_bundle_uri="artifact://successors/finalized.json",
            )
        )
        successor = self.root / "successors" / "finalized.json"

        self.assertTrue(result["ok"])
        self.assertTrue(result["input_bundle_unchanged"])
        self.assertEqual(bundle_path.read_bytes(), original)
        self.assertTrue(successor.is_file())
        self.assertIsNotNone(
            json.loads(successor.read_text(encoding="utf-8"))["acceptance"][
                "bundle_digest"
            ]
        )

    def test_symlink_bundle_input_is_rejected_without_mutating_target(self) -> None:
        target = self._write_bundle()
        original = target.read_bytes()
        alias = self.root / "bundle-link.json"
        try:
            alias.symlink_to(target.name)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(ValueError, "regular file"):
            signer.finalize(Namespace(bundle=alias))
        self.assertEqual(target.read_bytes(), original)
        self.assertTrue(alias.is_symlink())

    def test_real_parent_replacement_rejects_bundle_update(self) -> None:
        custody = self.root / "custody"
        bundle_path = self._write_bundle(custody)
        snapshot = signing_io.load_bundle_snapshot(bundle_path)
        replacement = self.root / "replacement"
        custody.rename(replacement)
        custody.mkdir()
        attacker = custody / "bundle.json"
        attacker.write_text('{"attacker":true}', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "directory identity changed"):
            signing_io.atomic_replace_bundle(
                snapshot,
                signing_io.bundle_bytes(snapshot.value),
            )
        self.assertEqual(attacker.read_text(encoding="utf-8"), '{"attacker":true}')
        self.assertEqual(
            (replacement / "bundle.json").read_bytes(),
            snapshot.raw,
        )

    def test_symlink_successor_parent_receives_no_output(self) -> None:
        bundle_path = self._write_bundle()
        actual = self.root / "actual-successors"
        actual.mkdir()
        alias = self.root / "successors"
        try:
            alias.symlink_to(actual.name, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        with self.assertRaisesRegex(ValueError, "unsafe directory"):
            signer.finalize(
                Namespace(
                    bundle=bundle_path,
                    custody_root=self.root,
                    output_bundle_uri="artifact://successors/finalized.json",
                )
            )
        self.assertFalse((actual / "finalized.json").exists())

    def test_atomic_bundle_replacement_preserves_private_mode(self) -> None:
        bundle_path = self._write_bundle()
        signer.finalize(Namespace(bundle=bundle_path))
        self.assertEqual(os.stat(bundle_path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
