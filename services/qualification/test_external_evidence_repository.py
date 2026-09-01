from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/validate_external_evidence.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_external_evidence_repository",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
external_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(external_evidence)


class CommittedExternalEvidenceTest(unittest.TestCase):
    def test_every_committed_candidate_package_is_complete_and_accepted(self) -> None:
        base = ROOT / "evidence/external"
        self.assertTrue((base / "README.md").is_file())

        packages = sorted(
            path
            for path in base.glob("*/bundle.json")
            if path.parent.name not in {"templates", "example"}
        )
        for bundle_path in packages:
            with self.subTest(bundle=str(bundle_path.relative_to(ROOT))):
                document = json.loads(bundle_path.read_text(encoding="utf-8"))
                candidate = document.get("candidate")
                self.assertIsInstance(candidate, dict)
                result = external_evidence.validate_bundle(
                    bundle_path,
                    artifact_root=bundle_path.parent / "artifacts",
                    expected_commit=candidate.get("source_commit"),
                    expected_tree=candidate.get("source_tree"),
                    require_complete=True,
                    require_accepted=True,
                )
                self.assertTrue(result["all_authority_owned_gaps_closed"])
                self.assertEqual(result["missing_gaps"], [])


if __name__ == "__main__":
    unittest.main()
