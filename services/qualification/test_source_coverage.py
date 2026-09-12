"""Coverage is a reverse source-tree check, not just a declared-module count."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.validate_source_coverage import CoverageError, inspect_repository, load_registry, owners, reference


class SourceCoverageUnitTest(unittest.TestCase):
    def registry(self):
        return {"modules": {"one": {"source_roots": ["lib/a"], "tests": ["test/shared.py"]}}, "overrides": {}}

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(CoverageError, "unowned"):
            owners("services/new_daemon/main.py", self.registry())

    def test_exact_prefix_does_not_match_sibling(self):
        self.assertEqual(owners("lib/a/code.dart", self.registry()), ["one"])
        with self.assertRaises(CoverageError):
            owners("lib/abc/code.dart", self.registry())

    def test_ambiguous_ownership_needs_explicit_override(self):
        registry = self.registry()
        registry["modules"]["two"] = {"source_roots": ["lib/a"], "tests": ["test/shared.py"]}
        with self.assertRaisesRegex(CoverageError, "ambiguous"):
            owners("lib/a/code.dart", registry)
        registry["overrides"]["lib/a"] = "two"
        self.assertEqual(owners("lib/a/code.dart", registry), ["two"])

    def test_equal_test_references_are_explicitly_shared(self):
        registry = self.registry()
        registry["modules"]["two"] = {"source_roots": ["lib/b"], "tests": ["test/shared.py"]}
        self.assertEqual(owners("test/shared.py", registry), ["one", "two"])

    def test_narrower_source_claim_wins(self):
        registry = self.registry()
        registry["modules"]["two"] = {"source_roots": ["lib/a/special.dart"], "tests": []}
        self.assertEqual(owners("lib/a/special.dart", registry), ["two"])

    def test_escaping_and_missing_references_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ("../outside", "/etc/passwd", "missing", "./bad", "x//y"):
                with self.subTest(value=value), self.assertRaises(CoverageError):
                    reference(Path(directory), value)

    def test_linked_source_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").write_text("value")
            (root / "alias").symlink_to("real")
            with self.assertRaisesRegex(CoverageError, "linked"):
                reference(root, "alias")

    def test_registry_cycle_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"schema_version": 1, "extends_registry": "b.json"}))
            (root / "b.json").write_text(json.dumps({"schema_version": 1, "extends_registry": "a.json"}))
            with self.assertRaisesRegex(CoverageError, "cyclic"):
                load_registry(root, "a.json")

    def test_unknown_module_extension_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"schema_version": 1, "module_extensions": [{"id": "unknown", "source_roots": ["lib"]}]}))
            with self.assertRaisesRegex(CoverageError, "unknown module"):
                load_registry(root, "a.json")

    def test_real_git_inventory_detects_new_unregistered_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "lib").mkdir()
            for name in ("lib/a.dart", "docs/guide.md", "docs/contract.json", "docs/test.py"):
                (root / name).write_text("fixture")
            module = {"id": "one", "owner": "team", "source_roots": ["lib/a.dart"],
                "documentation": ["docs/guide.md"], "tests": ["docs/test.py"],
                "contracts": ["docs/contract.json"], "external_gates": ["physical device"]}
            (root / "docs/MODULE_COVERAGE.json").write_text(json.dumps({"schema_version": 1, "modules": [module]}))
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            self.assertEqual(inspect_repository(root)["tracked_source_count"], 1)
            (root / "lib/unowned.dart").write_text("new source")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            with self.assertRaisesRegex(CoverageError, "unowned"):
                inspect_repository(root)


class RepositoryCoverageTest(unittest.TestCase):
    def test_actual_checkout_has_no_unowned_source(self):
        root = Path(__file__).resolve().parents[2]
        report = inspect_repository(root)
        self.assertGreaterEqual(report["module_count"], 26)
        self.assertIn("plugins/hepta-glasses-agent-os/.mcp.json", report["ownership"])
        self.assertEqual(report["ownership"]["plugins/hepta-glasses-agent-os/.mcp.json"], ["agent-os-plugin"])


if __name__ == "__main__":
    unittest.main()
