from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import (
    EvidenceError,
    _stable_read_target,
    safe_artifact_path,
    validation_snapshot,
)


class ExternalEvidenceScopedSnapshotTest(unittest.TestCase):
    def test_artifact_uri_symlink_is_rejected_before_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = root / "trusted.bin"
            alias = root / "report.bin"
            trusted.write_bytes(b"trusted")
            try:
                alias.symlink_to(trusted.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            @validation_snapshot
            def select() -> None:
                safe_artifact_path(
                    root,
                    "artifact://report.bin",
                    label="artifact",
                )

            with self.assertRaisesRegex(EvidenceError, "regular file"):
                select()
            self.assertTrue(alias.is_symlink())
            self.assertEqual(trusted.read_bytes(), b"trusted")

    def test_symlink_target_outside_scope_is_rejected_before_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            root.mkdir()
            outside = Path(directory) / "outside.bin"
            alias = root / "report.bin"
            outside.write_bytes(b"outside-attacker")
            try:
                alias.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            @validation_snapshot
            def select() -> None:
                safe_artifact_path(
                    root,
                    "artifact://report.bin",
                    label="artifact",
                )

            with self.assertRaisesRegex(EvidenceError, "regular file"):
                select()
            self.assertTrue(alias.is_symlink())
            self.assertEqual(outside.read_bytes(), b"outside-attacker")

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
                "non-directory or symbolic-link component",
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
