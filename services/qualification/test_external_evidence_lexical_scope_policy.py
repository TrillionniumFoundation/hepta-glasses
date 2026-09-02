from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence import EvidenceError, safe_artifact_path
from tools.external_evidence import core


class ExternalEvidenceLexicalScopePolicyTest(unittest.TestCase):
    @staticmethod
    def _write(path: Path, payload: bytes = b"evidence") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_regular_lexical_target_is_snapshotted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            target = self._write(root / "artifacts" / "report.json")

            @core.validation_snapshot
            def transaction() -> tuple[Path, bytes]:
                path = safe_artifact_path(
                    root,
                    "artifact://artifacts/report.json",
                    label="regular artifact",
                )
                return path, core._read_bounded_file(
                    path,
                    label="regular artifact",
                    maximum=1024,
                )

            path, payload = transaction()
            self.assertEqual(path, target)
            self.assertEqual(payload, b"evidence")

    def test_symbolic_link_scope_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual"
            self._write(actual / "report.json")
            alias = base / "custody"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                EvidenceError,
                "non-directory or symbolic-link component",
            ):
                safe_artifact_path(
                    alias,
                    "artifact://report.json",
                    label="linked root artifact",
                )

    def test_symbolic_link_parent_inside_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            actual = root / "actual"
            self._write(actual / "report.json")
            alias = root / "alias"
            try:
                alias.symlink_to(actual.name, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                EvidenceError,
                "non-directory or symbolic-link component",
            ):
                safe_artifact_path(
                    root,
                    "artifact://alias/report.json",
                    label="linked parent artifact",
                )

    def test_symbolic_link_final_file_inside_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            target = self._write(root / "actual.json")
            alias = root / "alias.json"
            try:
                alias.symlink_to(target.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                EvidenceError,
                "must reference a regular file",
            ):
                safe_artifact_path(
                    root,
                    "artifact://alias.json",
                    label="linked final artifact",
                )

    def test_direct_bounded_read_rejects_final_file_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self._write(root / "actual.json")
            alias = root / "alias.json"
            try:
                alias.symlink_to(target.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                EvidenceError,
                "must reference a regular file",
            ):
                core._read_bounded_file(
                    alias,
                    label="direct linked read",
                    maximum=1024,
                )

    def test_scope_root_replacement_between_reads_fails_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "custody"
            first = self._write(root / "first.json", b"first")
            second = self._write(root / "second.json", b"original-second")
            retired = base / "retired"

            @core.validation_snapshot
            def transaction() -> None:
                self.assertEqual(
                    core._read_bounded_file(
                        first,
                        label="first generation",
                        maximum=1024,
                    ),
                    b"first",
                )
                root.rename(retired)
                self._write(root / second.name, b"replacement-second")
                core._read_bounded_file(
                    root / second.name,
                    label="replacement generation",
                    maximum=1024,
                )

            with self.assertRaisesRegex(
                EvidenceError,
                "directory object changed during the validation transaction",
            ):
                transaction()

    def test_parent_directory_replacement_between_reads_fails_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            parent = root / "artifacts"
            first = self._write(parent / "first.json", b"first")
            retired = root / "retired-artifacts"

            @core.validation_snapshot
            def transaction() -> None:
                core._read_bounded_file(
                    first,
                    label="first parent generation",
                    maximum=1024,
                )
                parent.rename(retired)
                self._write(parent / "second.json", b"second")
                core._read_bounded_file(
                    parent / "second.json",
                    label="second parent generation",
                    maximum=1024,
                )

            with self.assertRaisesRegex(
                EvidenceError,
                "directory object changed during the validation transaction",
            ):
                transaction()


if __name__ == "__main__":
    unittest.main()
