"""Boundary-policy regressions; all fixtures use inert text, not real secrets."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import validate_repository as repository
from tools.server_provider_boundary import CONTRACT, ServerProviderBoundary, read_regular

ROOT = Path(__file__).resolve().parents[2]
PROVIDER = "services/model_gateway/responses_provider.py"
WIRE = "services/model_gateway/test_responses_provider.py"


class ServerProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = json.loads((ROOT / CONTRACT).read_text())
        for name in (PROVIDER, WIRE):
            self.write(name, (ROOT / name).read_bytes())
        self.save()
        self.write("lib/services/evenai.dart", b"// inert boundary fixture\n")

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def save(self):
        self.write(CONTRACT, (json.dumps(self.contract, indent=2) + "\n").encode())

    def validate(self):
        with patch.object(repository, "ROOT", self.root):
            repository.validate_boundaries()

    def refresh_digest(self, path):
        row = next(r for r in self.contract["entries"] if r["path"] == path)
        row["sha256"] = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
        self.save()

    def endpoint(self, index=-1):
        # Take literal fixture markers from the scanner, not from a live service.
        return repository.FORBIDDEN_PATTERNS["direct provider endpoint"].pattern.split("|")[index].replace(r"\.", ".")

    def test_exact_published_cloud_pair_passes(self):
        self.validate()

    def test_original_scanner_reproduces_all_three_reported_findings(self):
        found = []
        for path in (PROVIDER, WIRE):
            text = (self.root / path).read_text()
            found.extend((label, path) for label, pattern in repository.FORBIDDEN_PATTERNS.items() if pattern.search(text))
        self.assertEqual(set(found), {("direct provider endpoint", PROVIDER),
                                     ("direct provider endpoint", WIRE), ("provider key name", WIRE)})

    def test_any_change_to_registered_source_requires_new_digest(self):
        for path in (PROVIDER, WIRE):
            with self.subTest(path=path):
                original = (self.root / path).read_bytes()
                self.write(path, original + b"\n# changed\n")
                with self.assertRaisesRegex(AssertionError, "digest_mismatch"):
                    self.validate()
                self.write(path, original)

    def test_unregistered_cloud_adapter_still_rejected(self):
        self.write("services/model_gateway/other.py", f"HOST = {self.endpoint()!r}\n".encode())
        with self.assertRaisesRegex(AssertionError, "direct provider endpoint"):
            self.validate()

    def test_same_bytes_copied_into_consumer_are_not_exempt(self):
        for root, extension in (("lib", ".dart"), ("android", ".kt"), ("ios", ".swift"),
                                ("adapters", ".py"), ("plugins", ".py"), ("services", ".py")):
            with self.subTest(root=root):
                file = self.write(root + "/copied" + extension, (self.root / PROVIDER).read_bytes())
                with self.assertRaisesRegex(AssertionError, "direct provider endpoint"):
                    self.validate()
                file.unlink()

    def test_inert_key_name_outside_registered_test_is_rejected(self):
        marker = repository.FORBIDDEN_PATTERNS["provider key name"].pattern.split("|")[-1]
        self.write("services/qualification/other_test.py", f"VALUE = {marker!r}\n".encode())
        with self.assertRaisesRegex(AssertionError, "provider key name"):
            self.validate()

    def test_transport_never_gets_key_name_exception_even_if_digest_updated(self):
        marker = repository.FORBIDDEN_PATTERNS["provider key name"].pattern.split("|")[-1]
        data = (self.root / PROVIDER).read_bytes() + f"\nVALUE = {marker!r}\n".encode()
        self.write(PROVIDER, data)
        self.refresh_digest(PROVIDER)
        with self.assertRaisesRegex(AssertionError, "provider key name"):
            self.validate()

    def test_other_provider_endpoint_rejected_even_with_refreshed_digest(self):
        for path in (PROVIDER, WIRE):
            with self.subTest(path=path):
                data = (self.root / path).read_bytes()
                self.write(path, data + f"\nVALUE = {self.endpoint(0)!r}\n".encode())
                self.refresh_digest(path)
                with self.assertRaisesRegex(AssertionError, "direct provider endpoint"):
                    self.validate()
                self.write(path, data)
                self.refresh_digest(path)

    def test_bypass_pattern_is_never_exempt_even_with_refreshed_digest(self):
        marker = repository.FORBIDDEN_PATTERNS["Codex sandbox bypass"].pattern.split("|")[0]
        self.write(WIRE, (self.root / WIRE).read_bytes() + f"\nVALUE = {marker!r}\n".encode())
        self.refresh_digest(WIRE)
        with self.assertRaisesRegex(AssertionError, "sandbox bypass"):
            self.validate()

    def test_private_material_pattern_is_never_exempt(self):
        marker = "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5
        for path in (PROVIDER, WIRE):
            with self.subTest(path=path):
                original = (self.root / path).read_bytes()
                self.write(path, original + f"\nVALUE = {marker!r}\n".encode())
                self.refresh_digest(path)
                with self.assertRaisesRegex(AssertionError, "private key material"):
                    self.validate()
                self.write(path, original)
                self.refresh_digest(path)

    def test_token_material_pattern_is_never_exempt(self):
        marker = "gh" + "p_" + "A" * 40  # synthetic regex input only
        self.write(WIRE, (self.root / WIRE).read_bytes() + f"\nVALUE = {marker!r}\n".encode())
        self.refresh_digest(WIRE)
        with self.assertRaisesRegex(AssertionError, "token material"):
            self.validate()

    def test_missing_declaration_fails(self):
        (self.root / CONTRACT).unlink()
        with self.assertRaises(AssertionError):
            self.validate()

    def test_missing_declared_file_fails(self):
        (self.root / PROVIDER).unlink()
        with self.assertRaisesRegex(AssertionError, "not_scanned"):
            self.validate()

    def test_unknown_schema_extra_fields_and_wrong_contract_rejected(self):
        original = copy.deepcopy(self.contract)
        for change in ({"schema_version": True}, {"schema_version": 2}, {"contract_id": "other"}, {"enabled": True}):
            self.contract = dict(original, **change)
            self.save()
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.validate()

    def test_duplicate_json_fields_rejected(self):
        raw = json.dumps(self.contract).encode()
        self.write(CONTRACT, b'{"schema_version":1,' + raw[1:])
        with self.assertRaisesRegex(AssertionError, "duplicate_field"):
            self.validate()

    def test_contract_cannot_add_arbitrary_paths_or_directory_wildcards(self):
        original = copy.deepcopy(self.contract)
        for path in ("services/model_gateway/*", "lib/client.dart", "../" + PROVIDER, "/" + PROVIDER,
                     "services//model_gateway/responses_provider.py", "services/model_gateway/other.py"):
            self.contract = copy.deepcopy(original)
            self.contract["entries"][0]["path"] = path
            self.save()
            with self.subTest(path=path), self.assertRaises(AssertionError):
                self.validate()

    def test_duplicate_or_missing_declaration_rejected(self):
        original = copy.deepcopy(self.contract)
        for entries in ([], [original["entries"][0]], [original["entries"][0]] * 2,
                        original["entries"] + [original["entries"][0]]):
            self.contract = dict(original, entries=entries)
            self.save()
            with self.assertRaises(AssertionError):
                self.validate()

    def test_role_swap_and_unbounded_match_overrides_rejected(self):
        original = copy.deepcopy(self.contract)
        for changes in ({"role": "wire_regression"}, {"allowed_patterns": [".*"]}, {"sha256": "*"}):
            self.contract = copy.deepcopy(original)
            self.contract["entries"][0].update(changes)
            self.save()
            with self.assertRaises(AssertionError):
                self.validate()

    def test_contract_cannot_remove_security_pattern_checks(self):
        self.contract["entries"][1]["skip_patterns"] = list(repository.FORBIDDEN_PATTERNS)
        self.save()
        with self.assertRaisesRegex(AssertionError, "entry_invalid"):
            self.validate()

    def test_symlink_contract_is_rejected(self):
        target = self.root / "real.json"
        shutil.move(self.root / CONTRACT, target)
        (self.root / CONTRACT).symlink_to(target)
        with self.assertRaises(AssertionError):
            self.validate()

    def test_symlink_provider_is_rejected_even_when_bytes_match(self):
        target = self.root / "real.py"
        shutil.move(self.root / PROVIDER, target)
        (self.root / PROVIDER).symlink_to(target)
        with self.assertRaises(AssertionError):
            self.validate()

    def test_symlink_parent_directory_is_rejected(self):
        directory = self.root / "services/model_gateway"
        target = self.root / "moved"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(AssertionError):
            self.validate()

    def test_noncanonical_and_large_file_reads_rejected(self):
        for name in ("../real.py", "/real.py", "services//file.py", "services\\file.py"):
            with self.assertRaises(AssertionError):
                read_regular(self.root, name)
        with self.assertRaises(AssertionError):
            read_regular(self.root, PROVIDER, maximum_bytes=1)

    def test_invalid_utf8_never_becomes_replacement_text(self):
        self.write("services/bad.py", b"\xff")
        with self.assertRaisesRegex(AssertionError, "encoding_invalid"):
            self.validate()

    def test_duplicate_registered_file_scan_rejected(self):
        scanner = ServerProviderBoundary(self.root)
        raw = (self.root / PROVIDER).read_bytes()
        scanner.inspect(PROVIDER, raw, repository.FORBIDDEN_PATTERNS)
        with self.assertRaisesRegex(AssertionError, "duplicate_source"):
            scanner.inspect(PROVIDER, raw, repository.FORBIDDEN_PATTERNS)

    def test_same_snapshot_is_used_for_hash_and_marker_validation(self):
        scanner = ServerProviderBoundary(self.root)
        raw = (self.root / PROVIDER).read_bytes()
        self.write(PROVIDER, raw + b"\n# pathname changed after snapshot\n")
        self.assertEqual(scanner.inspect(PROVIDER, raw, repository.FORBIDDEN_PATTERNS), [])
        # New invocation sees the new bytes and rejects them, not stale approval.
        with self.assertRaisesRegex(AssertionError, "digest_mismatch"):
            self.validate()

    def test_scan_must_visit_both_declared_files(self):
        scanner = ServerProviderBoundary(self.root)
        scanner.inspect(PROVIDER, (self.root / PROVIDER).read_bytes(), repository.FORBIDDEN_PATTERNS)
        with self.assertRaisesRegex(AssertionError, "not_scanned"):
            scanner.finish()

    def test_direct_absolute_import_cannot_cross_to_adapter_or_plugin(self):
        for source in ("import services.model_gateway.responses_provider as p\n",
                       "from services.model_gateway import responses_provider as p\n",
                       "from services.model_gateway.responses_provider import ResponsesProvider\n",
                       "from services.model_gateway import *\n"):
            file = self.write("adapters/client.py", source.encode())
            with self.assertRaisesRegex(AssertionError, "direct import"):
                self.validate()
            file.unlink()

    def test_relative_direct_import_outside_model_service_rejected(self):
        self.write("services/control_plane/client.py", b"from ..model_gateway.responses_provider import ResponsesProvider\n")
        with self.assertRaisesRegex(AssertionError, "direct import"):
            self.validate()

    def test_same_service_import_remains_valid(self):
        self.write("services/model_gateway/client.py", b"from .responses_provider import ResponsesProvider\n")
        self.validate()

    def test_invalid_python_outside_service_fails_closed(self):
        self.write("adapters/client.py", b"def broken(:\n")
        with self.assertRaisesRegex(AssertionError, "parse_failed"):
            self.validate()

    def test_sensitive_evenai_log_check_still_runs(self):
        self.write("lib/services/evenai.dart", b"// combinedText-------\n")
        with self.assertRaisesRegex(AssertionError, "sensitive legacy logging"):
            self.validate()

    def test_all_original_scan_roots_and_security_patterns_remain(self):
        self.assertEqual(repository.SCAN_SOURCE, ["lib", "android", "ios", "services", "adapters", "plugins"])
        self.assertEqual(set(repository.FORBIDDEN_PATTERNS), {"provider key name", "direct provider endpoint",
                          "Codex sandbox bypass", "private key material", "GitHub token material"})

    def test_declared_bytes_equal_repository_files(self):
        for row in self.contract["entries"]:
            self.assertEqual(row["sha256"], hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest())


    def workflow_script(self):
        import textwrap
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        part = workflow.split("  secret-and-boundary-scan:", 1)[1]
        block = part.split("      - run: |\n", 1)[1].split("      - name: Scan every fetched", 1)[0]
        return textwrap.dedent(block)

    def run_workflow_scan(self):
        import subprocess
        for name in ("tools/validate_repository.py", "tools/server_provider_boundary.py"):
            self.write(name, (ROOT / name).read_bytes())
        for name in ("lib", "android", "ios", "services", "adapters", "plugins", "evidence"):
            (self.root / name).mkdir(exist_ok=True)
        return subprocess.run(["bash", "-c", self.workflow_script()], cwd=self.root,
                              capture_output=True, text=True, timeout=10)

    def test_actual_ci_shell_block_accepts_exact_declared_cloud_source(self):
        result = self.run_workflow_scan()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_ci_shell_block_rejects_consumer_endpoint(self):
        self.write("lib/client.dart", self.endpoint().encode())
        self.assertNotEqual(self.run_workflow_scan().returncode, 0)

    def test_actual_ci_shell_block_rejects_consumer_test_authority(self):
        self.write("lib/client.dart", b"TestMutationAuthorityProvider")
        self.assertNotEqual(self.run_workflow_scan().returncode, 0)

    def test_actual_ci_shell_block_rejects_evidence_secret_marker_without_echo(self):
        marker = "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5
        self.write("evidence/fixture.txt", marker.encode())
        result = self.run_workflow_scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_shell_guard_treats_grep_io_errors_as_failure(self):
        import subprocess
        script = self.workflow_script().split("          impossible marker")[0]
        function = script.split("assert_no_match() {", 1)[1].split("}\n", 1)[0]
        result = subprocess.run(["bash", "-c", "assert_no_match() {" + function +
                                 "}\nassert_no_match -E harmless missing-file\n"],
                                cwd=self.root, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)

    def test_canonical_job_matrix_is_unchanged(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(set(__import__("re").findall(r"^  ([a-z][a-z-]+):$", workflow, __import__("re").M))
                         - {"workflow-dispatch", "pull-request", "push"}, repository.EXPECTED_CHECKS)
        with patch.object(repository, "ROOT", ROOT):
            repository.validate_exact_head_workflow()


if __name__ == "__main__":
    unittest.main()
