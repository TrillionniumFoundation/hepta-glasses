#!/usr/bin/env python3
"""Deterministically normalize the current G4 integration head for CI."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, before: str, after: str) -> None:
    content = read(path)
    if content.count(before) != 1:
        raise RuntimeError(f"{path}: expected one exact pre-image")
    write(path, content.replace(before, after, 1))


def main() -> None:
    replace_once(
        "tools/validate_repository.py",
        '    if "Verify artifact is bound to PR head" not in workflow:\n'
        '        fail("source evidence workflow lacks an internal exact-head assertion")\n',
        '    exact_head_fragments = (\n'
        '        "source-evidence-summary.json",\n'
        '        "summary[\'commit\'] != expected",\n'
        '        "SOURCE_HEAD_SHA",\n'
        '    )\n'
        '    if any(fragment not in workflow for fragment in exact_head_fragments):\n'
        '        fail("source evidence workflow lacks an internal exact-head assertion")\n',
    )

    replace_once(
        "services/control_plane/identity.py",
        '        if payload["iss"] != self.issuer or payload["aud"] != audience:\n'
        '            raise IdentityEror("token_audience_invalid")\n',
        '        if payload["iss"] != self.issuer or payload["aud"] != audience:\n'
        '            raise IdentityError("token_audience_invalid")\n',
    )
    replace_once(
        "services/control_plane/test_identity.py",
        '\n\nif __name__ == "__main__":\n    unittest.main()\n',
        '\n    def test_wrong_audience_returns_stable_identity_error(self) -> None:\n'
        '        token = self.issue()\n'
        '        with self.assertRaises(IdentityError) as raised:\n'
        '            self.tokens.verify(token, audience="wrong-audience")\n'
        '        self.assertEqual(raised.exception.code, "token_audience_invalid")\n'
        '\n\nif __name__ == "__main__":\n    unittest.main()\n',
    )

    properties = read("android/gradle.properties")
    for line in ("android.builtInKotlin=false", "android.newDsl=false"):
        if line not in properties:
            properties = properties.rstrip() + "\n" + line + "\n"
    write("android/gradle.properties", properties)

    podfile = read("ios/Podfile")
    podfile, count = re.subn(
        r"^# platform :ios, '12\.0'$",
        "platform :ios, '15.0'",
        podfile,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError("ios/Podfile: platform pre-image missing")
    write("ios/Podfile", podfile)

    app_framework = read("ios/Flutter/AppFrameworkInfo.plist")
    if app_framework.count("<string>12.0</string>") != 1:
        raise RuntimeError("AppFrameworkInfo.plist: minimum version pre-image missing")
    write(
        "ios/Flutter/AppFrameworkInfo.plist",
        app_framework.replace("<string>12.0</string>", "<string>15.0</string>"),
    )

    project_path = "ios/Runner.xcodeproj/project.pbxproj"
    project = read(project_path)
    project = project.replace(
        "IPHONEOS_DEPLOYMENT_TARGET = 12.0;",
        "IPHONEOS_DEPLOYMENT_TARGET = 15.0;",
    ).replace(
        "IPHONEOS_DEPLOYMENT_TARGET = 13.0;",
        "IPHONEOS_DEPLOYMENT_TARGET = 15.0;",
    )
    project = project.replace(
        "com.example.demoAiEven",
        "org.trillionnium.heptaglasses",
    )
    project = re.sub(r"\n\s*DEVELOPMENT_TEAM = [A-Z0-9]+;", "", project)
    write(project_path, project)

    replace_once(
        "android/app/build.gradle",
        '        applicationId = "com.example.demo_ai_even"\n',
        '        applicationId = "org.trillionnium.heptaglasses"\n',
    )
    replace_once(
        "android/app/build.gradle",
        '        release {\n'
        '            // TODO: Add your own signing config for the release build.\n'
        '            // Signing with the debug keys for now, so `flutter run --release` works.\n'
        '            signingConfig = signingConfigs.debug\n'
        '        }\n',
        '        release {\n'
        '            // Product signing is injected by the release pipeline.\n'
        '            // Never fall back to the debug key for a distributable build.\n'
        '            signingConfig = null\n'
        '        }\n',
    )

    print("G4 CI normalization patch applied")


if __name__ == "__main__":
    main()
