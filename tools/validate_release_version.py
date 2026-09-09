#!/usr/bin/env python3
"""Validate single-source mobile versioning and fail-closed promotion semantics."""
from __future__ import annotations

import json
import plistlib
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = "contracts/release-versioning-v1.json"
VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\+([1-9][0-9]*)$"
)
TAG_RE = re.compile(
    r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\+([1-9][0-9]*)$"
)
EXPECTED_JOBS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
)
EXPECTED_CONTRACT_KEYS = {
    "schema_version",
    "version_authority",
    "version_pattern",
    "changelog",
    "tag_pattern",
    "android_projection",
    "ios_projection",
    "promotion",
}
EXPECTED_PROMOTION_KEYS = {
    "automatic",
    "evidence_transfer",
    "required_checks",
    "requires_exact_head_artifact",
    "requires_eligible_latest_head_review",
    "requires_protected_adoption",
    "signed_binary_is_separate_authority",
}


class ReleaseVersionError(ValueError):
    """Stable validation failure for the repository version boundary."""


def fail(message: str) -> None:
    raise ReleaseVersionError(message)


def _reject_constant(value: str) -> None:
    fail(f"non-finite JSON number is prohibited: {value}")


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReleaseVersionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a JSON object")
    return value


def _text(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        fail(f"required regular file is missing: {relative}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read {relative}: {error}")


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(
            f"{label} is not closed; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _one_assignment(text: str, name: str, expected: str, label: str) -> None:
    values = re.findall(rf"(?m)^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", text)
    if values != [expected]:
        fail(f"{label} must contain exactly one {name} = {expected!s} projection")


def _validate_contract(root: Path) -> dict[str, Any]:
    contract = _strict_json(root / CONTRACT_PATH)
    _exact_keys(contract, EXPECTED_CONTRACT_KEYS, "release version contract")
    if contract["schema_version"] != 1:
        fail("unsupported release version contract schema")
    if contract["version_authority"] != "pubspec.yaml":
        fail("pubspec.yaml must be the sole repository version authority")
    if contract["version_pattern"] != VERSION_RE.pattern:
        fail("release version pattern drifted")
    if contract["tag_pattern"] != TAG_RE.pattern:
        fail("release tag pattern drifted")
    if contract["changelog"] != "CHANGELOG.md":
        fail("release changelog path drifted")
    if contract["android_projection"] != {
        "version_name": "flutter.versionName",
        "version_code": "flutter.versionCode",
    }:
        fail("Android version projection contract drifted")
    if contract["ios_projection"] != {
        "short_version": "$(FLUTTER_BUILD_NAME)",
        "bundle_version": "$(FLUTTER_BUILD_NUMBER)",
        "project_version": "$(FLUTTER_BUILD_NUMBER)",
    }:
        fail("iOS version projection contract drifted")
    promotion = contract["promotion"]
    if not isinstance(promotion, dict):
        fail("promotion contract must be an object")
    _exact_keys(promotion, EXPECTED_PROMOTION_KEYS, "promotion contract")
    if promotion["automatic"] is not False:
        fail("automatic promotion is prohibited")
    if promotion["evidence_transfer"] is not False:
        fail("predecessor evidence transfer is prohibited")
    if tuple(promotion["required_checks"]) != EXPECTED_JOBS:
        fail("canonical required-check identity or order drifted")
    for field in (
        "requires_exact_head_artifact",
        "requires_eligible_latest_head_review",
        "requires_protected_adoption",
        "signed_binary_is_separate_authority",
    ):
        if promotion[field] is not True:
            fail(f"promotion.{field} must remain true")
    return contract


def _pubspec_version(root: Path) -> str:
    pubspec = _text(root, "pubspec.yaml")
    declarations = re.findall(r"(?m)^version:\s*([^\s#]+)\s*(?:#.*)?$", pubspec)
    if len(declarations) != 1:
        fail("pubspec.yaml must contain exactly one version declaration")
    version = declarations[0]
    match = VERSION_RE.fullmatch(version)
    if match is None:
        fail("pubspec version must be major.minor.patch+positive_build without leading zeroes")
    if not 1 <= int(match.group(4)) <= 2_147_483_647:
        fail("pubspec build number is outside the supported positive 32-bit range")
    return version


def _validate_changelog(root: Path, version: str) -> str:
    changelog = _text(root, "CHANGELOG.md")
    headings = re.findall(
        r"(?m)^## \[([^\]]+)\] - ([0-9]{4}-[0-9]{2}-[0-9]{2})$",
        changelog,
    )
    if not headings:
        fail("CHANGELOG.md has no versioned release entry")
    recorded_version, recorded_date = headings[0]
    if recorded_version != version:
        fail("first changelog version does not equal pubspec authority")
    try:
        parsed_date = date.fromisoformat(recorded_date)
    except ValueError as error:
        fail(f"changelog date is invalid: {error}")
    if parsed_date > date.today():
        fail("changelog entry is dated in the future")
    required_phrases = (
        "not a production-release claim",
        "source candidate",
        "not a signed",
    )
    for phrase in required_phrases:
        if phrase not in changelog:
            fail(f"CHANGELOG.md lacks claim-ceiling phrase: {phrase}")
    return recorded_date


def _validate_android(root: Path) -> None:
    gradle = _text(root, "android/app/build.gradle")
    _one_assignment(
        gradle,
        "versionCode",
        "flutter.versionCode",
        "android/app/build.gradle",
    )
    _one_assignment(
        gradle,
        "versionName",
        "flutter.versionName",
        "android/app/build.gradle",
    )


def _validate_ios(root: Path) -> None:
    plist_path = root / "ios/Runner/Info.plist"
    if plist_path.is_symlink() or not plist_path.is_file():
        fail("required regular file is missing: ios/Runner/Info.plist")
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as error:
        fail(f"cannot parse iOS Info.plist: {error}")
    if info.get("CFBundleShortVersionString") != "$(FLUTTER_BUILD_NAME)":
        fail("iOS short version must project FLUTTER_BUILD_NAME")
    if info.get("CFBundleVersion") != "$(FLUTTER_BUILD_NUMBER)":
        fail("iOS bundle version must project FLUTTER_BUILD_NUMBER")

    project = _text(root, "ios/Runner.xcodeproj/project.pbxproj")
    projected = project.count('CURRENT_PROJECT_VERSION = "$(FLUTTER_BUILD_NUMBER)";')
    if projected < 3:
        fail("every Runner build configuration must project FLUTTER_BUILD_NUMBER")


def _validate_documentation(root: Path) -> None:
    guide = _text(root, "docs/development/RELEASE_VERSIONING.md")
    for phrase in (
        "sole repository version authority",
        "Promotion is never automatic",
        "A rollback is a new source object",
        "Tags are immutable",
        "does not prove provisioning",
    ):
        if phrase not in guide:
            fail(f"release version guide lacks required semantic: {phrase}")


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    _validate_contract(root)
    version = _pubspec_version(root)
    changelog_date = _validate_changelog(root, version)
    _validate_android(root)
    _validate_ios(root)
    _validate_documentation(root)
    tag = f"v{version}"
    if TAG_RE.fullmatch(tag) is None:
        fail("derived release tag does not satisfy the contract")
    return {
        "ok": True,
        "version": version,
        "tag": tag,
        "changelog_date": changelog_date,
        "required_checks": list(EXPECTED_JOBS),
        "automatic_promotion": False,
        "evidence_transfer": False,
    }


def main() -> int:
    try:
        result = validate()
    except ReleaseVersionError as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
