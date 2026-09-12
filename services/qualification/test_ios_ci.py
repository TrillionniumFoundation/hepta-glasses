from __future__ import annotations

import copy
import io
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
        self.assertIn("--input /tmp/hepta-ios-test-summary.json --root .", workflow)
        self.assertIn("-test-timeouts-enabled YES", workflow)
        self.assertIn("-maximum-test-execution-time-allowance 180", workflow)
        self.assertEqual(workflow.count("flutter pub get --enforce-lockfile"), 3)
        self.assertIn("flutter analyze --fatal-infos --fatal-warnings", workflow)
        self.assertNotIn("xcodebuild -showdestinations", workflow)
        self.assertNotIn("Designed for [iPad,iPhone]", workflow)
        self.assertNotIn('grep -Fq "id:$DEVICE_ID"', workflow)


class StrictIosResultTests(unittest.TestCase):
    def good(self):
        return dict(totalTestCount=7, passedTests=7, failedTests=0, skippedTests=0)

    def test_complete_explicit_counts_pass(self):
        self.assertTrue(ios_ci.validate_xcresult_summary(self.good(), expected_count=7)['ok'])

    def test_all_skipped_is_not_success(self):
        with self.assertRaisesRegex(ios_ci.IosCiError, 'skipped'):
            ios_ci.validate_xcresult_summary(dict(totalTestCount=7, passedTests=0, failedTests=0, skippedTests=7))

    def test_partial_skip_is_not_success(self):
        with self.assertRaisesRegex(ios_ci.IosCiError, 'skipped'):
            ios_ci.validate_xcresult_summary(dict(totalTestCount=7, passedTests=6, failedTests=0, skippedTests=1))

    def test_every_count_is_required(self):
        for key in self.good():
            with self.subTest(key=key):
                doc=self.good(); del doc[key]
                with self.assertRaises(ios_ci.IosCiError):
                    ios_ci.validate_xcresult_summary(doc)

    def test_invalid_integer_types_and_negative_counts(self):
        for key in self.good():
            for value in (None, True, False, '0', 0.0, -1):
                with self.subTest(key=key, value=value):
                    doc=self.good(); doc[key]=value
                    with self.assertRaises(ios_ci.IosCiError):
                        ios_ci.validate_xcresult_summary(doc)

    def test_nested_count_cannot_replace_missing_root_count(self):
        doc=self.good(); doc['child']={'passedTests':doc.pop('passedTests')}
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.validate_xcresult_summary(doc)

    def test_zero_failures_does_not_infer_passes(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.validate_xcresult_summary(dict(totalTestCount=7,failedTests=0))

    def test_zero_and_partial_runs_fail(self):
        for total, passed in ((0,0),(7,6),(7,8)):
            with self.subTest(total=total,passed=passed):
                with self.assertRaises(ios_ci.IosCiError):
                    ios_ci.validate_xcresult_summary(dict(totalTestCount=total,passedTests=passed,failedTests=0,skippedTests=0))

    def test_failed_run_fails(self):
        doc=self.good();doc['failedTests']=1;doc['passedTests']=6
        with self.assertRaisesRegex(ios_ci.IosCiError, 'failed tests'):
            ios_ci.validate_xcresult_summary(doc)

    def test_source_inventory_mismatch_fails(self):
        for count in (1,8,True,0,-1):
            with self.subTest(count=count):
                with self.assertRaises(ios_ci.IosCiError):
                    ios_ci.validate_xcresult_summary(self.good(),expected_count=count)

    def test_duplicate_json_key_fails(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.load_json(io.StringIO('{"failedTests":1,"failedTests":0}'))

    def test_oversized_json_fails(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.load_json(io.StringIO(' ' * (ios_ci.MAX_JSON_CHARACTERS+1)))

    def test_deep_json_fails_with_stable_error(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.load_json(io.StringIO('['*2000+'0'+']'*2000))

    def test_missing_devices_is_stable_failure(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.select_available_iphone({'unrelated': []})

    def test_non_ios_runtime_cannot_supply_iphone(self):
        with self.assertRaises(ios_ci.IosCiError):
            ios_ci.select_available_iphone({'devices': {'com.apple.CoreSimulator.SimRuntime.tvOS-99-1':[
                {'name':'iPhone pretend','udid':'11111111-1111-1111-1111-111111111111','isAvailable':True,'state':'Booted'}]}})



if __name__ == "__main__":
    unittest.main()
