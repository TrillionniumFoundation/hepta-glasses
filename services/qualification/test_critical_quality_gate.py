from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = ROOT / "services/qualification/critical_quality_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("critical_quality_gate", GATE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load critical quality gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _load_gate()


class CriticalQualityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def _write(self, name: str, text: str) -> Path:
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def _contract(self, *, extra: dict[str, object] | None = None) -> Path:
        document: dict[str, object] = {
            "contract_id": "hepta-critical-dart-line-coverage-v1",
            "schema_version": 1,
            "metric": "instrumented_line_coverage_percent",
            "files": [
                {
                    "module_id": "contracts-compatibility",
                    "path": "lib/runtime/canonical_json.dart",
                    "minimum_instrumented_lines": 2,
                    "minimum_percent": 50.0,
                },
                {
                    "module_id": "g1-protocol-features",
                    "path": "lib/runtime/packet_codec.dart",
                    "minimum_instrumented_lines": 2,
                    "minimum_percent": 100.0,
                },
            ],
        }
        if extra:
            document.update(extra)
        return self._write("contract.json", json.dumps(document))

    def test_coverage_gate_uses_instrumented_lines_and_exact_paths(self) -> None:
        lcov = self._write(
            "lcov.info",
            """TN:
SF:lib/runtime/canonical_json.dart
DA:1,1
DA:2,0
LF:2
LH:1
end_of_record
SF:lib/runtime/packet_codec.dart
DA:1,3
DA:2,1
LF:2
LH:2
end_of_record
""",
        )
        result = GATE.evaluate_coverage(lcov, self._contract())
        self.assertTrue(result["passed"])
        self.assertEqual(
            [(entry["path"], entry["percent"]) for entry in result["files"]],
            [
                ("lib/runtime/canonical_json.dart", 50.0),
                ("lib/runtime/packet_codec.dart", 100.0),
            ],
        )

    def test_coverage_gate_fails_closed_on_duplicate_or_missing_records(self) -> None:
        duplicate = self._write(
            "duplicate.info",
            """SF:lib/runtime/canonical_json.dart
DA:1,1
end_of_record
SF:lib/runtime/canonical_json.dart
DA:2,1
end_of_record
""",
        )
        with self.assertRaises(GATE.QualityGateError):
            GATE.parse_lcov(duplicate)

        missing = self._write(
            "missing.info",
            """SF:lib/runtime/canonical_json.dart
DA:1,1
DA:2,1
end_of_record
""",
        )
        with self.assertRaisesRegex(GATE.QualityGateError, "absent from LCOV"):
            GATE.evaluate_coverage(missing, self._contract())

    def test_contract_rejects_unknown_fields_and_boolean_thresholds(self) -> None:
        with self.assertRaises(GATE.QualityGateError):
            GATE.load_coverage_contract(self._contract(extra={"unexpected": True}))

        document = json.loads(self._contract().read_text(encoding="utf-8"))
        document["files"][0]["minimum_instrumented_lines"] = True
        invalid = self._write("invalid.json", json.dumps(document))
        with self.assertRaises(GATE.QualityGateError):
            GATE.load_coverage_contract(invalid)

    def test_mutation_anchors_are_unique_and_semantic(self) -> None:
        source = (ROOT / "lib/runtime/packet_codec.dart").read_text(encoding="utf-8")
        identifiers: set[str] = set()
        for identifier, needle, replacement in GATE.MUTATIONS:
            self.assertNotIn(identifier, identifiers)
            identifiers.add(identifier)
            self.assertEqual(source.count(needle), 1, identifier)
            self.assertNotIn(replacement, source, identifier)
        self.assertEqual(len(identifiers), 3)


if __name__ == "__main__":
    unittest.main()
