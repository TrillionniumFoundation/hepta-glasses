from __future__ import annotations

import unittest
from pathlib import Path

from tools.validate_module_handoff import (
    HANDOFF_MARKER,
    HandoffError,
    marked_sections,
    require_status,
    validate,
)


class ModuleHandoffUnitTest(unittest.TestCase):
    def test_duplicate_markers_fail(self) -> None:
        text = (
            "<!-- handoff:one -->\nPrimary detailed document: `a`.\n"
            "<!-- handoff:one -->\nPrimary detailed document: `a`.\n"
        )
        with self.assertRaisesRegex(HandoffError, "duplicate module marker"):
            marked_sections(text, HANDOFF_MARKER)

    def test_placeholder_status_fails(self) -> None:
        with self.assertRaisesRegex(HandoffError, "placeholder"):
            require_status(
                "This platform status is explicitly TBD pending an owner decision.",
                label="fixture",
            )

    def test_short_status_fails(self) -> None:
        with self.assertRaisesRegex(HandoffError, "substantive"):
            require_status("unknown", label="fixture")


class RepositoryModuleHandoffTest(unittest.TestCase):
    def test_flattened_registry_has_complete_engineering_handoff(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = validate(root)
        self.assertEqual(
            result,
            {"modules": 26, "primary_documents": 26},
        )


if __name__ == "__main__":
    unittest.main()
