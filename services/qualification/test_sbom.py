from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.qualification.sbom import build_sbom, canonical_digest


class SbomTest(unittest.TestCase):
    def test_builds_deterministic_spdx_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib/example.dart").write_text("void main() {}\n", encoding="utf-8")
            (root / "pubspec.lock").write_text(
                'packages:\n  crypto:\n    version: "3.0.7"\n',
                encoding="utf-8",
            )
            first = build_sbom(root, document_name="test", namespace="urn:test")
            second = build_sbom(root, document_name="test", namespace="urn:test")
            self.assertEqual(canonical_digest(first), canonical_digest(second))
            self.assertEqual(first["spdxVersion"], "SPDX-2.3")
            self.assertEqual(first["packages"][0]["name"], "crypto")
            self.assertEqual(len(first["files"][0]["checksums"][0]["checksumValue"]), 64)


if __name__ == "__main__":
    unittest.main()
