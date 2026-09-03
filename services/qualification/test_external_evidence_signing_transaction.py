from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.external_evidence import EvidenceError, core, signing, signing_io


class ExternalEvidenceSigningTransactionTest(unittest.TestCase):
    @staticmethod
    def _write(path: Path, data: bytes = b"value") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_private_key_symbolic_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self._write(
                root / "actual.pem",
                b"-----BEGIN PRIVATE KEY-----\ninvalid\n-----END PRIVATE KEY-----\n",
            )
            alias = root / "alias.pem"
            try:
                alias.symlink_to(target.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                ValueError,
                "must reference a regular file",
            ):
                signing_io.read_private_key_snapshot(alias)

    def test_custody_root_symbolic_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual"
            actual.mkdir()
            alias = base / "custody"
            try:
                alias.symlink_to(actual.name, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(
                ValueError,
                "non-directory or symbolic-link component",
            ):
                signing_io.create_scoped_uri_exclusive(
                    alias,
                    "artifact://signature.bin",
                    b"signature",
                    1024,
                    label="linked custody output",
                )
            self.assertFalse((actual / "signature.bin").exists())

    def test_replaced_custody_root_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "custody"
            root.mkdir()
            retired = base / "retired"

            @core.validation_snapshot
            def transaction() -> None:
                core._validate_lexical_directory(root, label="initial custody")
                root.rename(retired)
                root.mkdir()
                signing_io.create_scoped_uri_exclusive(
                    root,
                    "artifact://signature.bin",
                    b"signature",
                    1024,
                    label="replacement custody output",
                )

            with self.assertRaisesRegex(
                EvidenceError,
                "directory object changed during the transaction",
            ):
                transaction()
            self.assertFalse((root / "signature.bin").exists())

    def test_replaced_existing_output_parent_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            parent = root / "outputs"
            parent.mkdir(parents=True)
            retired = root / "retired"

            @core.validation_snapshot
            def transaction() -> None:
                core._validate_lexical_directory(
                    parent,
                    label="initial output parent",
                )
                parent.rename(retired)
                parent.mkdir()
                signing_io.create_scoped_uri_exclusive(
                    root,
                    "artifact://outputs/signature.bin",
                    b"signature",
                    1024,
                    label="replacement output parent",
                )

            with self.assertRaisesRegex(
                EvidenceError,
                "directory object changed during the transaction",
            ):
                transaction()
            self.assertFalse((parent / "signature.bin").exists())

    def test_signature_and_successor_share_one_parent_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "custody"
            parent = root / "outputs"
            parent.mkdir(parents=True)
            retired = root / "retired"

            @core.validation_snapshot
            def transaction() -> None:
                signing_io.create_scoped_uri_exclusive(
                    root,
                    "artifact://outputs/signature.bin",
                    b"signature",
                    1024,
                    label="detached signature",
                )
                parent.rename(retired)
                parent.mkdir()
                signing_io.create_scoped_uri_exclusive(
                    root,
                    "artifact://outputs/successor.json",
                    b"{}\n",
                    1024,
                    label="successor bundle",
                )

            with self.assertRaisesRegex(
                EvidenceError,
                "directory object changed during the transaction",
            ):
                transaction()
            self.assertTrue((retired / "signature.bin").is_file())
            self.assertFalse((parent / "successor.json").exists())

    def test_high_level_authority_operations_are_snapshot_wrapped(self) -> None:
        for function in (
            signing.sign_submission,
            signing.sign_reviewer,
            signing.finalize,
        ):
            with self.subTest(function=function.__name__):
                self.assertIsNotNone(getattr(function, "__wrapped__", None))


if __name__ == "__main__":
    unittest.main()
