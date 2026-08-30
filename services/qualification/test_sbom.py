from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.qualification.sbom import (
    build_sbom,
    canonical_digest,
    package_ecosystems,
)


class SbomTest(unittest.TestCase):
    def test_builds_deterministic_multi_ecosystem_spdx_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib/example.dart").write_text(
                "void main() {}\n", encoding="utf-8"
            )
            (root / "pubspec.yaml").write_text(
                "name: test\nversion: 1.2.3\n", encoding="utf-8"
            )
            (root / "pubspec.lock").write_text(
                'packages:\n  crypto:\n    version: "3.0.7"\n',
                encoding="utf-8",
            )
            (root / "android/app").mkdir(parents=True)
            (root / "android/app/build.gradle").write_text(
                "dependencies { implementation 'junit:junit:4.13.2' }\n",
                encoding="utf-8",
            )
            (root / "android/gradle/wrapper").mkdir(parents=True)
            (root / "android/gradle/wrapper/gradle-wrapper.properties").write_text(
                "distributionUrl=https\\://services.gradle.org/distributions/"
                "gradle-8.7-all.zip\n",
                encoding="utf-8",
            )
            (root / "ios").mkdir()
            (root / "ios/Podfile.lock").write_text(
                "PODS:\n  - Flutter (1.0.0)\n\nCOCOAPODS: 1.17.0\n",
                encoding="utf-8",
            )
            (root / "native/liblc3").mkdir(parents=True)
            (root / "native/liblc3/lc3.c").write_text(
                "int lc3(void) { return 0; }\n", encoding="utf-8"
            )
            (root / "third_party").mkdir()
            (root / "third_party/native-components.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "components": [
                            {
                                "name": "liblc3",
                                "version": "NOASSERTION",
                                "supplier": "Organization: Google LLC",
                                "license": "Apache-2.0",
                                "purl": "pkg:github/google/liblc3",
                                "upstream_url": "https://github.com/google/liblc3",
                                "source_paths": ["native/liblc3"],
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
            self.assertEqual(
                set(package_ecosystems(first)),
                {
                    "android/gradle",
                    "dart/pub",
                    "ios/cocoapods",
                    "native/vendored",
                },
            )
            names = {package["name"] for package in first["packages"]}
            self.assertIn("crypto", names)
            self.assertIn("junit:junit", names)
            self.assertIn("Flutter", names)
            self.assertIn("liblc3", names)
            self.assertTrue(
                any(
                    item["relationshipType"] == "CONTAINS"
                    for item in first["relationships"]
                )
            )


if __name__ == "__main__":
    unittest.main()
