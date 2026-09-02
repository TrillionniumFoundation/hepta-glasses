from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
G9_REVISION = "2026-09-02-g9-authenticated-1"
G9_GAP = "HG-0073"
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def load_object(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain an object")
    return value


class G9MetadataCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_object("docs/G9_STATE.json")
        self.modules = load_object("docs/G9_MODULES.json")
        self.gaps = load_object("docs/G9_GAP_LEDGER.json")
        self.contract = load_object("contracts/external-evidence-envelope-v1.json")
        self.g8_ledger = load_object("docs/GAP_LEDGER.yaml")

    def test_revision_and_authority_owned_gap_set_are_synchronized(self) -> None:
        self.assertEqual(self.state["plan_revision"], G9_REVISION)
        self.assertEqual(self.modules["plan_revision"], G9_REVISION)
        self.assertEqual(self.gaps["plan_revision"], G9_REVISION)
        self.assertEqual(self.contract["contract_revision"], G9_REVISION)

        expected = set(self.contract["allowed_gap_ids"])
        self.assertEqual(set(self.state["authority_owned"]["gap_ids"]), expected)
        self.assertEqual(set(self.gaps["inherited_authority_owned_gap_ids"]), expected)

        by_id = {item["id"]: item for item in self.g8_ledger["gaps"]}
        self.assertTrue(expected.issubset(by_id))
        for gap_id in expected:
            self.assertIn(
                by_id[gap_id]["status"],
                {"BLOCKED_EXTERNAL", "BLOCKED_ADMIN_SETTING", "BLOCKED_UPSTREAM"},
            )

    def test_g9_source_gap_is_closed_with_existing_evidence(self) -> None:
        self.assertEqual(self.gaps["source_summary"]["repository_actionable_open"], 0)
        entries = self.gaps["gaps"]
        self.assertEqual([item["id"] for item in entries], [G9_GAP])
        gap = entries[0]
        self.assertEqual(gap["status"], "CLOSED_SOURCE")
        self.assertTrue(gap["close_criteria"].strip())
        for relative in gap["evidence"]:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_external_evidence_module_has_source_doc_test_contract_coverage(self) -> None:
        entries = self.modules["modules"]
        self.assertEqual(len(entries), 1)
        module = entries[0]
        self.assertEqual(module["id"], "external-evidence-authentication")
        for field in ("source_roots", "documentation", "tests", "contracts", "external_gates"):
            self.assertTrue(module[field], field)
        for relative in module["source_roots"]:
            self.assertTrue((ROOT / relative).exists(), relative)
        for field in ("documentation", "tests", "contracts"):
            for relative in module[field]:
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_docs_index_registers_g9_machine_truth(self) -> None:
        index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for name in (
            "G9_STATE.json",
            "G9_MODULES.json",
            "G9_GAP_LEDGER.json",
            "ADR-0004-external-evidence-authentication.md",
        ):
            self.assertIn(name, index)

    def test_g9_custody_contains_no_private_key_material(self) -> None:
        roots = [
            ROOT / "contracts" / "external-evidence-envelope-v1.json",
            ROOT / "schemas" / "external-evidence-envelope.schema.json",
            ROOT / "schemas" / "external-authority-trust-registry.schema.json",
            ROOT / "tools" / "external_evidence",
            ROOT / "tools" / "validate_external_evidence.py",
            ROOT / "tools" / "sign_external_evidence.py",
            ROOT / "evidence" / "external",
            ROOT / "evidence" / "templates" / "external-evidence-bundle.template.json",
            ROOT / "evidence" / "templates" / "external-authority-trust-registry.template.json",
        ]
        files: list[Path] = []
        for root in roots:
            files.extend(root.rglob("*") if root.is_dir() else [root])
        for path in files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(PRIVATE_KEY_PATTERN.search(text), str(path))

    def test_claim_ceiling_remains_external(self) -> None:
        self.assertEqual(self.state["repository_actionable"]["open"], 0)
        self.assertEqual(
            self.state["authority_owned"]["inherited_blocked_count"],
            len(self.contract["allowed_gap_ids"]),
        )
        self.assertIn("E5-E7", self.state["claim_ceiling"])
        self.assertIn("externally pinned", self.state["authority_owned"]["closure_rule"])


if __name__ == "__main__":
    unittest.main()
