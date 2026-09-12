from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.validate_release_version import ReleaseVersionError, validate

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "contracts/release-versioning-v1.json",
    "pubspec.yaml",
    "CHANGELOG.md",
    "android/app/build.gradle",
    "ios/Runner/Info.plist",
    "ios/Runner.xcodeproj/project.pbxproj",
    "docs/development/RELEASE_VERSIONING.md",
)


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-release-version-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for relative in FILES:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, relative)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_repository_version_contract_passes(self) -> None:
        result = validate(ROOT)
        self.assertEqual(result["version"], "0.2.0+2")
        self.assertEqual(result["tag"], "v0.2.0+2")
        self.assertFalse(result["automatic_promotion"])
        self.assertFalse(result["evidence_transfer"])

    def test_fixture_version_contract_passes(self) -> None:
        self.assertTrue(validate(self.root)["ok"])

    def test_zero_build_number_is_rejected(self) -> None:
        self.replace("pubspec.yaml", "version: 0.2.0+2", "version: 0.2.0+0")
        with self.assertRaisesRegex(ReleaseVersionError, "positive_build"):
            validate(self.root)

    def test_changelog_must_match_authority(self) -> None:
        self.replace(
            "CHANGELOG.md",
            "## [0.2.0+2] - 2026-09-09",
            "## [0.2.0+3] - 2026-09-09",
        )
        with self.assertRaisesRegex(ReleaseVersionError, "changelog version"):
            validate(self.root)

    def test_android_literal_version_is_rejected(self) -> None:
        self.replace(
            "android/app/build.gradle",
            "versionCode = flutter.versionCode",
            "versionCode = 2",
        )
        with self.assertRaisesRegex(ReleaseVersionError, "versionCode"):
            validate(self.root)

    def test_ios_projection_drift_is_rejected(self) -> None:
        self.replace(
            "ios/Runner/Info.plist",
            "$(FLUTTER_BUILD_NUMBER)",
            "2",
        )
        with self.assertRaisesRegex(ReleaseVersionError, "bundle version"):
            validate(self.root)

    def test_automatic_promotion_is_rejected(self) -> None:
        path = self.root / "contracts/release-versioning-v1.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["promotion"]["automatic"] = True
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseVersionError, "automatic promotion"):
            validate(self.root)

    def test_evidence_transfer_is_rejected(self) -> None:
        path = self.root / "contracts/release-versioning-v1.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["promotion"]["evidence_transfer"] = True
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseVersionError, "evidence transfer"):
            validate(self.root)

    def test_contract_shape_and_duplicate_keys_are_closed(self) -> None:
        path = self.root / "contracts/release-versioning-v1.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["unreviewed_promotion"] = True
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(ReleaseVersionError, "not closed"):
            validate(self.root)

        path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ReleaseVersionError, "duplicate JSON key"):
            validate(self.root)


if __name__ == "__main__":
    unittest.main()
