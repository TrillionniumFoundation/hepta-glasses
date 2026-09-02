from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.external_evidence.core as core
import tools.external_evidence.snapshot_io as snapshot_io
import tools.external_evidence.trust as trust_module
from tools.external_evidence.core import (
    EvidenceError,
    _read_bounded_file,
    _stable_read_target,
    safe_artifact_path,
    safe_key_path,
    validation_snapshot,
)


class ExternalEvidenceFilesystemHardeningTest(unittest.TestCase):
    def test_real_directory_replacement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            retired = root / "retired"
            selected.mkdir()
            target = selected / "report.bin"
            target.write_bytes(b"trusted")

            original_open = snapshot_io._open_absolute_regular_nofollow
            raced = False

            def replace_then_open(path: Path, **kwargs: object) -> int:
                nonlocal raced
                if not raced:
                    raced = True
                    selected.rename(retired)
                    selected.mkdir()
                    (selected / "report.bin").write_bytes(b"attacker")
                return original_open(path, **kwargs)

            with patch.object(
                snapshot_io,
                "_open_absolute_regular_nofollow",
                side_effect=replace_then_open,
            ):
                with self.assertRaisesRegex(
                    EvidenceError,
                    "directory identity changed",
                ):
                    _stable_read_target(
                        target,
                        label="artifact",
                        maximum=1024,
                    )

            self.assertEqual((selected / "report.bin").read_bytes(), b"attacker")
            self.assertEqual((retired / "report.bin").read_bytes(), b"trusted")

    def test_scoped_uri_must_be_canonical_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for uri in (
                "artifact://a//b",
                "artifact://a/./b",
                "artifact://a/",
                "artifact://a/../b",
                "artifact://./a",
            ):
                with self.subTest(uri=uri):
                    with self.assertRaisesRegex(
                        EvidenceError,
                        "canonical scoped relative path",
                    ):
                        safe_artifact_path(root, uri, label="artifact")

    def test_validation_snapshot_has_an_aggregate_byte_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first.bin").write_bytes(b"123456")
            (root / "second.bin").write_bytes(b"abcdef")

            @validation_snapshot
            def select_both() -> None:
                first = safe_artifact_path(
                    root,
                    "artifact://first.bin",
                    label="first",
                )
                self.assertEqual(
                    _read_bounded_file(first, label="first", maximum=1024),
                    b"123456",
                )
                safe_artifact_path(
                    root,
                    "artifact://second.bin",
                    label="second",
                )

            with patch.object(snapshot_io, "MAX_SNAPSHOT_BYTES", 10):
                with self.assertRaisesRegex(
                    EvidenceError,
                    "transaction bound",
                ):
                    select_both()

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required")
    def test_spki_normalization_uses_the_pinned_public_key_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_private = root / "first-private.pem"
            first_public = root / "first-public.pem"
            second_private = root / "second-private.pem"
            second_public = root / "second-public.pem"
            subprocess.run(
                [
                    "openssl",
                    "genpkey",
                    "-algorithm",
                    "ED25519",
                    "-out",
                    str(first_private),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-in",
                    str(first_private),
                    "-pubout",
                    "-out",
                    str(first_public),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "genpkey",
                    "-algorithm",
                    "ED25519",
                    "-out",
                    str(second_private),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-in",
                    str(second_private),
                    "-pubout",
                    "-out",
                    str(second_public),
                ],
                check=True,
                capture_output=True,
            )

            alias = root / "authority.pem"
            try:
                alias.symlink_to(first_public.name)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            @validation_snapshot
            def normalize_after_retarget() -> str:
                selected = safe_key_path(
                    root,
                    "key://authority.pem",
                    label="authority public key",
                )
                alias.unlink()
                alias.symlink_to(second_public.name)
                return core._normalized_public_key_digest(
                    selected,
                    openssl_binary="openssl",
                    label="authority public key",
                )

            first_der = subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-in",
                    str(first_public),
                    "-pubout",
                    "-outform",
                    "DER",
                ],
                check=True,
                capture_output=True,
            ).stdout
            second_der = subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-in",
                    str(second_public),
                    "-pubout",
                    "-outform",
                    "DER",
                ],
                check=True,
                capture_output=True,
            ).stdout

            normalized = normalize_after_retarget()
            self.assertEqual(normalized, hashlib.sha256(first_der).hexdigest())
            self.assertNotEqual(normalized, hashlib.sha256(second_der).hexdigest())
            self.assertIs(
                trust_module._normalized_public_key_digest,
                core._normalized_public_key_digest,
            )


if __name__ == "__main__":
    unittest.main()
