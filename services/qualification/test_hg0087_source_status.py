from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SLICES = {"identity", "model", "realtime", "capabilities", "speech", "skills", "memory"}

class HG0087SourceStatusTests(unittest.TestCase):
    def doc(self, path: str) -> dict:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))

    def test_source_closure_does_not_promote_external_authority(self) -> None:
        status = self.doc("docs/HG0087_IMPLEMENTATION_STATUS.json")
        self.assertEqual(status["aggregate_status"], "CLOSED_SOURCE")
        rows = {row["id"]: row for row in status["slices"]}
        self.assertEqual(set(rows), SLICES)
        for name, row in rows.items():
            self.assertEqual(row["status"], "CLOSED_SOURCE", name)
            self.assertTrue(row["remaining_external"], name)
            for field in ("source_evidence", "tests", "operations"):
                self.assertTrue(row[field], f"{name}.{field}")
                for relative in row[field]:
                    path = ROOT / relative
                    self.assertTrue(path.is_file(), relative)
                    self.assertFalse(path.is_symlink(), relative)
        ledger = self.doc("docs/REMEDIATION_GAP_LEDGER.json")
        gap = [row for row in ledger["gaps"] if row["id"] == "HG-0087"]
        self.assertEqual(len(gap), 1)
        self.assertEqual(gap[0]["status"], "CLOSED_SOURCE")
        for relative in gap[0]["evidence"]:
            self.assertTrue((ROOT / relative).is_file(), relative)
        project = self.doc("docs/PROJECT_STATE.json")
        gate = project["repository_actionable_gate"]
        self.assertNotIn("HG-0087", gate["active_open_gap_ids"])
        self.assertIn("HG-0087", gate["active_source_closed_gap_ids"])
        self.assertTrue(project["external_gates"])
        self.assertTrue(status["unchanged_authority_owned_gap_ids"])
        for relative in (
            "docs/CURRENT_STATE.md",
            "docs/development/2026-09-03_BLOCKER_EXECUTION_PLAN.md",
        ):
            self.assertIn("HG-0087 is `CLOSED_SOURCE`", (ROOT / relative).read_text(encoding="utf-8"))

if __name__ == "__main__":
    unittest.main()
