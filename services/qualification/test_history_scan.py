from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.scan_git_history import build_report, scan_blob


class HistoryScanTest(unittest.TestCase):
    def test_finding_is_fingerprinted_without_secret_material(self) -> None:
        secret = b"sk-abcdefghijklmnopqrstuvwxyz123456"
        findings = scan_blob(secret, path="lib/example.dart", object_id="a" * 40)
        self.assertEqual(len(findings), 1)
        self.assertNotIn(secret.decode(), str(findings))
        self.assertEqual(len(findings[0]["fingerprint"]), 64)

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
            self.assertGreaterEqual(report["commit_count"], 2)
            self.assertGreaterEqual(report["ref_count"], 2)


if __name__ == "__main__":
    unittest.main()
