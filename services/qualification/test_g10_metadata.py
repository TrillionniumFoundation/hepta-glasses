from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
G10_REVISION = "2026-09-02-g10-quorum-1"
G10_GAPS = ("HG-0076", "HG-0077")
G10_MODULES = ("authority-quorum-review-integrity",)


def load_object(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain an object")
    return value


class G10MetadataCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_object("docs/G10_STATE.json")
        self.modules = load_object("docs/G10_MODULES.json")
        self.gaps = load_object("docs/G10_GAP_LEDGER.json")
        self.g9_state = load_object("docs/G9_STATE.json")
        self.g9_gaps = load_object("docs/G9_GAP_LEDGER.json")
        self.contract = load_object(
            "contracts/external-evidence-envelope-v1.json"
        )

    def test_revision_and_inherited_gap_set_are_synchronized(self) -> None:
        self.assertEqual(self.state["plan_revision"], G10_REVISION)
        self.assertEqual(self.modules["plan_revision"], G10_REVISION)
        self.assertEqual(self.gaps["plan_revision"], G10_REVISION)
        self.assertEqual(
            self.state["extends_plan_revision"],
            self.g9_state["plan_revision"],
        )
        expected = set(self.contract["allowed_gap_ids"])
        self.assertEqual(
            set(self.state["authority_owned"]["gap_ids"]),
            expected,
        )
        self.assertEqual(
            set(self.gaps["inherited_authority_owned_gap_ids"]),
            expected,
        )

    def test_source_gaps_are_closed_with_existing_evidence(self) -> None:
        self.assertEqual(
            self.gaps["source_summary"]["repository_actionable_open"],
            0,
        )
        self.assertEqual(
            self.gaps["source_summary"]["closed_source"],
            len(G10_GAPS),
        )
        entries = self.gaps["gaps"]
        self.assertEqual(tuple(item["id"] for item in entries), G10_GAPS)
        self.assertEqual(
            tuple(self.state["repository_actionable"]["closed_source"]),
            G10_GAPS,
        )
        for gap in entries:
            with self.subTest(gap=gap["id"]):
                self.assertEqual(gap["status"], "CLOSED_SOURCE")
                self.assertTrue(gap["close_criteria"].strip())
                for relative in gap["evidence"]:
                    self.assertTrue((ROOT / relative).is_file(), relative)

    def test_module_has_source_doc_test_contract_coverage(self) -> None:
        entries = self.modules["modules"]
        self.assertEqual(
            tuple(item["id"] for item in entries),
            G10_MODULES,
        )
        for module in entries:
            for field in (
                "source_roots",
                "documentation",
                "tests",
                "contracts",
                "external_gates",
            ):
                self.assertTrue(module[field], f"{module['id']}.{field}")
            for relative in module["source_roots"]:
                self.assertTrue((ROOT / relative).exists(), relative)
            for field in ("documentation", "tests", "contracts"):
                for relative in module[field]:
                    self.assertTrue((ROOT / relative).is_file(), relative)

    def test_complete_validator_is_installed_for_every_package_caller(
        self,
    ) -> None:
        package_init = (
            ROOT / "tools/external_evidence/__init__.py"
        ).read_text(encoding="utf-8")
        policy = (
            ROOT / "tools/external_evidence/complete_closure.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "_complete_closure.validate_bundle",
            package_init,
        )
        self.assertIn(
            "missing_issuer_authority_classes",
            policy,
        )
        self.assertIn(
            "review_set_integrity",
            policy,
        )
        self.assertIn(
            "one key cannot satisfy multiple authority seats",
            policy,
        )

    def test_docs_index_registers_g10_machine_truth(self) -> None:
        index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for name in (
            "G10_STATE.json",
            "G10_MODULES.json",
            "G10_GAP_LEDGER.json",
            "G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md",
            "ADR-0008-authority-quorum-and-review-set-integrity.md",
        ):
            self.assertIn(name, index)

    def test_g10_does_not_promote_external_rows(self) -> None:
        self.assertEqual(self.state["repository_actionable"]["open"], 0)
        self.assertEqual(
            self.state["authority_owned"]["inherited_blocked_count"],
            len(self.contract["allowed_gap_ids"]),
        )
        self.assertIn("cannot manufacture", self.state["claim_ceiling"])
        g9_external = set(
            self.g9_gaps["inherited_authority_owned_gap_ids"]
        )
        self.assertEqual(
            set(self.gaps["inherited_authority_owned_gap_ids"]),
            g9_external,
        )


if __name__ == "__main__":
    unittest.main()
