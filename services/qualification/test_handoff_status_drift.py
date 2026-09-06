"""Structural agreement tests; matching prose is not semantic completeness."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_module_handoff import HandoffError, REQUIRED_DIMENSIONS, validate


class HandoffStatusDriftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.primary = "docs/MODULE_DEVELOPMENT_GUIDE.md#sample"
        self.status = "Fixture platform with a deliberately bounded source-only implementation."
        self.ceiling = "Fixture source tests do not prove any production or independently issued authority."
        self.machine = {"schema_version": 1, "extends_registry": "docs/MODULE_COVERAGE.json",
            "dimension_profile": "engineering-handoff-v1", "required_dimensions": list(REQUIRED_DIMENSIONS),
            "modules": [{"id": "sample", "lifecycle": "development_reference",
                "profile": "engineering-handoff-v1", "index_anchor": "docs/development/MODULE_HANDOFF.md#sample",
                "primary_document": self.primary, "platform_status": self.status,
                "evidence_ceiling": self.ceiling}]}
        module = {"id": "sample", "owner": "fixture-owner", "lifecycle": "development_reference",
            "source_roots": ["fixture.py"], "documentation": [self.primary], "tests": ["test_fixture.py"],
            "contracts": ["contract.json"], "external_gates": ["independent fixture gate"]}
        self.write("docs/MODULE_COVERAGE.json", json.dumps({"schema_version": 1, "modules": [module]}))
        self.write("docs/MODULE_DEVELOPMENT_GUIDE.md", "<!-- module:sample -->\n" +
                   ("Fixture content for a structural test, not project engineering documentation.\n" * 12))
        self.write("fixture.py", "")
        self.write("test_fixture.py", "")
        self.write("contract.json", "{}")
        self.write("README.md", "docs/MODULE_HANDOFF.json docs/development/MODULE_HANDOFF.md "
                   "contracts/conformance/canonical-json-v1.json")
        self.index = (f"<!-- handoff:sample -->\n## sample\n\nPrimary detailed document: `{self.primary}`. "
                      f"Platform status: {self.status} Evidence ceiling: {self.ceiling}\n")
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def save(self):
        self.write("docs/MODULE_HANDOFF.json", json.dumps(self.machine))
        self.write("docs/development/MODULE_HANDOFF.md", self.index)

    def test_matching_status_is_accepted(self):
        self.assertEqual(validate(self.root), {"modules": 1, "primary_documents": 1})

    def test_machine_platform_change_requires_index_update(self):
        self.machine["modules"][0]["platform_status"] = "A different platform state with enough substantive characters."
        self.save()
        with self.assertRaisesRegex(HandoffError, "differs from machine"):
            validate(self.root)

    def test_machine_evidence_change_requires_index_update(self):
        self.machine["modules"][0]["evidence_ceiling"] = "A different evidence boundary with enough substantive characters."
        self.save()
        with self.assertRaisesRegex(HandoffError, "differs from machine"):
            validate(self.root)

    def test_index_only_change_is_rejected(self):
        self.index = self.index.replace(self.status, "An obsolete platform description should no longer be accepted.")
        self.save()
        with self.assertRaisesRegex(HandoffError, "differs from machine"):
            validate(self.root)

    def test_duplicate_conflicting_labels_are_rejected(self):
        self.index += "\nPlatform status: Another conflicting status. Evidence ceiling: Another conflicting ceiling.\n"
        self.save()
        with self.assertRaisesRegex(HandoffError, "differs from machine"):
            validate(self.root)

    def test_line_wrapping_does_not_change_status(self):
        self.index = self.index.replace(" Evidence ceiling:", "\nEvidence ceiling:")
        self.save()
        self.assertEqual(validate(self.root)["modules"], 1)


if __name__ == "__main__":
    unittest.main()
