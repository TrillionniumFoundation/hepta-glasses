from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ROOT / ".github/dependabot.yml"
GUIDE = ROOT / "docs/development/DEPENDENCY_SECURITY.md"


class DependencyAutomationTests(unittest.TestCase):
    def test_dependabot_covers_every_supported_dependency_ecosystem(self) -> None:
        text = DEPENDABOT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("version: 2\n"))
        parts = re.split(r"(?m)^  - package-ecosystem: ", text)[1:]
        observed: dict[str, dict[str, str]] = {}
        for part in parts:
            ecosystem, _, body = part.partition("\n")
            self.assertNotIn(ecosystem, observed)
            directory = re.search(r'(?m)^    directory: "([^\"]+)"$', body)
            interval = re.search(r"(?m)^      interval: ([a-z]+)$", body)
            timezone = re.search(r'(?m)^      timezone: "([^\"]+)"$', body)
            limit = re.search(r"(?m)^    open-pull-requests-limit: ([0-9]+)$", body)
            self.assertIsNotNone(directory, ecosystem)
            self.assertIsNotNone(interval, ecosystem)
            self.assertIsNotNone(timezone, ecosystem)
            self.assertIsNotNone(limit, ecosystem)
            observed[ecosystem] = {
                "directory": directory.group(1),
                "interval": interval.group(1),
                "timezone": timezone.group(1),
                "limit": limit.group(1),
            }

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
                "cocoapods": {
                    "directory": "/ios",
                    "interval": "weekly",
                    "timezone": "Asia/Singapore",
                    "limit": "5",
                },
            },
        )

    def test_dependency_updates_cannot_self_promote(self) -> None:
        text = DEPENDABOT.read_text(encoding="utf-8").casefold()
        for prohibited in (
            "auto-merge",
            "automerge",
            "target-branch:",
            "insecure-external-code-execution: allow",
        ):
            self.assertNotIn(prohibited, text)
        self.assertEqual(text.count("open-pull-requests-limit: 5"), 4)

    def test_lockfiles_and_operator_guide_exist(self) -> None:
        for relative in (
            "pubspec.lock",
            "android/gradle/wrapper/gradle-wrapper.properties",
            "ios/Podfile.lock",
            "docs/development/DEPENDENCY_SECURITY.md",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(path.stat().st_size, 0, relative)
        guide = GUIDE.read_text(encoding="utf-8")
        for phrase in (
            "No dependency pull request is auto-merged",
            "all seven canonical jobs",
            "exact-head source Artifact",
            "signed mobile binaries",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
