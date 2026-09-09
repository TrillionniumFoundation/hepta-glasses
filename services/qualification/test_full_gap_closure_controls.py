from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CONTROL_FILES = (
    ".github/SECURITY.md",
    ".github/CONTRIBUTING.md",
    "docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md",
    "docs/development/2026-09-09_SOURCE_DEEPENING_WORK_PACKAGES.md",
    "docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md",
    "docs/development/MODULE_DOCUMENTATION_DEPTH_AUDIT_2026-09-09.md",
    "docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md",
)

EXPECTED_OPEN_ISSUES = {
    82,
    84,
    85,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    102,
}


class FullGapClosureControlTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        path = ROOT / relative
        self.assertTrue(path.is_file(), relative)
        self.assertFalse(path.is_symlink(), relative)
        return path.read_text(encoding="utf-8")

    def read_json(self, relative: str) -> dict[str, object]:
        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                self.assertNotIn(key, result, f"duplicate JSON key {key} in {relative}")
                result[key] = value
            return result

        value = json.loads(
            self.read(relative),
            object_pairs_hook=unique,
            parse_constant=lambda value: self.fail(
                f"non-finite JSON number {value} in {relative}"
            ),
        )
        self.assertIsInstance(value, dict, relative)
        return value

    def test_control_files_are_present_and_indexed(self) -> None:
        root_readme = self.read("README.md")
        docs_readme = self.read("docs/README.md")
        for relative in REQUIRED_CONTROL_FILES:
            self.read(relative)
            self.assertIn(relative, root_readme)
            docs_relative = relative.removeprefix("docs/")
            if relative.startswith("docs/"):
                self.assertIn(docs_relative, docs_readme)

    def test_live_successor_and_historical_baseline_are_not_conflated(self) -> None:
        prohibited = (
            "The live head and tree of Draft PR #101 identify the active adoption candidate",
            "The last independently qualified baseline is Draft PR #101",
        )
        for relative in ("README.md", "docs/CURRENT_STATE.md"):
            text = self.read(relative)
            self.assertIn("open PR #114", text)
            self.assertIn("last independently qualified historical baseline", text)
            self.assertIn("35f01329262d6a137bfa3c7e95302a397ed32676", text)
            self.assertIn("baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897", text)
            for phrase in prohibited:
                self.assertNotIn(phrase, text)

    def test_machine_state_keeps_successor_at_source_implemented(self) -> None:
        project = self.read_json("docs/PROJECT_STATE.json")
        last = project["last_qualified_source"]
        successor = project["current_successor"]
        authority = project["source_authority"]
        self.assertIsInstance(last, dict)
        self.assertIsInstance(successor, dict)
        self.assertIsInstance(authority, dict)
        assert isinstance(last, dict)
        assert isinstance(successor, dict)
        assert isinstance(authority, dict)
        self.assertEqual(last["pull_request"], 101)
        self.assertEqual(last["commit"], "35f01329262d6a137bfa3c7e95302a397ed32676")
        self.assertEqual(authority["pull_request"], 114)
        self.assertEqual(
            authority["branch"],
            "codex/hepta-main-convergence-20260909-v2",
        )
        self.assertEqual(successor["maturity"], "source_implemented")
        for field in (
            "qualified",
            "evidence_transfer_allowed",
            "ci_qualified",
            "integration_qualified",
            "physical_device_qualified",
            "pilot_qualified",
            "released",
        ):
            self.assertIs(successor[field], False, field)

    def test_closure_plan_is_complete_and_dependency_ordered(self) -> None:
        plan = self.read("docs/development/2026-09-09_FULL_GAP_CLOSURE_PLAN.md")
        positions: list[int] = []
        for stage in range(12):
            marker = f"C{stage} —"
            position = plan.find(marker)
            self.assertGreaterEqual(position, 0, marker)
            positions.append(position)
        self.assertEqual(positions, sorted(positions))
        for issue in EXPECTED_OPEN_ISSUES:
            self.assertIn(f"#{issue}", plan)
        for rule in (
            "Never mark a gap closed",
            "cannot satisfy the required independent latest-head approval",
            "product release gate has no override",
            "All gaps closed",
        ):
            self.assertIn(rule, plan)

    def test_control_board_covers_every_open_issue_exactly_as_coordination(self) -> None:
        board = self.read("docs/operations/FULL_GAP_CLOSURE_CONTROL_BOARD.md")
        rows = re.findall(r"^\|\s*\d+\s*\|\s*#(\d+)\s*\|", board, re.MULTILINE)
        observed = {int(value) for value in rows}
        self.assertEqual(observed, EXPECTED_OPEN_ISSUES)
        self.assertEqual(len(rows), len(EXPECTED_OPEN_ISSUES))
        self.assertIn("coordination surface", board)
        self.assertIn("never replaces GitHub API state", board)
        self.assertIn("does not have Repository Administration permission", board)

    def test_module_depth_audit_matches_canonical_registry(self) -> None:
        registry = self.read_json("docs/modules/modules.json")
        modules = registry["modules"]
        self.assertIsInstance(modules, list)
        assert isinstance(modules, list)
        self.assertEqual(len(modules), 26)
        identifiers = []
        for module in modules:
            self.assertIsInstance(module, dict)
            assert isinstance(module, dict)
            identifier = module.get("id")
            self.assertIsInstance(identifier, str)
            identifiers.append(identifier)
        self.assertEqual(len(identifiers), len(set(identifiers)))

        audit = self.read(
            "docs/development/MODULE_DOCUMENTATION_DEPTH_AUDIT_2026-09-09.md"
        )
        rows = re.findall(
            r"^\| `([^`]+)` \| `(?:SEMANTIC_PARTIAL|SEMANTIC_COMPLETE_SOURCE)` \|",
            audit,
            re.MULTILINE,
        )
        self.assertEqual(len(rows), 26)
        self.assertEqual(set(rows), set(identifiers))
        self.assertIn("SEMANTIC_PARTIAL", audit)
        self.assertIn("SEMANTIC_COMPLETE_SOURCE", audit)
        self.assertIn("does not replace", audit)

    def test_documentation_standard_requires_semantic_review(self) -> None:
        standard = self.read(
            "docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md"
        )
        required = (
            "Purpose, responsibility and non-goals",
            "Component and source map",
            "Public interfaces and contracts",
            "State machine and invariants",
            "Concurrency and atomicity",
            "Failure, retry, reconciliation and recovery",
            "Configuration, compatibility, migration and rollback",
            "Operations, observability and SLOs",
            "Security, privacy and abuse cases",
            "Verification and acceptance",
            "Ownership and change protocol",
        )
        for heading in required:
            self.assertIn(heading, standard)
        self.assertIn("Document length is not an acceptance criterion", standard)
        self.assertIn("independent reviewer", standard)

    def test_source_deepening_work_packages_are_complete(self) -> None:
        packages = self.read(
            "docs/development/2026-09-09_SOURCE_DEEPENING_WORK_PACKAGES.md"
        )
        positions = []
        for work_package in range(1, 8):
            marker = f"## WP{work_package} —"
            position = packages.find(marker)
            self.assertGreaterEqual(position, 0, marker)
            positions.append(position)
        self.assertEqual(positions, sorted(positions))
        for topic in (
            "Product identity convergence",
            "Versioned G1 protocol package",
            "Mobile application boundary refactor",
            "Behavioral test-depth gates",
            "Privacy-safe observability and SLOs",
            "Native dependency provenance",
            "Product UX, accessibility and diagnostics",
        ):
            self.assertIn(topic, packages)

    def test_security_and_contribution_rules_preserve_authority_boundaries(self) -> None:
        security = self.read(".github/SECURITY.md")
        contributing = self.read(".github/CONTRIBUTING.md")
        combined = security + "\n" + contributing
        for phrase in (
            "Do not place exploit details, credentials, private keys, tokens",
            "must not self-approve",
            "There is no security-gate or release-gate override",
            "Timeout, callback loss, disconnect, process death and missing acknowledgement are not proof of non-execution",
            "They cannot manufacture",
        ):
            self.assertIn(phrase, combined)
        self.assertNotRegex(combined, r"gh[pousr]_[A-Za-z0-9]{30,}")
        self.assertNotIn("-----BEGIN PRIVATE KEY-----", combined)


if __name__ == "__main__":
    unittest.main()
