from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ROOT / ".github/dependabot.yml"
ECOSYSTEM_CONTRACT = ROOT / "contracts/dependabot-supported-ecosystems-v1.json"
GUIDE = ROOT / "docs/development/DEPENDENCY_SECURITY.md"
POLICY_TOOL = ROOT / "tools/native/dependency_update_policy.py"
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _load_policy_module():
    spec = importlib.util.spec_from_file_location("dependency_update_policy", POLICY_TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load dependency update policy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = _load_policy_module()


def _dependabot_entries(text: str) -> dict[str, dict[str, str]]:
    parts = re.split(r"(?m)^  - package-ecosystem: ", text)[1:]
    observed: dict[str, dict[str, str]] = {}
    for part in parts:
        ecosystem, _, body = part.partition("\n")
        if ecosystem in observed:
            raise AssertionError(f"duplicate ecosystem: {ecosystem}")
        fields = {
            "directory": re.search(r'(?m)^    directory: "([^"]+)"$', body),
            "interval": re.search(r"(?m)^      interval: ([a-z]+)$", body),
            "timezone": re.search(r'(?m)^      timezone: "([^"]+)"$', body),
            "limit": re.search(
                r"(?m)^    open-pull-requests-limit: ([0-9]+)$", body
            ),
        }
        missing = [name for name, match in fields.items() if match is None]
        if missing:
            raise AssertionError(f"{ecosystem} missing fields: {missing}")
        observed[ecosystem] = {
            name: match.group(1) for name, match in fields.items()
        }
    return observed


class DependencyAutomationTests(unittest.TestCase):
    def test_dependabot_uses_exact_repository_applicable_values(self) -> None:
        contract = json.loads(ECOSYSTEM_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["official_source"],
            {
                "repository": "github/docs",
                "commit": "062800c32b5d12ccae18d1a4a542e94069d827f8",
                "path": "data/reusables/dependabot/supported-package-managers.md",
                "retrieved_at": "2026-09-08",
            },
        )
        self.assertEqual(
            contract["configured_ecosystems"],
            ["github-actions", "gradle", "pub"],
        )
        self.assertEqual(contract["unsupported_repository_managers"], ["cocoapods"])
        self.assertGreaterEqual(contract["minimum_official_value_count"], 20)

        text = DEPENDABOT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("version: 2\n"))
        self.assertEqual(
            _dependabot_entries(text),
            {
                "github-actions": {
                    "directory": "/",
                    "interval": "weekly",
                    "timezone": "Asia/Singapore",
                    "limit": "5",
                },
                "pub": {
                    "directory": "/",
                    "interval": "weekly",
                    "timezone": "Asia/Singapore",
                    "limit": "5",
                },
                "gradle": {
                    "directory": "/android",
                    "interval": "weekly",
                    "timezone": "Asia/Singapore",
                    "limit": "5",
                },
            },
        )

    def test_official_table_parser_is_external_and_fail_closed(self) -> None:
        fixture = """Package manager | YAML value | Version updates
GitHub Actions | `github-actions` | yes
Gradle | `gradle` | yes
Pub | `pub` | yes
Swift | `swift` | yes
"""
        self.assertEqual(
            POLICY.parse_official_values(fixture),
            {"github-actions", "gradle", "pub", "swift"},
        )
        with self.assertRaises(POLICY.DependencyPolicyError):
            POLICY.parse_official_values("github-actions gradle pub")

        source = POLICY_TOOL.read_text(encoding="utf-8")
        self.assertIn('_OFFICIAL_REPOSITORY = "github/docs"', source)
        self.assertIn(
            '_OFFICIAL_PATH = "data/reusables/dependabot/'
            'supported-package-managers.md"',
            source,
        )
        self.assertIn("build_opener(_NoRedirect())", source)
        self.assertIn("official-source read failed closed", source)
        self.assertNotIn("raw.githubusercontent.com/{repository}", source)

        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "python3 tools/native/dependency_update_policy.py "
            "--verify-dependabot-official",
            workflow,
        )

    def test_dependency_updates_cannot_self_promote(self) -> None:
        text = DEPENDABOT.read_text(encoding="utf-8").casefold()
        for prohibited in (
            "cocoapods",
            "auto-merge",
            "automerge",
            "target-branch:",
            "insecure-external-code-execution: allow",
        ):
            self.assertNotIn(prohibited, text)
        self.assertEqual(text.count("open-pull-requests-limit: 5"), 3)

    def test_cocoapods_boundary_is_actionable_and_fail_closed(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(POLICY_TOOL), "--check-cocoapods"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["mode"], "local-flutter-pod-only")
        self.assertEqual(result["external_registry_pods"], 0)
        self.assertEqual(result["external_sources"], ["Flutter"])
        self.assertEqual(result["ci_lock_enforcement"], "pod install --deployment")
        self.assertFalse(result["auto_commit"])
        self.assertFalse(result["auto_push"])
        self.assertFalse(result["auto_merge"])

        source = POLICY_TOOL.read_text(encoding="utf-8")
        for phrase in (
            "HEPTA_COCOAPODS_UPDATE_APPROVED",
            "named non-main review branch",
            'path != "ios/Podfile.lock"',
            "open an ordinary exact-head pull request",
            '"--untracked-files=all"',
        ):
            self.assertIn(phrase, source)

    def test_lockfiles_and_operator_guide_exist(self) -> None:
        for relative in (
            "pubspec.lock",
            "android/gradle/wrapper/gradle-wrapper.properties",
            "ios/Podfile.lock",
            "contracts/dependabot-supported-ecosystems-v1.json",
            "docs/development/DEPENDENCY_SECURITY.md",
            "tools/native/dependency_update_policy.py",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 0, relative)
        guide = GUIDE.read_text(encoding="utf-8")
        for phrase in (
            "three supported ecosystems",
            "Dependabot does not support CocoaPods",
            "immutable `github/docs` commit",
            "No dependency pull request is auto-merged",
            "all seven canonical jobs",
            "exact-head source Artifact",
            "signed mobile binaries",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
