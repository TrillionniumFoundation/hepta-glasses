from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT = ROOT / ".github/dependabot.yml"
ECOSYSTEM_CONTRACT = ROOT / "contracts/dependabot-supported-ecosystems-v1.json"
GUIDE = ROOT / "docs/development/DEPENDENCY_SECURITY.md"
POLICY_TOOL = ROOT / "tools/native/dependency_update_policy.py"
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _load_policy_module():
    spec = importlib.util.spec_from_file_location(
        "dependency_update_policy", POLICY_TOOL
    )
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
            "directory": re.search(
                r'(?m)^    directory: "([^"]+)"$', body
            ),
            "interval": re.search(
                r"(?m)^      interval: ([a-z]+)$", body
            ),
            "timezone": re.search(
                r'(?m)^      timezone: "([^"]+)"$', body
            ),
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
    def _inspect_fixture(
        self,
        *,
        podfile: str | None = None,
        lockfile: str | None = None,
        workflow: str | None = None,
        approved_workflow_sha: str | None = None,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            podfile_path = root / "Podfile"
            lockfile_path = root / "Podfile.lock"
            workflow_path = root / "ci.yml"
            podfile_path.write_text(
                PODFILE_TEXT if podfile is None else podfile,
                encoding="utf-8",
            )
            lockfile_path.write_text(
                LOCKFILE_TEXT if lockfile is None else lockfile,
                encoding="utf-8",
            )
            workflow_text = (
                WORKFLOW_TEXT if workflow is None else workflow
            )
            workflow_path.write_text(workflow_text, encoding="utf-8")
            expected_sha = (
                POLICY._git_blob_sha1(workflow_path.read_bytes())
                if approved_workflow_sha is None
                else approved_workflow_sha
            )
            with (
                patch.object(POLICY, "PODFILE", podfile_path),
                patch.object(POLICY, "LOCKFILE", lockfile_path),
                patch.object(POLICY, "WORKFLOW", workflow_path),
                patch.object(
                    POLICY,
                    "_APPROVED_WORKFLOW_GIT_BLOB_SHA1",
                    expected_sha,
                ),
            ):
                return POLICY.inspect_cocoapods()

    def test_dependabot_uses_exact_repository_applicable_values(self) -> None:
        contract = json.loads(
            ECOSYSTEM_CONTRACT.read_text(encoding="utf-8")
        )
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["official_source"],
            {
                "repository": "github/docs",
                "commit": "062800c32b5d12ccae18d1a4a542e94069d827f8",
                "path": (
                    "data/reusables/dependabot/"
                    "supported-package-managers.md"
                ),
                "retrieved_at": "2026-09-08",
            },
        )
        self.assertEqual(
            contract["configured_ecosystems"],
            ["github-actions", "gradle", "pub"],
        )
        self.assertEqual(
            contract["unsupported_repository_managers"], ["cocoapods"]
        )
        self.assertGreaterEqual(
            contract["minimum_official_value_count"], 20
        )

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
        self.assertIn(
            '_OFFICIAL_REPOSITORY = "github/docs"', source
        )
        self.assertIn(
            '_OFFICIAL_PATH = "data/reusables/dependabot/'
            'supported-package-managers.md"',
            source,
        )
        self.assertIn("build_opener(_NoRedirect())", source)
        self.assertIn("official-source read failed closed", source)
        self.assertNotIn(
            "raw.githubusercontent.com/{repository}", source
        )

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
        self.assertEqual(
            text.count("open-pull-requests-limit: 5"), 3
        )

    def test_cocoapods_boundary_is_closed_world_and_actionable(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(POLICY_TOOL),
                "--check-cocoapods",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["mode"], "closed-world-local-flutter-pod-only"
        )
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["lock_pods"], ["Flutter"])
        self.assertEqual(result["lock_dependencies"], ["Flutter"])
        self.assertEqual(result["lock_spec_checksums"], ["Flutter"])
        self.assertEqual(result["external_registry_pods"], 0)
        self.assertEqual(result["registry_pod_roots"], [])
        self.assertEqual(result["external_sources"], ["Flutter"])
        self.assertEqual(result["cocoapods_version"], "1.17.0")
        self.assertEqual(
            result["approved_cocoapods_version"], "1.17.0"
        )
        self.assertEqual(
            result["ci_lock_enforcement"],
            {
                "job": "ios-native",
                "step": "Install locked CocoaPods dependencies",
                "command": "cd ios && pod install --deployment",
                "git_blob_sha1": (
                    "7624aaf9cafa5bfef6b55f91d714bf50bb5c92ee"
                ),
            },
        )
        self.assertRegex(
            result["podfile_sha256"], r"^[0-9a-f]{64}$"
        )
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
            "_APPROVED_PODFILE_SHA256",
            "_APPROVED_WORKFLOW_GIT_BLOB_SHA1",
            "_APPROVED_COCOAPODS_VERSION",
            "parse_cocoapods_lock",
            "parse_canonical_ios_lock_step",
            '"external_registry_pods": len(registry_roots)',
            'f"_{_APPROVED_COCOAPODS_VERSION}_"',
        ):
            self.assertIn(phrase, source)
        self.assertNotIn('_POD_DECLARATION = re.compile', source)
        self.assertNotIn(
            '"pod install --deployment" not in workflow', source
        )

    def test_podfile_closed_world_rejects_ruby_evasions(self) -> None:
        variants = {
            "parenthesized": PODFILE_TEXT + '\npod("AFNetworking")\n',
            "spaced-parenthesized": (
                PODFILE_TEXT + "\npod ('AFNetworking')\n"
            ),
            "alias-variable": (
                PODFILE_TEXT
                + "\ninstaller = method(:pod)\n"
                + "installer.call('AFNetworking')\n"
            ),
            "helper-driven": (
                PODFILE_TEXT
                + "\ndef install_external\n"
                + "  pod 'AFNetworking'\n"
                + "end\ninstall_external\n"
            ),
            "source-change": (
                PODFILE_TEXT
                + "\nsource 'https://cdn.cocoapods.org/'\n"
            ),
        }
        for name, candidate in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_fixture(podfile=candidate)

    def test_lock_parser_derives_registry_pods(self) -> None:
        registry_lock = """PODS:
  - AFNetworking (4.0.1)
  - Flutter (1.0.0)

DEPENDENCIES:
  - AFNetworking
  - Flutter (from `Flutter`)

EXTERNAL SOURCES:
  Flutter:
    :path: Flutter

SPEC CHECKSUMS:
  AFNetworking: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  Flutter: 71a624a5bc0c04062bf19101d501e466baf2fb47

PODFILE CHECKSUM: 9c46fd01abff66081b39f5fa5767b3f1d0b11d76

COCOAPODS: 1.17.0
"""
        graph = POLICY.parse_cocoapods_lock(registry_lock)
        self.assertEqual(
            graph["registry_pod_roots"], ["AFNetworking"]
        )
        self.assertEqual(graph["external_registry_pods"], 1)
        with self.assertRaises(POLICY.DependencyPolicyError):
            self._inspect_fixture(lockfile=registry_lock)

    def test_lock_parser_rejects_unexpected_transitive_pods(self) -> None:
        transitive_lock = """PODS:
  - AFNetworking (4.0.1):
    - CFNetwork
  - CFNetwork (1.0.0)
  - Flutter (1.0.0)

DEPENDENCIES:
  - AFNetworking
  - Flutter (from `Flutter`)

EXTERNAL SOURCES:
  Flutter:
    :path: Flutter

SPEC CHECKSUMS:
  AFNetworking: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  CFNetwork: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  Flutter: 71a624a5bc0c04062bf19101d501e466baf2fb47

PODFILE CHECKSUM: 9c46fd01abff66081b39f5fa5767b3f1d0b11d76

COCOAPODS: 1.17.0
"""
        graph = POLICY.parse_cocoapods_lock(transitive_lock)
        self.assertEqual(
            graph["registry_pod_roots"],
            ["AFNetworking", "CFNetwork"],
        )
        self.assertEqual(graph["external_registry_pods"], 2)
        with self.assertRaises(POLICY.DependencyPolicyError):
            self._inspect_fixture(lockfile=transitive_lock)

    def test_lock_parser_rejects_duplicate_or_malformed_sections(self) -> None:
        duplicate = LOCKFILE_TEXT.replace(
            "\nEXTERNAL SOURCES:",
            "\nDEPENDENCIES:\n"
            "  - Flutter (from `Flutter`)\n\n"
            "EXTERNAL SOURCES:",
        )
        malformed = LOCKFILE_TEXT.replace(
            "  Flutter: 71a624a5bc0c04062bf19101d501e466baf2fb47",
            "    Flutter: not-a-digest",
        )
        unexpected_section = LOCKFILE_TEXT.replace(
            "\nSPEC CHECKSUMS:",
            "\nSPEC REPOS:\n  trunk:\n    - Flutter\n\n"
            "SPEC CHECKSUMS:",
        )
        for name, candidate in {
            "duplicate": duplicate,
            "malformed": malformed,
            "unexpected": unexpected_section,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.parse_cocoapods_lock(candidate)

    def test_lock_parser_rejects_cross_section_mismatches(self) -> None:
        missing_checksum = LOCKFILE_TEXT.replace(
            "  Flutter: 71a624a5bc0c04062bf19101d501e466baf2fb47\n",
            "",
        )
        absent_dependency_pod = LOCKFILE_TEXT.replace(
            "  - Flutter (from `Flutter`)",
            "  - Ghost (from `Flutter`)",
        )
        absent_child_pod = LOCKFILE_TEXT.replace(
            "  - Flutter (1.0.0)",
            "  - Flutter (1.0.0):\n    - Ghost",
        )
        for name, candidate in {
            "missing-checksum": missing_checksum,
            "dependency-not-in-pods": absent_dependency_pod,
            "child-not-in-pods": absent_child_pod,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.parse_cocoapods_lock(candidate)

    def test_inspection_rejects_origin_source_checksum_and_children_drift(
        self,
    ) -> None:
        origin_drift = LOCKFILE_TEXT.replace(
            "Flutter (from `Flutter`)",
            "Flutter (from `https://evil.example/pod`)",
        )
        source_drift = LOCKFILE_TEXT.replace(
            ":path: Flutter", ":git: https://evil.example/Flutter.git"
        )
        checksum_drift = LOCKFILE_TEXT.replace(
            "71a624a5bc0c04062bf19101d501e466baf2fb47",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        child_drift = LOCKFILE_TEXT.replace(
            "  - Flutter (1.0.0)",
            "  - Flutter (1.0.0):\n    - Flutter",
        )
        version_drift = LOCKFILE_TEXT.replace(
            "COCOAPODS: 1.17.0", "COCOAPODS: 99.0.0"
        )
        for name, candidate in {
            "origin": origin_drift,
            "source": source_drift,
            "checksum": checksum_drift,
            "children": child_drift,
            "generator-version": version_drift,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_fixture(lockfile=candidate)

    def test_workflow_parser_rejects_textual_decoys(self) -> None:
        decoys = {
            "comment": """name: decoy
jobs:
  ios-native:
    steps:
      # pod install --deployment
      - run: true
""",
            "echo": """name: decoy
jobs:
  ios-native:
    steps:
      - run: echo 'pod install --deployment'
""",
            "false-branch": """name: decoy
jobs:
  ios-native:
    steps:
      - name: Install locked CocoaPods dependencies
        if: ${{ false }}
        run: |
          cd ios
          pod install --deployment
""",
            "unrelated-job": """name: decoy
jobs:
  diagnostics:
    steps:
      - name: Install locked CocoaPods dependencies
        run: |
          cd ios
          pod install --deployment
""",
        }
        for name, candidate in decoys.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.parse_canonical_ios_lock_step(candidate)

    def test_workflow_full_object_binding_rejects_unrelated_drift(self) -> None:
        changed = WORKFLOW_TEXT + "\n# unrelated but unreviewed change\n"
        with self.assertRaises(POLICY.DependencyPolicyError):
            self._inspect_fixture(
                workflow=changed,
                approved_workflow_sha=(
                    "7624aaf9cafa5bfef6b55f91d714bf50bb5c92ee"
                ),
            )

    def test_generator_selector_rejects_mismatched_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pod"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            mismatch = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="99.0.0\n", stderr=""
            )
            with (
                patch.object(POLICY.shutil, "which", return_value=str(executable)),
                patch.object(POLICY.subprocess, "run", return_value=mismatch) as run,
            ):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    POLICY.resolve_cocoapods_generator()
            self.assertEqual(
                run.call_args.args[0],
                [str(executable.resolve()), "_1.17.0_", "--version"],
            )

    def test_generator_identity_binds_path_digest_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pod"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            matched = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="1.17.0\n", stderr=""
            )
            with (
                patch.object(POLICY.shutil, "which", return_value=str(executable)),
                patch.object(POLICY.subprocess, "run", return_value=matched),
            ):
                identity = POLICY.resolve_cocoapods_generator()
            self.assertEqual(identity["path"], str(executable.resolve()))
            self.assertEqual(identity["version"], "1.17.0")
            self.assertEqual(identity["selector"], "_1.17.0_")
            self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")

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
        for stable_interface in (
            "three supported ecosystems",
            "`github/docs` repository",
            "--verify-dependabot-official",
            "Dependabot does not support CocoaPods",
            "--check-cocoapods",
            "--refresh-cocoapods",
            "closed-world",
            "PODS",
            "DEPENDENCIES",
            "EXTERNAL SOURCES",
            "SPEC CHECKSUMS",
            "CocoaPods `1.17.0`",
            "Git blob SHA-1",
            "No dependency pull request is auto-merged",
            "all seven canonical jobs",
            "exact-head source Artifact",
            "signed mobile binaries",
        ):
            self.assertIn(stable_interface, guide)


PODFILE_TEXT = (ROOT / "ios/Podfile").read_text(encoding="utf-8")
LOCKFILE_TEXT = (ROOT / "ios/Podfile.lock").read_text(encoding="utf-8")
WORKFLOW_TEXT = WORKFLOW.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
