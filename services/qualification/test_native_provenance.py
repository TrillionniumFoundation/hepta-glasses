from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tools.native import validate_provenance as provenance

ROOT = Path(__file__).resolve().parents[2]


class NativeProvenanceTests(unittest.TestCase):
    def document(self) -> dict[str, object]:
        return provenance.strict_json(ROOT / provenance.MANIFEST)

    def test_exact_import_and_local_delta_inventory_matches_git(self) -> None:
        result = provenance.validate(ROOT)
        self.assertIs(result["ok"], True)
        self.assertEqual(
            result["external_import_commit"],
            "3899aac2b39ce969582cf6eb96ecb36be3e0e9e6",
        )
        self.assertEqual(
            result["external_import_tree"],
            "bc593f9b23ce9a49ead8b5652181639157032572",
        )
        self.assertIs(result["external_observation_requires_live_revalidation"], True)
        self.assertEqual(result["tree_units"], 4)
        self.assertEqual(result["tree_deltas"], 4)
        self.assertEqual(result["integration_files"], 5)
        self.assertEqual(result["integration_deltas"], 3)
        self.assertIs(result["direct_upstream_revision_known"], False)

    def test_changed_current_blob_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        units = document["tree_units"]
        self.assertIsInstance(units, list)
        assert isinstance(units, list)
        unit = units[1]
        self.assertIsInstance(unit, dict)
        assert isinstance(unit, dict)
        deltas = unit["deltas"]
        self.assertIsInstance(deltas, list)
        assert isinstance(deltas, list)
        delta = deltas[0]
        self.assertIsInstance(delta, dict)
        assert isinstance(delta, dict)
        delta["current_blob"] = "0" * 40
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "declared delta inventory does not match Git objects",
        ):
            provenance.validate_document(ROOT, document)

    def test_omitted_delta_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        units = document["tree_units"]
        assert isinstance(units, list)
        unit = units[2]
        assert isinstance(unit, dict)
        deltas = unit["deltas"]
        assert isinstance(deltas, list)
        del deltas[0]
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "declared delta inventory does not match Git objects",
        ):
            provenance.validate_document(ROOT, document)

    def test_extra_manifest_field_fails_closed(self) -> None:
        document = copy.deepcopy(self.document())
        document["unreviewed_extension"] = True
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "shape mismatch",
        ):
            provenance.validate_document(ROOT, document)

    def test_direct_upstream_revision_must_not_be_invented(self) -> None:
        document = copy.deepcopy(self.document())
        components = document["direct_upstream_components"]
        assert isinstance(components, list)
        component = components[0]
        assert isinstance(component, dict)
        component["revision"] = "1316cacaebc7a84a765f9f622078de61583b8596"
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "invents an unavailable direct-upstream revision",
        ):
            provenance.validate_document(ROOT, document)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_version":1,"schema_version":2}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                provenance.NativeProvenanceError,
                "duplicate JSON key",
            ):
                provenance.strict_json(path)


if __name__ == "__main__":
    unittest.main()
