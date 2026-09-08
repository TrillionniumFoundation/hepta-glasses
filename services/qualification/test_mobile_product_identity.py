from __future__ import annotations

import plistlib
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


class MobileProductIdentityTests(unittest.TestCase):
    def test_android_release_identity_is_canonical(self) -> None:
        gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
        manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
        application = manifest.find("application")
        self.assertIsNotNone(application)
        self.assertRegex(
            gradle,
            r'(?m)^\s*applicationId = "org\.trillionnium\.heptaglasses"$',
        )
        self.assertEqual(application.attrib[f"{ANDROID_NS}label"], "Hepta Glasses")
        self.assertNotIn("TODO: Specify your own unique Application ID", gradle)
        self.assertIn("Source packages retain the inherited namespace", gradle)

    def test_ios_user_visible_identity_is_canonical(self) -> None:
        with (ROOT / "ios/Runner/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        self.assertEqual(info["CFBundleDisplayName"], "Hepta Glasses")
        self.assertEqual(info["CFBundleName"], "hepta_glasses")
        self.assertEqual(info["CFBundleIdentifier"], "$(PRODUCT_BUNDLE_IDENTIFIER)")
        self.assertIn("Hepta Glasses", info["NSBluetoothAlwaysUsageDescription"])
        self.assertIn("Hepta Glasses", info["NSPhotoLibraryUsageDescription"])
        self.assertIn("Hepta Glasses", info["NSSpeechRecognitionUsageDescription"])

    def test_demo_title_is_absent_from_mobile_release_surfaces(self) -> None:
        paths = (
            "android/app/build.gradle",
            "android/app/src/main/AndroidManifest.xml",
            "ios/Runner/Info.plist",
        )
        title = re.compile(r"Demo(?:\s+|-)Ai(?:\s+|-)Even", re.IGNORECASE)
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(title.search(text), relative)

    def test_compatibility_and_signing_boundaries_are_documented(self) -> None:
        guide = (ROOT / "docs/development/PRODUCT_IDENTITY.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "implementation compatibility identifiers",
            "atomic migration",
            "PRODUCT_BUNDLE_IDENTIFIER",
            "provisioning profile",
            "does not close signing",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
