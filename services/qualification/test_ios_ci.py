from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import ios_ci

ROOT = Path(__file__).resolve().parents[2]


class IosCiTests(unittest.TestCase):
    def simctl(self) -> dict[str, object]:
        return {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [
                    {
                        "name": "iPhone 15",
                        "udid": "11111111-1111-1111-1111-111111111111",
                        "state": "Shutdown",
                        "isAvailable": True,
                    }
                ],
                "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                    {
                        "name": "iPhone 16 Pro",
                        "udid": "22222222-2222-2222-2222-222222222222",
                        "state": "Booted",
                        "isAvailable": True,
                    }
                ],
            }
        }

    def test_structured_simctl_selects_newest_available_iphone(self) -> None:
        selected = ios_ci.select_available_iphone(self.simctl())
        self.assertEqual(
            selected.destination,
            "platform=iOS Simulator,id=22222222-2222-2222-2222-222222222222",
        )

    def test_json_whitespace_and_brackets_do_not_affect_selection(self) -> None:
        payload = json.dumps(self.simctl(), indent=4)
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as fixture:
            fixture.write(payload)
            fixture.flush()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/ios_ci.py"),
                    "select-destination",
                    "--input",
                    fixture.name,
                ],
                cwd=ROOT,
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "platform=iOS Simulator,id=22222222-2222-2222-2222-222222222222",
        )

    def test_no_available_destination_fails_closed(self) -> None:
        document = self.simctl()
        devices = document["devices"]
        assert isinstance(devices, dict)
        for entries in devices.values():
            assert isinstance(entries, list)
            for entry in entries:
                assert isinstance(entry, dict)
                entry["isAvailable"] = False
        with self.assertRaisesRegex(ios_ci.IosCiError, "no available"):
            ios_ci.select_available_iphone(document)

    def test_invalid_available_udid_fails_closed(self) -> None:
        document = self.simctl()
        devices = document["devices"]
        assert isinstance(devices, dict)
        newest = devices["com.apple.CoreSimulator.SimRuntime.iOS-18-2"]
        assert isinstance(newest, list)
        entry = newest[0]
        assert isinstance(entry, dict)
        entry["udid"] = "not-a-udid"
        with self.assertRaisesRegex(ios_ci.IosCiError, "invalid UDID"):
            ios_ci.select_available_iphone(document)

    def test_shared_scheme_and_swift_inventory_are_nonempty(self) -> None:
        result = ios_ci.validate_test_inventory(ROOT)
        self.assertEqual(result["target"], "RunnerTests")
        self.assertGreaterEqual(result["test_count"], 7)
        self.assertIn(
            "testGenerationNTokenCannotOwnGenerationNPlusOne",
            result["tests"],
        )

    def test_xcresult_summary_requires_nonempty_failure_free_run(self) -> None:
        result = ios_ci.validate_xcresult_summary(
            {
                "totalTestCount": 7,
                "passedTests": 7,
                "failedTests": 0,
                "skippedTests": 0,
            }
        )
        self.assertEqual(result["total"], 7)
        self.assertIs(result["ok"], True)

    def test_zero_or_failed_test_result_fails_closed(self) -> None:
        for summary, pattern in (
            (
                {
                    "totalTestCount": 0,
                    "passedTests": 0,
                    "failedTests": 0,
                    "skippedTests": 0,
                },
                "zero tests",
            ),
            (
                {
                    "totalTestCount": 7,
                    "passedTests": 6,
                    "failedTests": 1,
                    "skippedTests": 0,
                },
                "failed tests",
            ),
        ):
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ios_ci.IosCiError, pattern):
                    ios_ci.validate_xcresult_summary(copy.deepcopy(summary))

    def test_workflow_uses_udid_destination_without_text_fallback(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        # This test is updated with the workflow in the same change.  The old
        # parser and comma-bearing macOS fallback must never return.
        self.assertIn("tools/ios_ci.py select-destination", workflow)
        self.assertIn("-only-testing:RunnerTests", workflow)
        self.assertIn("tools/ios_ci.py validate-result", workflow)
        self.assertNotIn("xcodebuild -showdestinations", workflow)
        self.assertNotIn("Designed for [iPad,iPhone]", workflow)
        self.assertNotIn('grep -Fq "id:$DEVICE_ID"', workflow)


if __name__ == "__main__":
    unittest.main()
