from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.qualification.sbom import (
    build_sbom,
    canonical_digest,
    inventory_summary,
)


class SbomTest(unittest.TestCase):
    def test_builds_deterministic_multi_ecosystem_spdx_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib/example.dart").write_text(
                "void main() {}\n",
                encoding="utf-8",
            )
            (root / "pubspec.yaml").write_text(
                "name: hepta_glasses\nversion: 0.3.0+3\n",
                encoding="utf-8",
            )
            (root / "pubspec.lock").write_text(
                'packages:\n  crypto:\n    version: "3.0.7"\n',
                encoding="utf-8",
            )

            (root / "ios").mkdir()
            (root / "ios/Podfile.lock").write_text(
                "PODS:\n"
                "  - Flutter (1.0.0)\n\n"
                "DEPENDENCIES:\n"
                "  - Flutter (from `Flutter`)\n\n"
                "COCOAPODS: 1.17.0\n",
                encoding="utf-8",
            )

            (root / "android/app").mkdir(parents=True)
            (root / "android/gradle/wrapper").mkdir(parents=True)
            (root / "android/settings.gradle").write_text(
                'plugins {\n'
                '    id "com.android.application" version "8.11.1" apply false\n'
                '}\n',
                encoding="utf-8",
            )
            (root / "android/app/build.gradle").write_text(
                "dependencies {\n"
                "    implementation 'org.jetbrains.kotlin:kotlin-reflect:2.2.20'\n"
                "}\n",
                encoding="utf-8",
            )
            (root / "android/gradle/wrapper/gradle-wrapper.properties").write_text(
                "distributionUrl=https\\://services.gradle.org/distributions/"
                "gradle-8.14.3-bin.zip\n",
                encoding="utf-8",
            )

            (root / "vendor/component").mkdir(parents=True)
            (root / "vendor/component/source.c").write_text(
                "/* Apache-2.0 */\n",
                encoding="utf-8",
            )
            (root / "third_party").mkdir()
            (root / "third_party/components.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "components": [
                            {
                                "name": "example-vendored",
                                "supplier": "Organization: Example",
                                "license": "Apache-2.0",
                                "download_location": "https://example.invalid/source",
                                "paths": ["vendor/component"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            first = build_sbom(root, document_name="test", namespace="urn:test")
            second = build_sbom(root, document_name="test", namespace="urn:test")
            self.assertEqual(canonical_digest(first), canonical_digest(second))
            self.assertEqual(first["spdxVersion"], "SPDX-2.3")
            self.assertEqual(first["packages"][0]["name"], "hepta_glasses")

            summary = inventory_summary(first)
            self.assertGreaterEqual(summary["file_count"], 8)
            self.assertGreaterEqual(summary["package_count"], 8)
            self.assertEqual(summary["vendored_component_count"], 1)
            self.assertEqual(summary["ecosystem_counts"]["pub"], 1)
            self.assertEqual(summary["ecosystem_counts"]["cocoapods"], 1)
            self.assertEqual(summary["ecosystem_counts"]["gradle-plugin"], 1)
            self.assertEqual(summary["ecosystem_counts"]["maven"], 1)
            self.assertGreaterEqual(summary["ecosystem_counts"]["build-tool"], 2)

            vendored = next(
                package
                for package in first["packages"]
                if package.get("comment") == "ecosystem: vendored"
            )
            self.assertEqual(vendored["licenseDeclared"], "Apache-2.0")
            self.assertEqual(len(vendored["checksums"][0]["checksumValue"]), 64)
            self.assertTrue(
                any(
                    relationship["spdxElementId"] == vendored["SPDXID"]
                    and relationship["relationshipType"] == "CONTAINS"
                    for relationship in first["relationships"]
                )
            )

    def test_rejects_third_party_path_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pubspec.yaml").write_text(
                "name: test\nversion: 1.0.0\n",
                encoding="utf-8",
            )
            (root / "third_party").mkdir()
            (root / "third_party/components.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "components": [
                            {
                                "name": "escape",
                                "supplier": "NOASSERTION",
                                "license": "NOASSERTION",
                                "download_location": "NOASSERTION",
                                "paths": ["../outside"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                build_sbom(root, document_name="test", namespace="urn:test")


if __name__ == "__main__":
    unittest.main()
