from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import (
    EvidenceError,
    _read_bounded_file,
    _stable_read_target,
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

    def test_retarget_after_path_selection_cannot_change_first_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            root.mkdir()
            trusted = root / "trusted.bin"
            attacker = Path(directory) / "outside.bin"
            alias = root / "report.bin"
            trusted.write_bytes(b"trusted")
            attacker.write_bytes(b"outside-attacker")
            try:
                alias.symlink_to(trusted.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            @validation_snapshot
            def validate_after_retarget() -> bytes:
                selected = safe_artifact_path(
                    root,
                    "artifact://report.bin",
                    label="artifact",
                )
                alias.unlink()
                alias.symlink_to(attacker)
                return _read_bounded_file(
                    selected,
                    label="artifact",
                    maximum=1024,
                )

            self.assertEqual(validate_after_retarget(), b"trusted")
            self.assertEqual(alias.read_bytes(), b"outside-attacker")

    def test_resolved_target_parent_replaced_by_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected_parent = root / "selected"
            retired_parent = root / "retired"
            outside_parent = root / "outside"
            selected_parent.mkdir()
            outside_parent.mkdir()
            target = selected_parent / "report.bin"
            target.write_bytes(b"trusted")
            (outside_parent / "report.bin").write_bytes(b"outside-attacker")
            resolved_target = target.resolve(strict=True)

            selected_parent.rename(retired_parent)
            try:
                selected_parent.symlink_to(
                    outside_parent,
                    target_is_directory=True,
                )
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            with self.assertRaisesRegex(
                EvidenceError,
                "unsafe or replaced directory component",
            ):
                _stable_read_target(
                    resolved_target,
                    label="artifact",
                    maximum=1024,
                )
            self.assertEqual(
                (selected_parent / "report.bin").read_bytes(),
                b"outside-attacker",
            )


if __name__ == "__main__":
    unittest.main()
