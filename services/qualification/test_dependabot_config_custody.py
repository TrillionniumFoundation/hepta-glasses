from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/native/dependabot_config_custody.py"
CONFIG = ROOT / ".github/dependabot.yml"
GUIDE = ROOT / "docs/development/DEPENDABOT_CONFIG_CUSTODY.md"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "dependabot_config_custody", TOOL
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load Dependabot config custody tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CUSTODY = _load_tool()
CANONICAL = CONFIG.read_text(encoding="utf-8")


class DependabotConfigCustodyTests(unittest.TestCase):
    def test_complete_config_object_is_bound(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(TOOL), "--check"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["size_bytes"], 749)
        self.assertEqual(
            result["config_sha256"],
            "c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5",
        )
        self.assertEqual(
            result["ecosystems"], ["github-actions", "pub", "gradle"]
        )
        self.assertEqual(result["directories"], ["/", "/", "/android"])
        self.assertEqual(
            result["schedule_times"], ["03:00", "03:15", "03:30"]
        )
        self.assertEqual(result["timezone"], "Asia/Singapore")
        self.assertEqual(result["open_pull_request_limit_each"], 5)
        self.assertFalse(result["auto_merge"])
        self.assertFalse(result["target_branch_override"])
        self.assertFalse(result["external_registries"])

    def test_valid_yaml_alternate_ecosystem_syntax_cannot_evade_custody(self) -> None:
        quoted_extra = (
            CANONICAL
            + '\nupdates-extra:\n'
            + '  - package-ecosystem: "npm"\n'
            + '    directory: "/web"\n'
            + '    schedule:\n'
            + '      interval: weekly\n'
        )
        quoted_replacement = CANONICAL.replace(
            "package-ecosystem: gradle",
            'package-ecosystem: "npm"',
        )
        anchored = CANONICAL.replace(
            "updates:\n",
            "updates: &updates\n",
            1,
        )
        merged = CANONICAL.replace(
            "  - package-ecosystem: gradle",
            "  - <<: *shared\n    package-ecosystem: gradle",
            1,
        )
        for name, candidate in {
            "quoted-extra": quoted_extra,
            "quoted-replacement": quoted_replacement,
            "anchor": anchored,
            "merge-key": merged,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(CUSTODY.DependabotConfigError):
                    CUSTODY.verify_text(candidate)

    def test_authority_and_schedule_drift_fail_closed(self) -> None:
        variants = {
            "target-branch": CANONICAL.replace(
                '    directory: "/android"\n',
                '    directory: "/android"\n    target-branch: "main"\n',
            ),
            "registry": CANONICAL.replace(
                "updates:\n", "registries:\n  private: {}\n\nupdates:\n", 1
            ),
            "limit": CANONICAL.replace(
                "open-pull-requests-limit: 5",
                "open-pull-requests-limit: 50",
                1,
            ),
            "timezone": CANONICAL.replace(
                "Asia/Singapore", "UTC", 1
            ),
            "cocoapods": CANONICAL.replace(
                "package-ecosystem: gradle",
                "package-ecosystem: cocoapods",
            ),
            "swift-substitution": CANONICAL.replace(
                "package-ecosystem: gradle",
                "package-ecosystem: swift",
            ),
        }
        for name, candidate in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(CUSTODY.DependabotConfigError):
                    CUSTODY.verify_text(candidate)

    def test_encoding_shape_drift_fails_closed(self) -> None:
        variants = {
            "bom": "\ufeff" + CANONICAL,
            "crlf": CANONICAL.replace("\n", "\r\n"),
            "tab": CANONICAL.replace("updates:", "\tupdates:", 1),
            "trailing-space": CANONICAL.replace("version: 2", "version: 2 "),
            "missing-final-lf": CANONICAL.rstrip("\n"),
            "double-final-lf": CANONICAL + "\n",
        }
        for name, candidate in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(CUSTODY.DependabotConfigError):
                    CUSTODY.verify_text(candidate)

    def test_operator_guide_preserves_exact_object_boundary(self) -> None:
        guide = GUIDE.read_text(encoding="utf-8")
        for phrase in (
            "complete 749-byte configuration object",
            "c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5",
            "Quoted YAML scalars",
            "anchors, aliases, and merge keys",
            "No configuration movement inherits",
            "seven canonical jobs",
            "exact-head Artifact",
            "eligible non-pusher",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
