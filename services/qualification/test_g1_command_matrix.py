from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import tools.validate_g1_command_matrix as matrix

ROOT = Path(__file__).resolve().parents[2]


class G1CommandMatrixTests(unittest.TestCase):
    def document(self) -> dict[str, object]:
        return matrix.strict_json(ROOT / matrix.MATRIX)

    def test_complete_matrix_matches_base_contract_and_repository(self) -> None:
        result = matrix.validate(ROOT)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["commands"], 12)
        self.assertEqual(result["mutating_commands"], 9)
        self.assertGreaterEqual(result["source_references"], 24)
        self.assertGreaterEqual(result["test_references"], 20)
        self.assertGreaterEqual(result["external_gates"], 6)
        self.assertIs(result["vendor_confirmation_required"], True)
        self.assertIs(result["physical_qualification_required"], True)

    def test_duplicate_command_byte_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        commands = document["commands"]
        assert isinstance(commands, list)
        first = commands[0]
        second = commands[1]
        assert isinstance(first, dict)
        assert isinstance(second, dict)
        second["command"] = first["command"]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "duplicate command byte",
        ):
            matrix.validate_document(ROOT, document)

    def test_base_command_drift_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        commands = document["commands"]
        assert isinstance(commands, list)
        display = next(
            item
            for item in commands
            if isinstance(item, dict) and item.get("id") == "display_text_and_ai"
        )
        display["command"] = "0x4F"
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "command byte drifted",
        ):
            matrix.validate_document(ROOT, document)

    def test_missing_source_reference_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        commands = document["commands"]
        assert isinstance(commands, list)
        microphone = commands[0]
        assert isinstance(microphone, dict)
        microphone["source_refs"] = ["lib/does-not-exist.dart"]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "does not identify a regular file",
        ):
            matrix.validate_document(ROOT, document)

    def test_retry_semantics_must_be_substantive(self) -> None:
        document = copy.deepcopy(self.document())
        commands = document["commands"]
        assert isinstance(commands, list)
        command = commands[0]
        assert isinstance(command, dict)
        command["retry_semantics"] = "retry"
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "must be a substantive string",
        ):
            matrix.validate_document(ROOT, document)

    def test_unknown_field_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        commands = document["commands"]
        assert isinstance(commands, list)
        command = commands[0]
        assert isinstance(command, dict)
        command["vendor_says_ok"] = True
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "shape mismatch",
        ):
            matrix.validate_document(ROOT, document)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_version":1,"schema_version":2}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                matrix.G1CommandMatrixError,
                "duplicate JSON key",
            ):
                matrix.strict_json(path)


if __name__ == "__main__":
    unittest.main()
