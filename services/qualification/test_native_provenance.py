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

    def inventory(self) -> dict[str, object]:
        return provenance.strict_json(ROOT / provenance.INVENTORY)

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
        self.assertIs(
            result["external_observation_requires_live_revalidation"],
            True,
        )
        self.assertEqual(result["external_path_observations"], 9)
        self.assertEqual(result["tree_units"], 4)
        self.assertEqual(result["tree_deltas"], 4)
        self.assertEqual(result["integration_files"], 5)
        self.assertEqual(result["integration_deltas"], 3)
        self.assertIs(result["direct_upstream_revision_known"], False)
        source_paths = result["component_source_path_sets"]
        self.assertIsInstance(source_paths, dict)
        assert isinstance(source_paths, dict)
        self.assertEqual(
            source_paths["xiph-rnnoise"],
            [
                "android/app/src/main/cpp/include",
                "android/app/src/main/cpp/rnnoise",
            ],
        )

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

    def test_count_preserving_tree_alias_is_rejected(self) -> None:
        document = copy.deepcopy(self.document())
        units = document["tree_units"]
        assert isinstance(units, list)
        source = copy.deepcopy(
            next(
                unit
                for unit in units
                if isinstance(unit, dict)
                and unit.get("id") == "android-liblc3-source"
            )
        )
        assert isinstance(source, dict)
        for unit in units:
            assert isinstance(unit, dict)
            for field in (
                "component_ids",
                "path",
                "kind",
                "imported_object",
                "current_object",
                "status",
                "deltas",
            ):
                unit[field] = copy.deepcopy(source[field])
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "fixed ID/path/component/import binding drifted",
        ):
            provenance.validate_document(ROOT, document)

    def test_imported_baseline_cannot_be_replaced_by_current_objects(self) -> None:
        document = copy.deepcopy(self.document())
        units = document["tree_units"]
        files = document["integration_files"]
        assert isinstance(units, list)
        assert isinstance(files, list)
        for unit in units:
            assert isinstance(unit, dict)
            unit["imported_object"] = unit["current_object"]
            unit["deltas"] = []
            unit["status"] = "unchanged_from_import_snapshot"
        for record in files:
            assert isinstance(record, dict)
            record["imported_blob"] = record["current_blob"]
            record["status"] = "unchanged_from_import_snapshot"
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "fixed ID/path/component/import binding drifted",
        ):
            provenance.validate_document(ROOT, document)

    def test_external_path_observation_cannot_follow_current_tree(self) -> None:
        document = copy.deepcopy(self.document())
        units = document["tree_units"]
        observations = document["external_path_observations"]
        assert isinstance(units, list)
        assert isinstance(observations, list)
        unit = next(
            item
            for item in units
            if isinstance(item, dict)
            and item.get("id") == "android-liblc3-source"
        )
        assert isinstance(unit, dict)
        observation = next(
            item
            for item in observations
            if isinstance(item, dict)
            and item.get("path") == unit["path"]
        )
        assert isinstance(observation, dict)
        observation["object"] = unit["current_object"]
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "external import path/object binding drifted",
        ):
            provenance.validate_document(ROOT, document)

    def test_component_source_paths_match_tree_unit_coverage(self) -> None:
        document = self.document()
        snapshot = document["import_snapshot"]
        self.assertIsInstance(snapshot, dict)
        assert isinstance(snapshot, dict)
        inventory = copy.deepcopy(self.inventory())
        components = inventory["components"]
        assert isinstance(components, list)
        component = next(
            item
            for item in components
            if isinstance(item, dict) and item.get("id") == "xiph-rnnoise"
        )
        assert isinstance(component, dict)
        component["source_paths"] = [
            "android/app/src/main/cpp/rnnoise",
        ]
        with self.assertRaisesRegex(
            provenance.NativeProvenanceError,
            "source_paths does not match fixed tree-unit coverage",
        ):
            provenance.validate_inventory_document(
                ROOT,
                snapshot,
                inventory,
                provenance.expected_component_source_paths(),
            )

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
