from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.external_evidence.core import EvidenceError, verify_public_key


class ExternalEvidencePublicKeyTypeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _run(self, *arguments: str) -> None:
        subprocess.run(
            ["openssl", *arguments],
            check=True,
            capture_output=True,
            timeout=15,
        )

    def test_real_ed25519_public_key_is_accepted(self) -> None:
        private_key = self.root / "ed25519-private.pem"
        public_key = self.root / "ed25519-public.pem"
        self._run("genpkey", "-algorithm", "ED25519", "-out", str(private_key))
        self._run(
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        )

        verify_public_key(
            public_key,
            openssl_binary="openssl",
            label="ed25519-public-key",
        )

    def test_rsa_key_cannot_be_mislabeled_as_ed25519(self) -> None:
        private_key = self.root / "rsa-private.pem"
        public_key = self.root / "rsa-public.pem"
        message = self.root / "message.bin"
        signature = self.root / "signature.bin"
        message.write_bytes(b"hepta external evidence key-type confusion regression")
        self._run(
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:512",
            "-out",
            str(private_key),
        )
        self._run(
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        )
        self._run(
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(message),
            "-out",
            str(signature),
        )
        self.assertEqual(
            len(signature.read_bytes()),
            64,
            "a 512-bit RSA signature demonstrates why signature length alone is insufficient",
        )
        self._run(
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_key),
            "-rawin",
            "-in",
            str(message),
            "-sigfile",
            str(signature),
        )

        with self.assertRaisesRegex(
            EvidenceError,
            "actual Ed25519 public key",
        ):
            verify_public_key(
                public_key,
                openssl_binary="openssl",
                label="mislabeled-rsa-public-key",
            )


if __name__ == "__main__":
    unittest.main()
