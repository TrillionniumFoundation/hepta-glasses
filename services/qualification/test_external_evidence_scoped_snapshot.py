from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import (
    _read_bounded_file,
    safe_artifact_path,
    validation_snapshot,
)


class ExternalEvidenceScopedSnapshotTest(unittest.TestCase):
    def test_artifact_uri_symlink_retarget_keeps_first_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = root / "trusted.bin"
            attacker = root / "attacker.bin"
            alias = root / "report.bin"
            trusted.write_bytes(b"trusted")
            attacker.write_bytes(b"attacker")
            try:
                alias.symlink_to(trusted.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            @validation_snapshot
            def validate_twice() -> tuple[bytes, bytes]:
                first_path = safe_artifact_path(
                    root,
                    "artifact://report.bin",
                    label="artifact",
                )
                first = _read_bounded_file(
                    first_path,
                    label="artifact",
                    maximum=1024,
                )
                alias.unlink()
                alias.symlink_to(attacker.name)
                second_path = safe_artifact_path(
                    root,
                    "artifact://report.bin",
                    label="artifact",
                )
                second = _read_bounded_file(
                    second_path,
                    label="artifact",
                    maximum=1024,
                )
                return first, second

            first, second = validate_twice()
            self.assertEqual(first, b"trusted")
            self.assertEqual(second, first)
            self.assertEqual(alias.read_bytes(), b"attacker")


if __name__ == "__main__":
    unittest.main()
