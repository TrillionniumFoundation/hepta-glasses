from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from services.qualification.documentation_truth import (
    DocumentationTruthError,
    PINNED_BASELINE,
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
        self.assertEqual(result["successor_maturity"], "source_implemented")
        self.assertEqual(result["last_qualified_commit"], PINNED_BASELINE["commit"])
        self.assertEqual(result["successor_pull_request"], 127)
        self.assertEqual(result["successor_branch"], "integration/hepta-main-convergence-20260912")
        self.assertEqual(result["successor_base_branch"], "main")
        self.assertEqual(result["module_registry"], "docs/modules/modules.json")


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

    def project(self) -> dict:
        return self.read_json("docs/PROJECT_STATE.json")

    def save_project(self, value: dict) -> None:
        self.write_json("docs/PROJECT_STATE.json", value)

    def test_stale_open_claim_is_rejected(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.write_text("README.md", readme + "\nHG-0087 remains OPEN\n")
        with self.assertRaisesRegex(DocumentationTruthError, "stale source-status phrase"):
            validate(self.root)

    def test_machine_slice_drift_is_rejected(self) -> None:
        status = self.read_json("docs/HG0087_IMPLEMENTATION_STATUS.json")
        status["aggregate_status"] = "OPEN"
        self.write_json("docs/HG0087_IMPLEMENTATION_STATUS.json", status)
        with self.assertRaisesRegex(DocumentationTruthError, "aggregate status"):
            validate(self.root)

    def test_administration_gate_promotion_is_rejected(self) -> None:
        ledger = self.read_json("docs/REMEDIATION_GAP_LEDGER.json")
        for row in ledger["gaps"]:
            if row["id"] == "HG-0089":
                row["status"] = "CLOSED_SOURCE"
        self.write_json("docs/REMEDIATION_GAP_LEDGER.json", ledger)
        with self.assertRaisesRegex(DocumentationTruthError, "administration gate"):
            validate(self.root)

    def test_successor_evidence_transfer_is_rejected(self) -> None:
        project = self.project()
        project["current_successor"]["evidence_transfer_allowed"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "promoted"):
            validate(self.root)

    def test_successor_ci_promotion_is_rejected(self) -> None:
        project = self.project()
        project["current_successor"]["maturity"] = "ci_qualified"
        project["current_successor"]["qualified"] = True
        project["current_successor"]["ci_qualified"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "promoted"):
            validate(self.root)

    def test_successor_release_promotion_is_rejected(self) -> None:
        project = self.project()
        project["current_successor"]["maturity"] = "released"
        project["current_successor"]["released"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "promoted"):
            validate(self.root)

    def test_prose_successor_promotion_is_rejected(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        self.write_text("README.md", readme + "\nActive successor is `ci_qualified`.\n")
        with self.assertRaisesRegex(DocumentationTruthError, "promotes"):
            validate(self.root)

    def test_required_check_drift_is_rejected(self) -> None:
        project = self.project()
        project["repository_actionable_gate"]["required_checks"].pop()
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "required check set drifted"):
            validate(self.root)

    def test_current_successor_pointer_drift_is_rejected(self) -> None:
        project = self.project()
        project["source_authority"]["pull_request"] = 114
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "pull request drifted"):
            validate(self.root)

    def test_current_successor_branch_drift_is_rejected(self) -> None:
        project = self.project()
        project["source_authority"]["branch"] = "wrong-branch"
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "head branch drifted"):
            validate(self.root)

    def test_canonical_module_registry_pointer_drift_is_rejected(self) -> None:
        project = self.project()
        project["repository_actionable_gate"]["module_registry"] = "docs/MODULE_COVERAGE.json"
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "canonical module registry"):
            validate(self.root)

    def test_artifact_name_substitution_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["artifact_name"] = "hepta-source-evidence-wrong"
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "immutable tuple drifted"):
            validate(self.root)

    def test_run_substitution_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["workflow_run_id"] += 1
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "immutable tuple drifted"):
            validate(self.root)

    def test_artifact_substitution_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["artifact_id"] += 1
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "immutable tuple drifted"):
            validate(self.root)

    def test_review_substitution_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["code_owner_review_id"] += 1
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "immutable tuple drifted"):
            validate(self.root)

    def test_commit_tree_mismatch_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["tree"] = "0" * 40
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "immutable tuple drifted"):
            validate(self.root)

    def test_non_hex_commit_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["commit"] = "z" * 40
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "lowercase 40-hex"):
            validate(self.root)

    def test_unknown_project_field_is_rejected(self) -> None:
        project = self.project()
        project["repository_says_released"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "unknown keys"):
            validate(self.root)

    def test_unknown_baseline_field_is_rejected(self) -> None:
        project = self.project()
        project["last_qualified_source"]["self_asserted"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "unknown keys"):
            validate(self.root)

    def test_duplicate_completed_is_rejected(self) -> None:
        path = self.root / "docs/PROJECT_STATE.json"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            '"completed": true,',
            '"completed": true,\n    "completed": true,',
            1,
        )
        self.write_text("docs/PROJECT_STATE.json", text)
        with self.assertRaisesRegex(DocumentationTruthError, "duplicate JSON object member"):
            validate(self.root)

    def test_duplicate_digest_is_rejected(self) -> None:
        path = self.root / "docs/PROJECT_STATE.json"
        text = path.read_text(encoding="utf-8")
        needle = f'"artifact_zip_sha256": "{PINNED_BASELINE["artifact_zip_sha256"]}",'
        text = text.replace(needle, needle + "\n    " + needle, 1)
        self.write_text("docs/PROJECT_STATE.json", text)
        with self.assertRaisesRegex(DocumentationTruthError, "duplicate JSON object member"):
            validate(self.root)

    def test_non_finite_value_is_rejected(self) -> None:
        path = self.root / "docs/PROJECT_STATE.json"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            f'"artifact_id": {PINNED_BASELINE["artifact_id"]}',
            '"artifact_id": NaN',
            1,
        )
        self.write_text("docs/PROJECT_STATE.json", text)
        with self.assertRaisesRegex(DocumentationTruthError, "non-finite JSON number"):
            validate(self.root)

    def test_boolean_cannot_impersonate_integer(self) -> None:
        project = self.project()
        project["last_qualified_source"]["artifact_id"] = True
        self.save_project(project)
        with self.assertRaisesRegex(DocumentationTruthError, "integer"):
            validate(self.root)

    def test_maturity_order_drift_is_rejected(self) -> None:
        path = self.root / "docs/MATURITY_MODEL.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("### 1. `design_draft`", "### 2. `design_draft`", 1)
        self.write_text("docs/MATURITY_MODEL.md", text)
        with self.assertRaisesRegex(DocumentationTruthError, "identity/order drifted"):
            validate(self.root)


if __name__ == "__main__":
    unittest.main()
