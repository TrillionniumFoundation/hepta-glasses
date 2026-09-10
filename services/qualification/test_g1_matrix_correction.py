from __future__ import annotations

import copy
import unittest
from pathlib import Path

from services.qualification import g1_command_matrix as matrix

ROOT = Path(__file__).resolve().parents[2]


class G1MatrixCorrectionTests(unittest.TestCase):
    @staticmethod
    def microphone_example(document: dict[str, object]) -> dict[str, object]:
        commands = document["commands"]
        assert isinstance(commands, list)
        microphone = next(
            item
            for item in commands
            if isinstance(item, dict) and item.get("id") == "microphone_data"
        )
        examples = microphone["consumer_examples"]
        assert isinstance(examples, list)
        example = next(
            item
            for item in examples
            if isinstance(item, dict) and item.get("name") == "lc3_frame"
        )
        assert isinstance(example, dict)
        return example

    def test_exact_base_plus_single_correction_produces_202_byte_vector(self) -> None:
        raw = matrix.load_raw_matrix(ROOT)
        self.assertEqual(matrix.canonical_digest(raw), matrix.BASE_MATRIX_SHA256)
        raw_bytes = self.microphone_example(raw)["bytes"]
        self.assertIsInstance(raw_bytes, list)
        assert isinstance(raw_bytes, list)
        self.assertEqual(len(raw_bytes), 203)
        self.assertEqual(raw_bytes[:2], [0xF1, 0])
        self.assertEqual(raw_bytes[2:], [0] * 201)

        effective = matrix.load_effective_matrix(ROOT)
        effective_bytes = self.microphone_example(effective)["bytes"]
        self.assertIsInstance(effective_bytes, list)
        assert isinstance(effective_bytes, list)
        self.assertEqual(len(effective_bytes), 202)
        self.assertEqual(effective_bytes[:2], [0xF1, 0])
        self.assertEqual(effective_bytes[2:], [0] * 200)

        result = matrix.validate(ROOT)
        self.assertIs(result["ok"], True)
        self.assertEqual(result["correction_operations"], 1)
        self.assertEqual(
            result["correction_contract"],
            "contracts/g1-command-matrix-v1-corrections.json",
        )

    def test_correction_rejects_already_short_vector(self) -> None:
        raw = matrix.load_raw_matrix(ROOT)
        example = self.microphone_example(raw)
        data = example["bytes"]
        assert isinstance(data, list)
        example["bytes"] = data[:-1]
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "base matrix digest drifted",
        ):
            matrix.apply_pinned_correction(raw, copy.deepcopy(matrix.EXPECTED_CORRECTION))

    def test_correction_rejects_nonzero_tail_even_if_length_is_preserved(self) -> None:
        raw = matrix.load_raw_matrix(ROOT)
        example = self.microphone_example(raw)
        data = example["bytes"]
        assert isinstance(data, list)
        data[-1] = 1
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "base matrix digest drifted",
        ):
            matrix.apply_pinned_correction(raw, copy.deepcopy(matrix.EXPECTED_CORRECTION))

    def test_correction_manifest_is_closed_and_exact(self) -> None:
        raw = matrix.load_raw_matrix(ROOT)
        correction = copy.deepcopy(matrix.EXPECTED_CORRECTION)
        correction["operations"][0]["drop_count"] = 2
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "correction document drifted",
        ):
            matrix.apply_pinned_correction(raw, correction)

    def test_effective_matrix_remains_mutation_sensitive(self) -> None:
        effective = matrix.load_effective_matrix(ROOT)
        example = self.microphone_example(effective)
        data = example["bytes"]
        assert isinstance(data, list)
        data.append(0)
        with self.assertRaisesRegex(
            matrix.G1CommandMatrixError,
            "exceeds the typed frame maximum|typed command profile drifted",
        ):
            matrix.validate_document(ROOT, effective)


if __name__ == "__main__":
    unittest.main()
