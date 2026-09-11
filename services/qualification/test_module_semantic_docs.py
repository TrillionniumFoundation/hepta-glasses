from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tools.generate_module_docs import (
    REQUIRED_MODULE_FIELDS,
    load_canonical,
    module_digest,
    render_module,
)
from tools.validate_module_semantics import REQUIRED_HEADINGS, validate


class ModuleSemanticDocumentationTests(unittest.TestCase):
    def test_actual_repository_has_one_canonical_26_module_handoff(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = validate(root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["modules"], 26)
        self.assertEqual(result["semantic_dimensions"], 8)
        self.assertEqual(len(result["registry_digest"]), 64)

    def test_every_record_uses_the_complete_required_shape(self) -> None:
        root = Path(__file__).resolve().parents[2]
        registry = load_canonical(root)
        for module in registry["modules"]:
            with self.subTest(module=module["id"]):
                self.assertTrue(set(REQUIRED_MODULE_FIELDS).issubset(module))
                self.assertTrue(module["source_roots"])
                self.assertTrue(module["documentation"])
                self.assertTrue(module["tests"])
                self.assertTrue(module["contracts"])
                self.assertTrue(module["external_gates"])

    def test_record_digest_changes_when_an_interface_changes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        module = copy.deepcopy(load_canonical(root)["modules"][0])
        before = module_digest(module)
        module["contracts"] = [*module["contracts"], "contracts/fixture-change.json"]
        self.assertNotEqual(before, module_digest(module))

    def test_generated_page_binds_all_eight_dimensions_and_module_data(self) -> None:
        root = Path(__file__).resolve().parents[2]
        module = load_canonical(root)["modules"][0]
        rendered = render_module(module)
        positions = [rendered.index(heading) for heading in REQUIRED_HEADINGS]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(module_digest(module), rendered)
        self.assertIn(module["owner"], rendered)
        self.assertIn(module["primary_document"], rendered)
        for reference in (
            *module["source_roots"],
            *module["documentation"],
            *module["tests"],
            *module["contracts"],
        ):
            self.assertIn(f"`{reference}`", rendered)


if __name__ == "__main__":
    unittest.main()
