from __future__ import annotations

import ast
import importlib.util
import json
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

    def test_complete_dependabot_object_is_bound_before_extraction(self) -> None:
        source = POLICY_TOOL.read_text(encoding="utf-8")
        self.assertIn("_APPROVED_DEPENDABOT_CONFIG_SHA256", source)
        self.assertIn("complete Dependabot object differs", source)
        self.assertLess(
            source.index("digest != _APPROVED_DEPENDABOT_CONFIG_SHA256"),
            source.index("_CANONICAL_ECOSYSTEM.findall(text)"),
        )
        expected = POLICY._APPROVED_DEPENDABOT_CONFIG_SHA256
        self.assertEqual(
            expected,
            "c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5",
        )
        self.assertEqual(
            POLICY.hashlib.sha256(DEPENDABOT.read_bytes()).hexdigest(),
            expected,
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
        self.assertNotIn("Authorization", source)

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

    def test_cocoapods_boundary_is_closed_world(self) -> None:
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
        self.assertEqual(result["schema_version"], 4)
        self.assertEqual(
            result["mode"], "closed-world-local-flutter-pod-only"
        )
        self.assertFalse(result["repository_executes_update"])
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
                    "b8fb28c09bba09251ad35656ee8a6bab08dbff76"
                ),
            },
        )
        self.assertRegex(
            result["podfile_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            result["podfile_lock_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertFalse(result["auto_commit"])
        self.assertFalse(result["auto_push"])
        self.assertFalse(result["auto_merge"])

    def test_external_update_contract_is_machine_readable_and_nonexecuting(
        self,
    ) -> None:
        direct = POLICY.emit_cocoapods_update_contract()
        completed = subprocess.run(
            [
                sys.executable,
                str(POLICY_TOOL),
                "--emit-cocoapods-update-contract",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        cli = json.loads(completed.stdout)
        self.assertEqual(cli, direct)
        self.assertEqual(
            direct["operation"],
            "external-hermetic-cocoapods-lock-refresh",
        )
        self.assertFalse(direct["repository_executes_generator"])
        self.assertFalse(direct["repository_executes_flutter"])
        self.assertFalse(direct["repository_executes_git"])
        self.assertEqual(
            direct["allowed_repository_changes"], ["ios/Podfile.lock"]
        )
        self.assertEqual(
            direct["required_external_evidence"],
            [
                "immutable_environment_digest",
                "ruby_interpreter_sha256",
                "cocoapods_gem_set_digest",
                "flutter_sdk_digest",
                "network_dependency_provenance",
                "generated_lock_sha256",
                "invocation_transcript_digest",
            ],
        )
        self.assertTrue(direct["passed"])
        self.assertFalse(direct["auto_commit"])
        self.assertFalse(direct["auto_push"])
        self.assertFalse(direct["auto_merge"])

    def test_policy_has_no_child_process_or_local_refresh_path(self) -> None:
        source = POLICY_TOOL.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertFalse({"subprocess", "shutil", "os"} & imported)
        for forbidden in (
            "--refresh-cocoapods",
            "HEPTA_COCOAPODS_UPDATE_APPROVED",
            "resolve_cocoapods_generator",
            "_run_generator_version",
            "_verify_same_generator",
            "shutil.which",
            "subprocess.run",
        ):
            self.assertNotIn(forbidden, source)

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

    def test_inspection_rejects_origin_source_checksum_version_and_children_drift(
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
        version_drift = LOCKFILE_TEXT.replace(
            "COCOAPODS: 1.17.0", "COCOAPODS: 99.0.0"
        )
        child_drift = LOCKFILE_TEXT.replace(
            "  - Flutter (1.0.0)",
            "  - Flutter (1.0.0):\n    - Flutter",
        )
        for name, candidate in {
            "origin": origin_drift,
            "source": source_drift,
            "checksum": checksum_drift,
            "version": version_drift,
            "children": child_drift,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_fixture(lockfile=candidate)

    def test_workflow_parser_rejects_textual_decoys(self) -> None:
        exact = WORKFLOW_TEXT
        comment_only = exact.replace(
            "      - name: Install locked CocoaPods dependencies\n"
            "        run: |\n"
            "          cd ios\n"
            "          pod install --deployment\n",
            "      # pod install --deployment\n",
        )
        echo_only = exact.replace(
            "          cd ios\n          pod install --deployment",
            "          echo 'cd ios && pod install --deployment'",
        )
        conditional = exact.replace(
            "      - name: Install locked CocoaPods dependencies\n",
            "      - name: Install locked CocoaPods dependencies\n"
            "        if: ${{ false }}\n",
        )
        wrong_job = exact.replace(
            "      - name: Install locked CocoaPods dependencies",
            "  unrelated:\n"
            "      - name: Install locked CocoaPods dependencies",
            1,
        )
        duplicate = exact.replace(
            "      - name: Install locked CocoaPods dependencies\n"
            "        run: |\n"
            "          cd ios\n"
            "          pod install --deployment\n",
            "      - name: Install locked CocoaPods dependencies\n"
            "        run: |\n"
            "          cd ios\n"
            "          pod install --deployment\n"
            "      - name: Install locked CocoaPods dependencies\n"
            "        run: |\n"
            "          cd ios\n"
            "          pod install --deployment\n",
        )
        for name, candidate in {
            "comment": comment_only,
            "echo": echo_only,
            "conditional": conditional,
            "wrong-job": wrong_job,
            "duplicate": duplicate,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(POLICY.DependencyPolicyError):
                    self._inspect_fixture(workflow=candidate)

    def test_workflow_complete_object_drift_is_rejected(self) -> None:
        changed = WORKFLOW_TEXT.replace(
            "name: hepta-glasses-ci",
            "name: hepta-glasses-ci-drift",
            1,
        )
        with self.assertRaises(POLICY.DependencyPolicyError):
            self._inspect_fixture(
                workflow=changed,
                approved_workflow_sha=POLICY._APPROVED_WORKFLOW_GIT_BLOB_SHA1,
            )

    def test_lockfiles_policy_and_operator_guide_exist(self) -> None:
        for relative in (
            "pubspec.lock",
            "android/gradle/wrapper/gradle-wrapper.properties",
            "ios/Podfile.lock",
            "contracts/dependabot-supported-ecosystems-v1.json",
            "docs/development/DEPENDENCY_SECURITY.md",
            "docs/development/DEPENDABOT_CONFIG_CUSTODY.md",
            "tools/native/dependency_update_policy.py",
            "tools/native/dependabot_config_custody.py",
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
            "--emit-cocoapods-update-contract",
            "closed-world",
            "PODS",
            "DEPENDENCIES",
            "EXTERNAL SOURCES",
            "SPEC CHECKSUMS",
            "repository never executes",
            "external hermetic",
            "No dependency pull request is auto-merged",
            "all seven canonical jobs",
            "exact-head source Artifact",
            "signed mobile binaries",
        ):
            self.assertIn(stable_interface, guide)


PODFILE_TEXT = (
    ROOT / "ios/Podfile"
).read_text(encoding="utf-8")
LOCKFILE_TEXT = (
    ROOT / "ios/Podfile.lock"
).read_text(encoding="utf-8")
WORKFLOW_TEXT = WORKFLOW.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
