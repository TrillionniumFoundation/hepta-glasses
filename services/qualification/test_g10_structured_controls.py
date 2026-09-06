"""Typed metadata assertions supplement legacy prose checks without promoting evidence."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class StructuredControlsTest(unittest.TestCase):
    def test_controls_are_typed_and_explicit(self):
        state = json.loads((ROOT / "docs/G10_STATE.json").read_text())
        controls = state["validation_controls"]
        self.assertEqual(controls, {
            "schema_version": 1,
            "can_manufacture_external_evidence": False,
            "repository_admission": "descriptor_anchored",
            "lexical_custody_scope": "transaction_wide",
            "crypto_executable_policy": "absolute_verified_path",
            "cross_authority_role_aliasing_allowed": False,
            "runtime_clock": "trusted_system_time",
        })
        self.assertIs(controls["can_manufacture_external_evidence"], False)
        self.assertIs(controls["cross_authority_role_aliasing_allowed"], False)
        self.assertEqual(state["authority_owned"]["inherited_blocked_count"], 12)
        self.assertTrue((ROOT / state["remediation_tracking"]).is_file())

    def test_legacy_metadata_compatibility_is_retained(self):
        state = json.loads((ROOT / "docs/G10_STATE.json").read_text())
        ledger = json.loads((ROOT / "docs/G10_GAP_LEDGER.json").read_text())
        for value in ("cannot manufacture", "descriptor-anchored", "transaction-wide lexical", "absolute cryptographic-executable"):
            self.assertIn(value, state["claim_ceiling"])
        self.assertIn("one key ID", state["authority_owned"]["closure_rule"])
        gap = next(row for row in ledger["gaps"] if row["id"] == "HG-0079")
        self.assertIn("complete validation transaction", gap["close_criteria"])


if __name__ == "__main__":
    unittest.main()
