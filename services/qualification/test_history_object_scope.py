"""Historical synthetic markers must never exempt a future key at the same path."""
from __future__ import annotations
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.scan_git_history import build_report, load_acknowledgements


class HistoryObjectScopeTest(unittest.TestCase):
    def test_private_marker_requires_exact_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "contracts/history-scan-acknowledgements-v1.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"schema_version": 1, "acknowledgements": [{
                "id": "fixture", "pattern": "private_key", "path": "fixture.py",
                "fingerprint": "0" * 64, "classification": "synthetic_test_fixture",
                "reason": "negative fixture",
            }]}))
            with self.assertRaisesRegex(RuntimeError, "exact object"):
                load_acknowledgements(root)

    def test_changed_blob_with_same_marker_is_not_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root).decode().strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            # Assemble an invalid marker at runtime; no static secret fixture.
            marker = b"-----BEGIN " + b"PRIVATE KEY-----"
            fixture = root / "fixture.txt"
            fixture.write_bytes(marker + b"\ninvalid\n")
            git("add", ".")
            git("commit", "-qm", "historical invalid fixture")
            object_id = git("rev-parse", "HEAD:fixture.txt")
            contract = root / "contracts/history-scan-acknowledgements-v1.json"
            contract.parent.mkdir()
            contract.write_text(json.dumps({"schema_version": 1, "acknowledgements": [{
                "id": "fixture", "pattern": "private_key", "path": "fixture.txt",
                "fingerprint": hashlib.sha256(marker).hexdigest(), "object": object_id,
                "classification": "synthetic_test_fixture", "reason": "exact invalid object",
            }]}))
            fixture.write_bytes(b"safe\n")
            git("add", ".")
            git("commit", "-qm", "remove fixture and acknowledge history")
            report = build_report(root)
            self.assertEqual(report["finding_count"], 0)
            self.assertEqual(report["acknowledged_finding_count"], 1)
            self.assertEqual(report["unused_acknowledgement_count"], 0)
            fixture.write_bytes(marker + b"\ndifferent untrusted content\n")
            git("add", ".")
            git("commit", "-qm", "different object must not inherit exemption")
            report = build_report(root)
            self.assertEqual(report["finding_count"], 1)
            self.assertEqual(report["acknowledged_finding_count"], 1)
            self.assertNotIn(marker.decode(), json.dumps(report))

    def test_malformed_object_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "contracts/history-scan-acknowledgements-v1.json"
            path.parent.mkdir()
            for value in ("*", None, "short", "A" * 40):
                with self.subTest(value=value):
                    path.write_text(json.dumps({"schema_version": 1, "acknowledgements": [{
                        "id": "fixture", "pattern": "private_key", "path": "fixture.py",
                        "fingerprint": "0" * 64, "object": value,
                        "classification": "synthetic_test_fixture", "reason": "negative fixture",
                    }]}))
                    with self.assertRaisesRegex(RuntimeError, "exact Git blob"):
                        load_acknowledgements(root)


if __name__ == "__main__":
    unittest.main()
