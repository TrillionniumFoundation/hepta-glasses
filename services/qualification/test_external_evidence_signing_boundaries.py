from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import tools.external_evidence.signing as signing


class ExternalEvidenceSigningBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.custody = self.root / "custody"
        self.custody.mkdir()

    @staticmethod
    def _bundle() -> dict[str, object]:
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

    def _write_bundle(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "bundle.json"
        path.write_text(json.dumps(self._bundle()), encoding="utf-8")
        return path

    def test_input_bundle_must_be_below_declared_custody_root(self) -> None:
        outside = self._write_bundle(self.root / "outside")
        original = outside.read_bytes()

        with self.assertRaisesRegex(ValueError, "located below --custody-root"):
            signing.finalize(
                Namespace(
                    bundle=outside,
                    custody_root=self.custody,
                    output_bundle_uri="artifact://successors/finalized.json",
                )
            )

        self.assertEqual(outside.read_bytes(), original)
        self.assertFalse((self.custody / "successors/finalized.json").exists())

    def test_signature_and_successor_uris_must_be_distinct(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use distinct URIs"):
            signing._preflight_output_uris(
                Namespace(
                    output_bundle_uri="artifact://same/output.bin",
                    signature_uri="artifact://same/output.bin",
                ),
                include_signature=True,
            )

    def test_noncanonical_successor_uri_fails_before_creation(self) -> None:
        bundle = self._write_bundle(self.custody)
        original = bundle.read_bytes()

        with self.assertRaisesRegex(ValueError, "canonical scoped relative path"):
            signing.finalize(
                Namespace(
                    bundle=bundle,
                    custody_root=self.custody,
                    output_bundle_uri="artifact://successors//finalized.json",
                )
            )

        self.assertEqual(bundle.read_bytes(), original)
        self.assertFalse((self.custody / "successors").exists())

    def test_visible_successor_is_read_back_before_success(self) -> None:
        bundle = self._write_bundle(self.custody)
        original = bundle.read_bytes()

        with patch.object(signing, "_stable_read_target", return_value=b"replaced"):
            with self.assertRaisesRegex(RuntimeError, "changed before command completion"):
                signing.finalize(
                    Namespace(
                        bundle=bundle,
                        custody_root=self.custody,
                        output_bundle_uri="artifact://successors/finalized.json",
                    )
                )

        self.assertEqual(bundle.read_bytes(), original)
        self.assertTrue((self.custody / "successors/finalized.json").is_file())


if __name__ == "__main__":
    unittest.main()
