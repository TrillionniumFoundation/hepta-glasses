from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import (
    _read_bounded_file,
    read_object,
    validation_snapshot,
    verify_ed25519_bytes,
    verify_ed25519_file,
    verify_public_key,
)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for snapshot tests")
class ExternalEvidenceImmutableSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private_key = self.root / "private.pem"
        self.public_key = self.root / "public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key)],
            check=True,
            capture_output=True,
            timeout=15,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(self.private_key),
                "-pubout",
                "-out",
                str(self.public_key),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )

    def _sign(self, message: Path, signature: Path) -> None:
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(self.private_key),
                "-rawin",
                "-in",
                str(message),
                "-out",
                str(signature),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )

    def test_same_path_is_pinned_to_first_stable_json_bytes(self) -> None:
        path = self.root / "registry.json"
        path.write_text('{"registry_id":"trusted"}', encoding="utf-8")

        @validation_snapshot
        def read_then_replace() -> tuple[dict[str, object], dict[str, object]]:
            first = read_object(path, "registry")
            path.write_text('{"registry_id":"attacker"}', encoding="utf-8")
            second = read_object(path, "registry")
            return first, second

        first, second = read_then_replace()
        self.assertEqual(first, {"registry_id": "trusted"})
        self.assertEqual(second, first)
        self.assertEqual(json.loads(path.read_text()), {"registry_id": "attacker"})

    def test_public_key_verification_uses_digest_phase_snapshot(self) -> None:
        original = self.public_key.read_bytes()
        replacement_private = self.root / "rsa-private.pem"
        replacement_public = self.root / "rsa-public.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:512",
                "-out",
                str(replacement_private),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(replacement_private),
                "-pubout",
                "-out",
                str(replacement_public),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )

        @validation_snapshot
        def cache_then_replace() -> None:
            cached = _read_bounded_file(
                self.public_key,
                label="pinned-public-key",
                maximum=64 * 1024,
            )
            self.assertEqual(cached, original)
            self.public_key.write_bytes(replacement_public.read_bytes())
            verify_public_key(
                self.public_key,
                openssl_binary="openssl",
                label="pinned-public-key",
            )

        cache_then_replace()

    def test_signature_verification_uses_digest_phase_snapshot(self) -> None:
        message = self.root / "message.bin"
        signature = self.root / "signature.bin"
        payload = b"candidate-bound evidence statement"
        message.write_bytes(payload)
        self._sign(message, signature)
        valid_signature = signature.read_bytes()
        self.assertEqual(len(valid_signature), 64)

        @validation_snapshot
        def cache_then_replace() -> None:
            digest_phase = _read_bounded_file(
                signature,
                label="statement-signature",
                maximum=4096,
            )
            self.assertEqual(
                hashlib.sha256(digest_phase).hexdigest(),
                hashlib.sha256(valid_signature).hexdigest(),
            )
            signature.write_bytes(b"z" * 64)
            verify_ed25519_bytes(
                public_key=self.public_key,
                message=payload,
                signature_path=signature,
                openssl_binary="openssl",
                label="statement-signature",
            )

        cache_then_replace()

    def test_artifact_verification_uses_hash_phase_snapshot(self) -> None:
        message = self.root / "artifact.bin"
        signature = self.root / "artifact.sig"
        trusted = b"trusted artifact bytes"
        message.write_bytes(trusted)
        self._sign(message, signature)

        @validation_snapshot
        def hash_then_replace() -> None:
            hashed = _read_bounded_file(
                message,
                label="artifact",
                maximum=1024,
            )
            self.assertEqual(hashed, trusted)
            message.write_bytes(b"attacker replacement")
            verify_ed25519_file(
                public_key=self.public_key,
                message_path=message,
                signature_path=signature,
                openssl_binary="openssl",
                label="artifact",
            )

        hash_then_replace()


if __name__ == "__main__":
    unittest.main()
