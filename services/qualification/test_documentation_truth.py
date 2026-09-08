from __future__ import annotations

import hashlib
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
FILES = (
    "README.md",
    "docs/CURRENT_STATE.md",
    "docs/PROJECT_STATE.json",
    "docs/HG0087_IMPLEMENTATION_STATUS.json",
    "docs/REMEDIATION_GAP_LEDGER.json",
    "docs/MATURITY_MODEL.md",
    "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md",
    "evidence/source-baselines/pr101-35f01329/manifest.json",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part01",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part02",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part03",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part04",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part05",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part06",
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part07",
)
MANIFEST = "evidence/source-baselines/pr101-35f01329/manifest.json"
FIRST_ARCHIVE_PART = (
    "evidence/source-baselines/pr101-35f01329/"
    "hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part01"
)


class DocumentationTruthRepositoryTests(unittest.TestCase):
    def test_repository_truth_is_synchronized_and_evidence_bound(self) -> None:
        result = validate(ROOT)
        self.assertEqual(result["hg0087_status"], "CLOSED_SOURCE")
        self.assertEqual(result["hg0087_slices"], 7)
        self.assertEqual(result["repository_actionable_open"], 0)
        self.assertEqual(result["hg0089_status"], "BLOCKED_ADMIN_SETTING")
        self.assertEqual(result["maturity_stages"], 7)
        self.assertEqual(result["required_jobs"], 7)
        self.assertEqual(result["baseline_members"], 7)
        self.assertEqual(
            result["last_qualified_commit"],
            "35f01329262d6a137bfa3c7e95302a397ed32676",
        )
        self.assertEqual(
            result["baseline_archive_sha256"],
            "baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897",
        )


class DocumentationTruthNegativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in FILES:
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def no_history(_root: Path, _manifest: dict) -> None:
        return None

    def check(self, pattern: str, *, manifest_digest: str | None = None) -> None:
        kwargs = {"_history_verifier": self.no_history}
        if manifest_digest is not None:
            kwargs["_manifest_digest"] = manifest_digest
        with self.assertRaisesRegex(DocumentationTruthError, pattern):
            validate(self.root, **kwargs)

    def read_text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def write_text(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8")

    def read_json(self, relative: str) -> dict:
        return json.loads(self.read_text(relative))

    def write_json(self, relative: str, value: dict, *, sort_keys: bool = False) -> None:
        self.write_text(
            relative,
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
        )

    def mutate_project(self, mutation) -> None:
        value = self.read_json("docs/PROJECT_STATE.json")
        mutation(value)
        self.write_json("docs/PROJECT_STATE.json", value)

    def mutate_manifest(self, mutation) -> str:
        value = self.read_json(MANIFEST)
        mutation(value)
        self.write_json(MANIFEST, value, sort_keys=True)
        return hashlib.sha256((self.root / MANIFEST).read_bytes()).hexdigest()

    def test_stale_open_claim_is_rejected(self) -> None:
        self.write_text(
            "README.md",
            self.read_text("README.md") + "\nHG-0087 remains OPEN\n",
        )
        self.check("stale source status")

    def test_hg0087_machine_drift_is_rejected(self) -> None:
        value = self.read_json("docs/HG0087_IMPLEMENTATION_STATUS.json")
        value["aggregate_status"] = "OPEN"
        self.write_json("docs/HG0087_IMPLEMENTATION_STATUS.json", value)
        self.check("aggregate status")

    def test_administration_gate_promotion_is_rejected(self) -> None:
        value = self.read_json("docs/REMEDIATION_GAP_LEDGER.json")
        for row in value["gaps"]:
            if row["id"] == "HG-0089":
                row["status"] = "CLOSED_SOURCE"
        self.write_json("docs/REMEDIATION_GAP_LEDGER.json", value)
        self.check("falsely promotes HG-0089")

    def test_machine_ci_qualification_promotion_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["active_successor"].update(
                {"embedded_maturity": "ci_qualified"}
            )
        )
        self.check("self-promoted")

    def test_machine_release_promotion_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["active_successor"].update({"released": True})
        )
        self.check("self-promoted")

    def test_prose_successor_promotion_is_rejected(self) -> None:
        self.write_text(
            "docs/CURRENT_STATE.md",
            self.read_text("docs/CURRENT_STATE.md")
            + "\nCurrent successor is `ci_qualified`.\n",
        )
        self.check("prohibited successor promotion")

    def test_workflow_run_substitution_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["last_qualified_source"].update(
                {"workflow_run_id": 99999999999}
            )
        )
        self.check("workflow run substitution")

    def test_artifact_substitution_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["last_qualified_source"].update(
                {"artifact_id": 99999999999}
            )
        )
        self.check("artifact substitution")

    def test_review_substitution_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["last_qualified_source"].update(
                {"code_owner_review_id": 9999999999}
            )
        )
        self.check("review substitution")

    def test_commit_tree_mismatch_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["last_qualified_source"].update(
                {"tree": "0" * 40}
            )
        )
        self.check("commit/tree mismatch")

    def test_non_hex_commit_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["last_qualified_source"].update(
                {"commit": "g" * 40}
            )
        )
        self.check("lowercase 40-hex")

    def test_unknown_project_field_is_rejected(self) -> None:
        self.mutate_project(lambda value: value.update({"authority_override": True}))
        self.check("unknown keys")

    def test_unknown_successor_field_is_rejected(self) -> None:
        self.mutate_project(
            lambda value: value["active_successor"].update(
                {"qualification_override": True}
            )
        )
        self.check("unknown keys")

    def test_duplicate_completed_is_rejected(self) -> None:
        text = self.read_text("docs/PROJECT_STATE.json")
        needle = '    "completed": true,\n'
        self.assertIn(needle, text)
        self.write_text(
            "docs/PROJECT_STATE.json",
            text.replace(needle, needle + '    "completed": true,\n', 1),
        )
        self.check("duplicate JSON object member.*completed")

    def test_duplicate_commit_is_rejected(self) -> None:
        text = self.read_text("docs/PROJECT_STATE.json")
        needle = (
            '    "commit": "35f01329262d6a137bfa3c7e95302a397ed32676",\n'
        )
        self.assertIn(needle, text)
        self.write_text(
            "docs/PROJECT_STATE.json",
            text.replace(needle, needle + needle, 1),
        )
        self.check("duplicate JSON object member.*commit")

    def test_duplicate_digest_is_rejected(self) -> None:
        text = self.read_text("docs/PROJECT_STATE.json")
        needle = (
            '    "artifact_zip_sha256": '
            '"baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897",\n'
        )
        self.assertIn(needle, text)
        self.write_text(
            "docs/PROJECT_STATE.json",
            text.replace(needle, needle + needle, 1),
        )
        self.check("duplicate JSON object member.*artifact_zip_sha256")

    def test_non_finite_json_is_rejected(self) -> None:
        text = self.read_text("docs/PROJECT_STATE.json")
        self.write_text(
            "docs/PROJECT_STATE.json",
            text.replace("{\n", '{\n  "poison": NaN,\n', 1),
        )
        self.check("non-finite JSON number")

    def test_manifest_duplicate_source_commit_is_rejected_before_hash(self) -> None:
        text = self.read_text(MANIFEST)
        needle = (
            '  "source_commit": '
            '"35f01329262d6a137bfa3c7e95302a397ed32676",\n'
        )
        self.assertIn(needle, text)
        self.write_text(MANIFEST, text.replace(needle, needle + needle, 1))
        self.check("duplicate JSON object member.*source_commit")

    def test_manifest_non_finite_json_is_rejected_before_hash(self) -> None:
        text = self.read_text(MANIFEST)
        self.write_text(MANIFEST, text.replace("{\n", '{\n  "poison": Infinity,\n', 1))
        self.check("non-finite JSON number")

    def test_manifest_unknown_field_is_rejected(self) -> None:
        digest = self.mutate_manifest(
            lambda value: value.update({"authority_override": True})
        )
        self.check("unknown keys", manifest_digest=digest)

    def test_manifest_run_substitution_is_rejected(self) -> None:
        digest = self.mutate_manifest(
            lambda value: value["workflow"].update({"id": 99999999999})
        )
        self.check("workflow id differs", manifest_digest=digest)

    def test_manifest_artifact_substitution_is_rejected(self) -> None:
        digest = self.mutate_manifest(
            lambda value: value["artifact"].update({"id": 99999999999})
        )
        self.check("artifact id differs", manifest_digest=digest)

    def test_manifest_review_substitution_is_rejected(self) -> None:
        digest = self.mutate_manifest(
            lambda value: value["independent_review"].update(
                {"review_id": 9999999999}
            )
        )
        self.check("independent review differs", manifest_digest=digest)

    def test_manifest_raw_tamper_is_rejected_by_pin(self) -> None:
        text = self.read_text(MANIFEST)
        self.write_text(
            MANIFEST,
            text.replace(
                "historical_repository_source_qualification_only",
                "historical_repository_source_qualification_only_tampered",
                1,
            ),
        )
        self.check("manifest digest mismatch")

    def test_archive_tamper_is_rejected(self) -> None:
        path = self.root / FIRST_ARCHIVE_PART
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        self.check("archive part size or digest mismatch")

    def test_maturity_order_drift_is_rejected(self) -> None:
        text = self.read_text("docs/MATURITY_MODEL.md")
        first = "### 1. `design_draft`"
        second = "### 2. `source_implemented`"
        text = text.replace(first, "__FIRST__", 1)
        text = text.replace(second, first, 1)
        text = text.replace("__FIRST__", second, 1)
        self.write_text("docs/MATURITY_MODEL.md", text)
        self.check("stage order drifted")

    def test_duplicate_maturity_heading_is_rejected(self) -> None:
        self.write_text(
            "docs/MATURITY_MODEL.md",
            self.read_text("docs/MATURITY_MODEL.md") + "\n### 7. `released`\n",
        )
        self.check("heading must occur exactly once")


if __name__ == "__main__":
    unittest.main()
