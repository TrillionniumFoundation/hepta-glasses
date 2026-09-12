from __future__ import annotations

import plistlib
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
CANONICAL_DART = "hepta_glasses"
CANONICAL_JAVA = "org.trillionnium.heptaglasses"


class MobileProductIdentityTests(unittest.TestCase):
    def test_dart_android_and_apple_release_identity_is_canonical(self) -> None:
        pubspec = (ROOT / "pubspec.yaml").read_text(encoding="utf-8")
        gradle = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
        manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
        application = manifest.find("application")
        self.assertIsNotNone(application)
        self.assertRegex(pubspec, r"(?m)^name: hepta_glasses$")
        self.assertRegex(gradle, r'(?m)^\s*namespace = "org\.trillionnium\.heptaglasses"$')
        self.assertRegex(gradle, r'(?m)^\s*applicationId = "org\.trillionnium\.heptaglasses"$')
        self.assertEqual(application.attrib[f"{ANDROID_NS}label"], "Hepta Glasses")
        with (ROOT / "ios/Runner/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        self.assertEqual(info["CFBundleDisplayName"], "Hepta Glasses")
        self.assertEqual(info["CFBundleName"], CANONICAL_DART)
        project = (ROOT / "ios/Runner.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
        self.assertGreaterEqual(project.count(f"PRODUCT_BUNDLE_IDENTIFIER = {CANONICAL_JAVA};"), 3)
        self.assertGreaterEqual(project.count(f"PRODUCT_BUNDLE_IDENTIFIER = {CANONICAL_JAVA}.RunnerTests;"), 3)

    def test_android_source_trees_and_packages_moved_atomically(self) -> None:
        suffix = Path(*CANONICAL_JAVA.split("."))
        for source_set in ("main", "test"):
            package_root = ROOT / "android/app/src" / source_set / "kotlin" / suffix
            self.assertTrue(package_root.is_dir(), package_root)
            kotlin_files = sorted(package_root.rglob("*.kt"))
            self.assertTrue(kotlin_files, package_root)
            for path in kotlin_files:
                text = path.read_text(encoding="utf-8")
                self.assertRegex(text, r"(?m)^package org\.trillionnium\.heptaglasses(?:\.|$)")

    def test_jni_registration_uses_canonical_package(self) -> None:
        native = (ROOT / "android/app/src/main/cpp/liblc3.cpp").read_text(encoding="utf-8")
        self.assertIn("Java_org_trillionnium_heptaglasses_cpp_Cpp_decodeLC3", native)
        self.assertIn("Java_org_trillionnium_heptaglasses_cpp_Cpp_rnNoise", native)

    def test_inherited_demo_identifiers_are_absent_from_active_surfaces(self) -> None:
        legacy_dart = "demo" + "_ai_even"
        legacy_java = ".".join(("com", "example", legacy_dart))
        legacy_path = legacy_java.replace(".", "/")
        legacy_jni = "Java_" + "com_example_demo_1ai_1even"
        patterns = (legacy_dart, legacy_java, legacy_path, legacy_jni)
        roots = ("android", "ios", "lib", "test", "services", "contracts", "docs", "tools", ".github")
        excluded = {"build", ".dart_tool", "Pods", ".symlinks"}
        for relative in roots:
            base = ROOT / relative
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or excluded.intersection(path.parts):
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                if b"\x00" in data or len(data) > 5_000_000:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for pattern in patterns:
                    self.assertNotIn(pattern, text, f"{path}: {pattern}")

    def test_migration_and_external_authority_boundaries_are_documented(self) -> None:
        guide = (ROOT / "docs/development/PRODUCT_IDENTITY.md").read_text(encoding="utf-8")
        for phrase in (
            "Atomic migration invariants",
            "Application data continuity",
            "absence of inherited demo identifiers",
            "does not close production signing",
            "external evidence gates",
        ):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
