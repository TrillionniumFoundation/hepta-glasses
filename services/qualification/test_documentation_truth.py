from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from services.qualification.documentation_truth import (
    DocumentationTruthError,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


class DocumentationTruthRepositoryTests(unittest.TestCase):
    def test_repository_truth_is_synchronized(self) -> None:
        result = validate(ROOT)
        self.assertEqual(result["hg0087_status"], "CLOSED_SOURCE")
        self.assertEqual(result["hg0087_slices"], 7)
        self.assertEqual(result["repository_actionable_open"], 0)
        self.assertEqual(result["hg0089_status"], "BLOCKED_ADMIN_SETTING")
        self.assertEqual(result["maturity_stages"], 7)
        self.assertEqual(result["required_jobs"], 7)


class DocumentationTruthNegativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (
            "README.md",
            "docs/CURRENT_STATE.md",
            "docs/PROJECT_STATE.json",
            "docs/HG0087_IMPLEMENTATION_STATUS.json",
            "docs/REMEDIATION_GAP_LEDGER.json",
            "docs/MATURITY_MODEL.md",
            "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md",
        ):
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_text(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8")

    def read_json(self, relative: str) -> dict:
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def write_json(self, relative: str, value: dict) -> None:
        self.write_text(
            relative,
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )

    def test_stale_open_claim_is_rejected(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.write_text("README.md", readme + "\nHG-0087 remains OPEN\n")
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "stale source-status phrase",
        ):
            validate(self.root)

    def test_machine_slice_drift_is_rejected(self) -> None:
        status = self.read_json("docs/HG0087_IMPLEMENTATION_STATUS.json")
        status["aggregate_status"] = "OPEN"
        self.write_json("docs/HG0087_IMPLEMENTATION_STATUS.json", status)
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "aggregate status",
        ):
            validate(self.root)

    def test_administration_gate_promotion_is_rejected(self) -> None:
        ledger = self.read_json("docs/REMEDIATION_GAP_LEDGER.json")
        for row in ledger["gaps"]:
            if row["id"] == "HG-0089":
                row["status"] = "CLOSED_SOURCE"
        self.write_json("docs/REMEDIATION_GAP_LEDGER.json", ledger)
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "administration gate",
        ):
            validate(self.root)

    def test_successor_evidence_transfer_is_rejected(self) -> None:
        project = self.read_json("docs/PROJECT_STATE.json")
        project["last_qualified_source"][
            "successor_requires_fresh_qualification"
        ] = False
        self.write_json("docs/PROJECT_STATE.json", project)
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "successor evidence transfer",
        ):
            validate(self.root)

    def test_required_check_drift_is_rejected(self) -> None:
        project = self.read_json("docs/PROJECT_STATE.json")
        project["repository_actionable_gate"]["required_checks"].pop()
        self.write_json("docs/PROJECT_STATE.json", project)
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "required check set drifted",
        ):
            validate(self.root)

    def test_artifact_commit_binding_is_rejected(self) -> None:
        project = self.read_json("docs/PROJECT_STATE.json")
        project["last_qualified_source"][
            "artifact_name"
        ] = "hepta-source-evidence-wrong"
        self.write_json("docs/PROJECT_STATE.json", project)
        with self.assertRaisesRegex(
            DocumentationTruthError,
            "artifact name",
        ):
            validate(self.root)


if __name__ == "__main__":
    unittest.main()
