from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_key_alias_test_support",
    SUPPORT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence


class ExternalEvidenceKeyAliasTest(support.ExternalEvidenceFixture):
    def test_same_public_key_cannot_be_registered_under_another_identity(self) -> None:
        bundle = self._bundle(["HG-0017"])
        issuer = self.registry_document["keys"][0]
        alternate = self.registry_document["keys"][1]
        alternate["key_id"] = "apparently-independent-key"
        alternate["identity"] = "apparently-independent-reviewer"
        alternate["organization"] = "apparently-independent-organization"
        alternate["public_key_uri"] = issuer["public_key_uri"]
        alternate["public_key_sha256"] = issuer["public_key_sha256"]
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "reuses the cryptographic public key",
        ):
            self._validate(bundle)

    def test_reencoded_same_public_key_is_also_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        issuer = self.registry_document["keys"][0]
        issuer_path = self.key_root / "issuer.public.pem"
        alternate_path = self.key_root / "same-key-reencoded.public.pem"
        # CRLF changes the pinned PEM-byte digest while preserving the DER SPKI.
        alternate_bytes = issuer_path.read_bytes().replace(b"\n", b"\r\n")
        alternate_path.write_bytes(alternate_bytes)

        alternate = self.registry_document["keys"][1]
        alternate["key_id"] = "reencoded-independent-key"
        alternate["identity"] = "reencoded-independent-reviewer"
        alternate["organization"] = "reencoded-independent-organization"
        alternate["public_key_uri"] = f"key://keys/{alternate_path.name}"
        import hashlib

        alternate["public_key_sha256"] = hashlib.sha256(alternate_bytes).hexdigest()
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "reuses the cryptographic public key",
        ):
            self._validate(bundle)


if __name__ == "__main__":
    unittest.main()
