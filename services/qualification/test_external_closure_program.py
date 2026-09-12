from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_external_closure_program import (
    ExternalClosureProgramError,
    EXPECTED_ISSUES,
    PROGRAM,
    validate,
)


class ExternalClosureProgramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]
        self.program = json.loads(
            (self.root / PROGRAM).read_text(encoding="utf-8")
        )
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-closure-program-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "program.json"

    def write(self, value=None) -> Path:
        selected = self.program if value is None else value
        self.path.write_text(
            json.dumps(selected, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.path

    def test_actual_program_covers_every_external_authority_gate(self) -> None:
        result = validate(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["gates"], 13)
        self.assertEqual(result["issues"], len(EXPECTED_ISSUES))
        self.assertEqual(
            result["status_counts"],
            {
                "BLOCKED_ADMIN_SETTING": 1,
                "BLOCKED_EXTERNAL": 11,
                "BLOCKED_UPSTREAM": 1,
            },
        )
        self.assertEqual(
            result["claim_ceiling"],
            "source_preparation_only_no_external_gate_closed",
        )

    def test_false_closed_status_is_rejected(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][0]["status"] = "CLOSED_VERIFIED"
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "unsupported or falsely promoted status",
        ):
            validate(self.root, program_path=self.write(value))

    def test_missing_gate_is_rejected(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"].pop()
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "exactly thirteen gates",
        ):
            validate(self.root, program_path=self.write(value))

    def test_issue_cannot_be_reassigned_or_duplicated(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][1]["issue_numbers"] = [84]
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "assigned to multiple closure gates",
        ):
            validate(self.root, program_path=self.write(value))

    def test_gap_cannot_be_reassigned_or_duplicated(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][1]["gap_ids"] = ["HG-0017"]
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "assigned to multiple closure gates",
        ):
            validate(self.root, program_path=self.write(value))

    def test_source_preparation_path_traversal_is_rejected(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][0]["source_preparation"][0] = "../outside.json"
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "non-canonical source-preparation reference",
        ):
            validate(self.root, program_path=self.write(value))

    def test_source_preparation_must_exist(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][0]["source_preparation"][0] = (
            "contracts/not-present.json"
        )
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "source-preparation reference is missing",
        ):
            validate(self.root, program_path=self.write(value))

    def test_claim_ceiling_cannot_be_removed(self) -> None:
        value = copy.deepcopy(self.program)
        value["claim_ceiling"] = "This is a deliberately long but false statement. " * 8
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "claim ceiling lacks required semantic",
        ):
            validate(self.root, program_path=self.write(value))

    def test_prohibited_substitutes_must_remain_explicit(self) -> None:
        value = copy.deepcopy(self.program)
        value["gates"][0]["prohibited_substitutes"] = []
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "prohibited_substitutes must contain at least 4 entries",
        ):
            validate(self.root, program_path=self.write(value))

    def test_duplicate_json_members_fail_closed(self) -> None:
        self.path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ExternalClosureProgramError,
            "duplicate JSON key",
        ):
            validate(self.root, program_path=self.path)


if __name__ == "__main__":
    unittest.main()
