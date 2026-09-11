#!/usr/bin/env python3
"""Fail-closed helpers for the canonical iOS native-test CI lane.

The workflow consumes CoreSimulator's structured JSON rather than scraping
``xcodebuild -showdestinations`` human-readable text.  It also verifies that the
shared scheme contains a non-skipped native test target and that the xcresult
summary reports a non-empty, failure-free test run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO

UDID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
RUNTIME_VERSION = re.compile(r"(?:^|[.-])iOS[-.]?(\d+)(?:[-.](\d+))?(?:[-.](\d+))?$")
SWIFT_TEST = re.compile(r"\bfunc\s+(test[A-Za-z0-9_]*)\s*\(")


class IosCiError(ValueError):
    """Stable failure raised when the iOS qualification lane is ambiguous."""


@dataclass(frozen=True, slots=True)
class Simulator:
    runtime: str
    name: str
    udid: str
    state: str

    @property
    def destination(self) -> str:
        return f"platform=iOS Simulator,id={self.udid}"


def fail(message: str) -> None:
    raise IosCiError(message)


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(stream: TextIO) -> Any:
    try:
        return json.load(
            stream,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: fail(f"non-finite JSON number: {value}"),
        )
    except IosCiError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"invalid JSON: {error}")


def _runtime_key(identifier: str) -> tuple[int, int, int, str]:
    normalized = identifier.rsplit(".", 1)[-1]
    match = RUNTIME_VERSION.search(normalized)
    if match is None:
        return (-1, -1, -1, identifier)
    values = tuple(int(value or 0) for value in match.groups())
    return (*values, identifier)


def select_available_iphone(document: Any) -> Simulator:
    if not isinstance(document, Mapping) or set(document) < {"devices"}:
        fail("simctl document lacks devices")
    devices = document["devices"]
    if not isinstance(devices, Mapping):
        fail("simctl devices must be an object")

    candidates: list[Simulator] = []
    for runtime, entries in devices.items():
        if not isinstance(runtime, str) or not isinstance(entries, list):
            fail("simctl runtime inventory is malformed")
        for entry in entries:
            if not isinstance(entry, Mapping):
                fail("simctl device entry is malformed")
            if entry.get("isAvailable") is not True:
                continue
            name = entry.get("name")
            udid = entry.get("udid")
            state = entry.get("state", "Unknown")
            if not isinstance(name, str) or not name.startswith("iPhone"):
                continue
            if not isinstance(udid, str) or UDID.fullmatch(udid) is None:
                fail(f"available iPhone has invalid UDID: {udid!r}")
            if not isinstance(state, str) or not state:
                fail("available iPhone has invalid state")
            candidates.append(
                Simulator(runtime=runtime, name=name, udid=udid.upper(), state=state)
            )

    if not candidates:
        fail("no available iPhone simulator")

    # Prefer the newest runtime.  Within one runtime, deterministic lexical
    # ordering avoids depending on CoreSimulator's presentation order.
    candidates.sort(
        key=lambda item: (_runtime_key(item.runtime), item.name, item.udid),
        reverse=True,
    )
    return candidates[0]


def validate_test_inventory(root: Path) -> dict[str, Any]:
    root = root.resolve()
    scheme = root / "ios/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme"
    tests_dir = root / "ios/RunnerTests"
    if scheme.is_symlink() or not scheme.is_file():
        fail("shared Runner scheme is missing or linked")
    if tests_dir.is_symlink() or not tests_dir.is_dir():
        fail("RunnerTests directory is missing or linked")

    try:
        tree = ET.parse(scheme)
    except (ET.ParseError, OSError) as error:
        fail(f"cannot parse Runner scheme: {error}")

    testables = []
    for reference in tree.findall("./TestAction/Testables/TestableReference"):
        if reference.attrib.get("skipped") == "YES":
            continue
        buildable = reference.find("BuildableReference")
        if buildable is None:
            continue
        product = buildable.attrib.get("BuildableName")
        blueprint = buildable.attrib.get("BlueprintName")
        if product == "RunnerTests.xctest" and blueprint == "RunnerTests":
            testables.append((product, blueprint))
    if testables != [("RunnerTests.xctest", "RunnerTests")]:
        fail("Runner scheme must contain exactly one enabled RunnerTests target")

    discovered: list[str] = []
    for path in sorted(tests_dir.glob("*.swift")):
        if path.is_symlink() or not path.is_file():
            fail(f"invalid Swift test source: {path.relative_to(root)}")
        text = path.read_text(encoding="utf-8")
        for name in SWIFT_TEST.findall(text):
            if name in discovered:
                fail(f"duplicate Swift test identifier: {name}")
            discovered.append(name)
    if not discovered:
        fail("RunnerTests target has no discoverable test methods")
    return {
        "ok": True,
        "target": "RunnerTests",
        "tests": sorted(discovered),
        "test_count": len(discovered),
    }


def _numbers_for_key(value: Any, key: str) -> list[int]:
    values: list[int] = []
    if isinstance(value, Mapping):
        for current_key, current_value in value.items():
            if current_key == key and isinstance(current_value, int) and not isinstance(
                current_value, bool
            ):
                values.append(current_value)
            values.extend(_numbers_for_key(current_value, key))
    elif isinstance(value, list):
        for item in value:
            values.extend(_numbers_for_key(item, key))
    return values


def validate_xcresult_summary(document: Any) -> dict[str, int | bool]:
    if not isinstance(document, Mapping):
        fail("xcresult summary must be an object")

    total_values = _numbers_for_key(document, "totalTestCount")
    passed_values = _numbers_for_key(document, "passedTests")
    failed_values = _numbers_for_key(document, "failedTests")
    skipped_values = _numbers_for_key(document, "skippedTests")
    if len(total_values) != 1 or len(failed_values) != 1:
        fail("xcresult summary has ambiguous test counts")

    total = total_values[0]
    failed = failed_values[0]
    passed = passed_values[0] if len(passed_values) == 1 else total - failed
    skipped = skipped_values[0] if len(skipped_values) == 1 else 0
    if min(total, passed, failed, skipped) < 0:
        fail("xcresult summary contains a negative test count")
    if total <= 0:
        fail("iOS native test run executed zero tests")
    if failed != 0:
        fail(f"iOS native test run has {failed} failed tests")
    if passed + failed + skipped != total:
        fail("xcresult summary counts do not reconcile")
    return {
        "ok": True,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def _open_input(path: str | None) -> TextIO:
    if path is None or path == "-":
        return sys.stdin
    return Path(path).open("r", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select-destination")
    select.add_argument("--input", default="-")

    inventory = subparsers.add_parser("validate-inventory")
    inventory.add_argument("--root", default=".")

    result = subparsers.add_parser("validate-result")
    result.add_argument("--input", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "select-destination":
            stream = _open_input(args.input)
            try:
                simulator = select_available_iphone(load_json(stream))
            finally:
                if stream is not sys.stdin:
                    stream.close()
            print(simulator.destination)
        elif args.command == "validate-inventory":
            print(json.dumps(validate_test_inventory(Path(args.root)), sort_keys=True))
        else:
            stream = _open_input(args.input)
            try:
                summary = validate_xcresult_summary(load_json(stream))
            finally:
                if stream is not sys.stdin:
                    stream.close()
            print(json.dumps(summary, sort_keys=True))
    except (IosCiError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
