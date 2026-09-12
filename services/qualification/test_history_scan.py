from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.scan_git_history import MAX_BLOB_BYTES, build_report, scan_blob


def _synthetic_provider_token() -> bytes:
    """Build an inert scanner fixture without storing token-shaped source text."""
    return b"sk-" + bytes(97 + (index % 26) for index in range(32))


def _synthetic_history_fixture() -> bytes:
    """Benign end-to-end sentinel; it is not shaped like any provider credential."""
    return b"HEPTA-HISTORY-FIXTURE-" + bytes(
        65 + (index % 26) for index in range(24)
    )


class HistoryScanTest(unittest.TestCase):
    def test_finding_is_fingerprinted_without_secret_material(self) -> None:
        token_bytes = _synthetic_provider_token()
        findings = scan_blob(token_bytes, path="lib/example.dart", object_id="a" * 40)
        self.assertEqual(len(findings), 1)
        self.assertNotIn(token_bytes.decode(), str(findings))
        self.assertEqual(len(findings[0]["fingerprint"]), 64)

    def test_binary_blob_is_not_silently_skipped(self) -> None:
        token_bytes = b"prefix\x00" + _synthetic_provider_token() + b"\x00suffix"
        findings = scan_blob(token_bytes, path="assets/sample.bin", object_id="b" * 40)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["pattern"], "provider_token")

    def test_scans_all_fetched_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            subprocess.check_call(
                ["git", "config", "user.email", "test@example.invalid"], cwd=root
            )
            subprocess.check_call(["git", "config", "user.name", "Test"], cwd=root)
            (root / "safe.txt").write_text("safe\n", encoding="utf-8")
            subprocess.check_call(["git", "add", "."], cwd=root)
            subprocess.check_call(["git", "commit", "-qm", "safe"], cwd=root)
            first = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            subprocess.check_call(["git", "branch", "old", first], cwd=root)
            (root / "safe.txt").write_text("still safe\n", encoding="utf-8")
            subprocess.check_call(["git", "commit", "-qam", "second"], cwd=root)

            report = build_report(root)
            self.assertEqual(report["finding_count"], 0)
            self.assertEqual(report["unscanned_blob_count"], 0)
            self.assertGreaterEqual(report["commit_count"], 2)
            self.assertGreaterEqual(report["ref_count"], 2)

    def test_exact_synthetic_fixture_acknowledgement_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            subprocess.check_call(
                ["git", "config", "user.email", "test@example.invalid"], cwd=root
            )
            subprocess.check_call(["git", "config", "user.name", "Test"], cwd=root)
            fixture_bytes = _synthetic_history_fixture()
            fixture = root / "services/qualification/test_history_scan.py"
            fixture.parent.mkdir(parents=True)
            fixture.write_bytes(fixture_bytes)
            contract = root / "contracts/history-scan-acknowledgements-v1.json"
            contract.parent.mkdir(parents=True)
            contract.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "acknowledgements": [
                            {
                                "id": "synthetic-fixture",
                                "pattern": "synthetic_fixture",
                                "path": str(fixture.relative_to(root)),
                                "fingerprint": hashlib.sha256(fixture_bytes).hexdigest(),
                                "classification": "synthetic_test_fixture",
                                "reason": "unit-test fixture",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subprocess.check_call(["git", "add", "."], cwd=root)
            subprocess.check_call(["git", "commit", "-qm", "fixture"], cwd=root)
            with mock.patch.dict(
                "tools.scan_git_history.PATTERNS",
                {
                    "synthetic_fixture": re.compile(
                        rb"HEPTA-HISTORY-FIXTURE-[A-Z]{24}"
                    )
                },
                clear=True,
            ):
                report = build_report(root)
            self.assertEqual(report["raw_finding_count"], 1)
            self.assertEqual(report["acknowledged_finding_count"], 1)
            self.assertEqual(report["finding_count"], 0)
            self.assertEqual(report["unused_acknowledgement_count"], 0)
            self.assertNotIn(fixture_bytes.decode(), str(report))

    def test_stale_history_acknowledgement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            subprocess.check_call(
                ["git", "config", "user.email", "test@example.invalid"], cwd=root
            )
            subprocess.check_call(["git", "config", "user.name", "Test"], cwd=root)
            (root / "safe.txt").write_text("safe\n", encoding="utf-8")
            contract = root / "contracts/history-scan-acknowledgements-v1.json"
            contract.parent.mkdir(parents=True)
            contract.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "acknowledgements": [
                            {
                                "id": "stale-fixture",
                                "pattern": "provider_token",
                                "path": "services/qualification/test_history_scan.py",
                                "fingerprint": "0" * 64,
                                "classification": "synthetic_test_fixture",
                                "reason": "must be consumed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subprocess.check_call(["git", "add", "."], cwd=root)
            subprocess.check_call(["git", "commit", "-qm", "safe"], cwd=root)
            report = build_report(root)
            self.assertEqual(report["finding_count"], 0)
            self.assertEqual(report["unused_acknowledgement_count"], 1)

    def test_large_blob_is_reported_as_unscanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            subprocess.check_call(
                ["git", "config", "user.email", "test@example.invalid"], cwd=root
            )
            subprocess.check_call(["git", "config", "user.name", "Test"], cwd=root)
            (root / "large.bin").write_bytes(b"x" * 32)
            subprocess.check_call(["git", "add", "."], cwd=root)
            subprocess.check_call(["git", "commit", "-qm", "large"], cwd=root)

            with mock.patch("tools.scan_git_history.MAX_BLOB_BYTES", 16):
                report = build_report(root)

            self.assertEqual(report["unscanned_blob_count"], 1)
            self.assertEqual(report["unscanned_blobs"][0]["size"], 32)
            self.assertLess(16, MAX_BLOB_BYTES)


if __name__ == "__main__":
    unittest.main()
