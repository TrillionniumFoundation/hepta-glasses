from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.qualification.release_gate import ReleaseGate
from services.qualification.release_gate_test_support import ReleaseGateFixtures


class ReleaseGateSourceTest(ReleaseGateFixtures, unittest.TestCase):
    def test_source_mode_passes_without_claiming_product_release(self) -> None:
        result = ReleaseGate().evaluate({"source": self.source()}, mode="source")
        self.assertTrue(result.passed, result.missing)

    def test_source_mode_rejects_stale_contracts_version(self) -> None:
        source = self.source()
        source["contracts_version"] = "2026-08-31-g5"
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("contracts_version", result.missing)

    def test_source_mode_rejects_incomplete_sbom(self) -> None:
        source = self.source()
        source["sbom_ecosystems"] = ["dart/pub"]
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("sbom_ecosystems", result.missing)

    def test_source_mode_rejects_history_finding(self) -> None:
        source = self.source()
        history = dict(source["history_scan"])
        history["finding_count"] = 1
        source["history_scan"] = history
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("history_scan", result.missing)

    def test_source_mode_rejects_unscanned_history_blob(self) -> None:
        source = self.source()
        history = dict(source["history_scan"])
        history["unscanned_blob_count"] = 1
        source["history_scan"] = history
        result = ReleaseGate().evaluate({"source": source}, mode="source")
        self.assertFalse(result.passed)
        self.assertIn("history_scan", result.missing)

    def test_artifact_digest_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = {
                "source-sbom.spdx.json": {"spdxVersion": "SPDX-2.3"},
                "source-provenance.json": {"type": "unsigned-source-provenance-v1"},
                "source-history-scan.json": {
                    "head": "a" * 40,
                    "scope": "all-fetched-refs-and-deduplicated-blobs",
                    "finding_count": 0,
                    "unscanned_blob_count": 0,
                },
                "source-native-sanitizer.json": {
                    "passed": True,
                    "lc3_cross_platform_parity": True,
                },
            }
            digests = {}
            for name, document in documents.items():
                encoded = json.dumps(document, sort_keys=True).encode() + b"\n"
                (root / name).write_bytes(encoded)
                digests[name] = hashlib.sha256(encoded).hexdigest()
            source = self.source()
            source["sbom"] = {"sha256": digests["source-sbom.spdx.json"]}
            source["provenance"] = {
                "sha256": digests["source-provenance.json"]
            }
            source["history_scan"] = {
                **source["history_scan"],
                "sha256": digests["source-history-scan.json"],
            }
            source["native_sanitizer"] = {
                **source["native_sanitizer"],
                "sha256": digests["source-native-sanitizer.json"],
            }
            result = ReleaseGate().evaluate(
                {"source": source}, mode="source", evidence_dir=root
            )
            self.assertTrue(result.passed, result.missing)
            (root / "source-sbom.spdx.json").write_text("tampered\n")
            result = ReleaseGate().evaluate(
                {"source": source}, mode="source", evidence_dir=root
            )
            self.assertFalse(result.passed)
            self.assertIn("artifact_sbom_digest", result.missing)


if __name__ == "__main__":
    unittest.main()
