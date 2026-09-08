from __future__ import annotations

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
COCOAPODS_TOOL = ROOT / "tools/native/refresh_cocoapods_lock.py"


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
    def test_dependabot_uses_only_officially_supported_values(self) -> None:
        contract = json.loads(ECOSYSTEM_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(contract["retrieved_at"], "2026-09-08")
        self.assertEqual(
            contract["source"],
            "https://docs.github.com/en/code-security/reference/"
            "supply-chain-security/supported-ecosystems-and-repositories",
        )
        supported = contract["yaml_values"]
        self.assertEqual(supported, sorted(set(supported)))
        self.assertNotIn("cocoapods", supported)

        text = DEPENDABOT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("version: 2\n"))
        observed = _dependabot_entries(text)
        self.assertTrue(set(observed).issubset(set(supported)))
        self.assertEqual(
            observed,
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
            [sys.executable, str(COCOAPODS_TOOL), "--check"],
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

        source = COCOAPODS_TOOL.read_text(encoding="utf-8")
        for phrase in (
            "HEPTA_COCOAPODS_UPDATE_APPROVED",
            "named non-main review branch",
            'path != "ios/Podfile.lock"',
            "open an ordinary exact-head pull request",
        ):
            self.assertIn(phrase, source)

    def test_lockfiles_and_operator_guide_exist(self) -> None:
        for relative in (
            "pubspec.lock",
            "android/gradle/wrapper/gradle-wrapper.properties",
            "ios/Podfile.lock",
            "contracts/dependabot-supported-ecosystems-v1.json",
            "docs/development/DEPENDENCY_SECURITY.md",
            "tools/native/refresh_cocoapods_lock.py",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 0, relative)
        guide = GUIDE.read_text(encoding="utf-8")
        for phrase in (
            "three supported ecosystems",
            "Dependabot does not support CocoaPods",
            "No dependency pull request is auto-merged",
            "all seven canonical jobs",
            "exact-head source Artifact",
            "signed mobile binaries",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
