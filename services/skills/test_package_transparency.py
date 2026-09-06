"""Actual Ed25519/Merkle/SQLite tests; fixture logs are not external evidence."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.skills.package_transparency import (
    PREFIX,
    TransparencyLogKey,
    TransparencyProof,
    TransparencyVerifier,
)
from services.skills.signed_package import (
    PREFIX as PACKAGE_PREFIX,
    PublisherKey,
    SignedSkillError,
    canonical,
    sealed_inputs,
    sha256,
)
from services.skills.signed_registry import InstallConsent, SignedSkillRegistry


def leaf_hash(value: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + value).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def split(size: int) -> int:
    return 1 << ((size - 1).bit_length() - 1)


def root(values: list[bytes]) -> bytes:
    if not values:
        raise ValueError("empty tree")
    if len(values) == 1:
        return leaf_hash(values[0])
    point = split(len(values))
    return node_hash(root(values[:point]), root(values[point:]))


def path(values: list[bytes], index: int) -> tuple[bytes, ...]:
    if len(values) == 1:
        return ()
    point = split(len(values))
    if index < point:
        return path(values[:point], index) + (root(values[point:]),)
    return path(values[point:], index - point) + (root(values[:point]),)


def package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("program.json")
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, b'{"result":"fixture"}')
    return buffer.getvalue()


class TransparencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.publisher_private, cls.publisher_public = cls.keypair()
        cls.log_private, cls.log_public = cls.keypair()
        cls.other_private, cls.other_public = cls.keypair()

    @staticmethod
    def keypair() -> tuple[bytes, bytes]:
        private = subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER"],
            capture_output=True,
            check=True,
            timeout=5,
        ).stdout
        public = subprocess.run(
            ["/usr/bin/openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=private,
            capture_output=True,
            check=True,
            timeout=5,
        ).stdout
        return private, public

    @staticmethod
    def sign(private: bytes, value: bytes, prefix: bytes) -> bytes:
        with sealed_inputs((private, prefix + value)) as descriptors:
            return subprocess.run(
                [
                    "/usr/bin/openssl",
                    "pkeyutl",
                    "-sign",
                    "-keyform",
                    "DER",
                    "-inkey",
                    f"/proc/self/fd/{descriptors[0]}",
                    "-rawin",
                    "-in",
                    f"/proc/self/fd/{descriptors[1]}",
                ],
                pass_fds=descriptors,
                capture_output=True,
                check=True,
                timeout=5,
            ).stdout

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.package = package()
        self.document = self.manifest()
        self.publisher_key = PublisherKey("publisher", self.publisher_public, 900, 2000)
        self.log_key = TransparencyLogKey("primary-log", self.log_public, 900, 1800)
        self.verifier = TransparencyVerifier(
            {"log-v1": self.log_key}, clock=lambda: self.now
        )

    def manifest(self, **changes) -> bytes:
        content = b'{"result":"fixture"}'
        value = {
            "schema_version": 1,
            "skill_id": "pure",
            "version": "1.0.0",
            "publisher": "publisher",
            "key_id": "publisher-v1",
            "entrypoint": "program.json",
            "capabilities": [],
            "data_classes": ["public"],
            "network_domains": [],
            "risk_tier": "R0",
            "timeout_ms": 1000,
            "issued_at": 1000,
            "expires_at": 1500,
            "package_sha256": sha256(self.package),
            "files": [
                {"path": "program.json", "size": len(content), "sha256": sha256(content)}
            ],
            "dependencies": [],
        }
        value.update(changes)
        return canonical(value)

    def proof(
        self,
        document: bytes | None = None,
        *,
        values: list[bytes] | None = None,
        index: int | None = None,
        checkpoint_changes: dict | None = None,
        private: bytes | None = None,
        prefix: bytes = PREFIX,
    ) -> TransparencyProof:
        document = document or self.document
        values = values or [b"before", document, b"after", b"tail"]
        index = values.index(document) if index is None else index
        checkpoint = {
            "schema_version": 1,
            "log_id": "primary-log",
            "key_id": "log-v1",
            "tree_size": len(values),
            "root_sha256": root(values).hex(),
            "issued_at": 1000,
            "expires_at": 1200,
        }
        if checkpoint_changes:
            checkpoint.update(checkpoint_changes)
        raw = canonical(checkpoint)
        return TransparencyProof(
            raw,
            self.sign(private or self.log_private, raw, prefix),
            index,
            path(values, index),
        )

    def registry(self, *, verifier=..., path: str | None = None) -> SignedSkillRegistry:
        if verifier is ...:
            verifier = self.verifier
        registry = SignedSkillRegistry(
            path or str(Path(self.temp.name) / "registry.sqlite"),
            subject="user",
            keys={"publisher-v1": self.publisher_key},
            allowed_capabilities=frozenset(),
            allowed_domains=frozenset(),
            clock=lambda: self.now,
            transparency_verifier=verifier,
        )
        self.addCleanup(registry.close)
        return registry

    def install(self, registry: SignedSkillRegistry | None = None, *,
                document: bytes | None = None, proof: TransparencyProof | None = ...):
        registry = registry or self.registry()
        document = document or self.document
        if proof is ...:
            proof = self.proof(document)
        return registry.install(
            document,
            signature=self.sign(self.publisher_private, document, PACKAGE_PREFIX),
            package=self.package,
            consent=InstallConsent("user", sha256(document), 1400),
            transparency=proof,
        )

    def error(self, code: str, callback) -> None:
        with self.assertRaises(SignedSkillError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_all_positions_in_non_power_of_two_trees_verify(self):
        for size in range(1, 18):
            values = [f"leaf-{value}".encode() for value in range(size)]
            for index, document in enumerate(values):
                with self.subTest(size=size, index=index):
                    proof = self.proof(document, values=values, index=index)
                    verified = self.verifier.verify(document, proof)
                    self.assertEqual(verified.tree_size, size)
                    self.assertEqual(verified.leaf_index, index)
                    self.assertEqual(verified.root_sha256, root(values).hex())

    def test_registry_install_resolve_and_expiry_binding(self):
        registry = self.registry()
        checked = self.install(registry)
        self.assertEqual(checked.consent_expires_at, 1200)
        self.assertEqual(registry.resolve("pure", package=self.package), checked)
        self.now = 1200
        self.error("skill_admission_expired", lambda: registry.resolve("pure", package=self.package))

    def test_manifest_or_inclusion_path_drift_is_rejected(self):
        proof = self.proof()
        self.error(
            "skill_transparency_inclusion_proof_invalid",
            lambda: self.verifier.verify(self.manifest(timeout_ms=2), proof),
        )
        bad = TransparencyProof(proof.checkpoint, proof.signature, proof.leaf_index,
                                proof.audit_path[:-1] + (b"x" * 32,))
        self.error(
            "skill_transparency_inclusion_proof_invalid",
            lambda: self.verifier.verify(self.document, bad),
        )

    def test_tree_index_and_path_shapes_are_strict(self):
        proof = self.proof()
        cases = [
            TransparencyProof(proof.checkpoint, proof.signature, True, proof.audit_path),
            TransparencyProof(proof.checkpoint, proof.signature, 99, proof.audit_path),
            TransparencyProof(proof.checkpoint, proof.signature, proof.leaf_index, list(proof.audit_path)),
            TransparencyProof(proof.checkpoint, proof.signature, proof.leaf_index, (b"short",)),
            TransparencyProof(proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path + (b"x" * 32,)),
        ]
        for value in cases:
            with self.subTest(value=value):
                self.error(
                    "skill_transparency_inclusion_proof_invalid",
                    lambda p=value: self.verifier.verify(self.document, p),
                )

    def test_signature_domain_and_key_are_strict(self):
        self.error(
            "skill_transparency_signature_invalid",
            lambda: self.verifier.verify(
                self.document, self.proof(prefix=b"OTHER-PROTOCOL\n")
            ),
        )
        self.error(
            "skill_transparency_signature_invalid",
            lambda: self.verifier.verify(
                self.document, self.proof(private=self.other_private)
            ),
        )

    def test_log_and_key_binding_mismatch_rejected(self):
        for changes in ({"log_id": "other-log"}, {"key_id": "other-key"}):
            with self.subTest(changes=changes):
                self.error(
                    "skill_transparency_log_key_mismatch",
                    lambda c=changes: self.verifier.verify(
                        self.document, self.proof(checkpoint_changes=c)
                    ),
                )

    def test_checkpoint_time_and_key_lifetime_enforced(self):
        for changes, code in (
            ({"issued_at": 1001, "expires_at": 1100}, "skill_transparency_checkpoint_expired"),
            ({"issued_at": 900, "expires_at": 1000}, "skill_transparency_checkpoint_expired"),
            ({"issued_at": 1000, "expires_at": 1801}, "skill_transparency_checkpoint_outlives_key"),
            ({"issued_at": 1000, "expires_at": 90000}, "skill_transparency_checkpoint_time_invalid"),
        ):
            with self.subTest(changes=changes):
                self.error(
                    code,
                    lambda c=changes: self.verifier.verify(
                        self.document, self.proof(checkpoint_changes=c)
                    ),
                )

    def test_checkpoint_encoding_duplicate_extra_and_boolean_tree_rejected(self):
        proof = self.proof()
        raw = proof.checkpoint
        cases = [
            raw + b" ",
            raw.replace(b'{"expires_at":1200,', b'{"expires_at":1200,"expires_at":1200,'),
            canonical({**json.loads(raw), "extra": True}),
            canonical({**json.loads(raw), "tree_size": True}),
        ]
        for value in cases:
            signature = self.sign(self.log_private, value, PREFIX)
            malformed = TransparencyProof(value, signature, 1, proof.audit_path)
            with self.subTest(value=value[:40]), self.assertRaises(SignedSkillError):
                self.verifier.verify(self.document, malformed)

    def test_required_optional_and_unconfigured_modes(self):
        self.error("skill_transparency_proof_required", lambda: self.install(proof=None))
        optional = TransparencyVerifier(
            {"log-v1": self.log_key}, clock=lambda: self.now, required=False
        )
        checked = self.install(self.registry(verifier=optional, path=str(Path(self.temp.name) / "optional.sqlite")), proof=None)
        self.assertEqual(checked.consent_expires_at, 1400)
        unconfigured = self.registry(verifier=None, path=str(Path(self.temp.name) / "plain.sqlite"))
        self.error("skill_transparency_unconfigured", lambda: self.install(unconfigured))

    def test_registry_public_transparency_binding_cannot_be_reassigned(self):
        registry = self.registry()
        with self.assertRaises(AttributeError):
            registry.transparency_verifier = None
        self.assertIs(registry.transparency_verifier, self.verifier)

    def test_policy_binding_rejects_key_or_requirement_drift(self):
        path_value = str(Path(self.temp.name) / "policy.sqlite")
        self.registry(path=path_value).close()
        different_key = TransparencyVerifier(
            {"log-v1": TransparencyLogKey("primary-log", self.other_public, 900, 1800)},
            clock=lambda: self.now,
        )
        self.error(
            "skill_registry_policy_migration_required",
            lambda: self.registry(verifier=different_key, path=path_value),
        )
        optional = TransparencyVerifier(
            {"log-v1": self.log_key}, clock=lambda: self.now, required=False
        )
        self.error(
            "skill_registry_policy_migration_required",
            lambda: self.registry(verifier=optional, path=path_value),
        )

    def test_duplicate_public_key_alias_and_subclass_bypass_rejected(self):
        with self.assertRaises(SignedSkillError):
            TransparencyVerifier(
                {"log-v1": self.log_key, "log-v2": self.log_key},
                clock=lambda: self.now,
            )

        class Bypass(TransparencyVerifier):
            def verify(self, document, proof):
                return None

        bypass = Bypass({"log-v1": self.log_key}, clock=lambda: self.now)
        self.error(
            "skill_registry_configuration_invalid",
            lambda: self.registry(verifier=bypass),
        )

    def test_verifier_configuration_is_immutable_after_construction(self):
        original_binding = self.verifier.binding
        for attribute, value in (("required", False), ("binding", "0" * 64),
                                 ("_required", False), ("_clock", lambda: 999)):
            with self.subTest(attribute=attribute):
                self.error(
                    "skill_transparency_configuration_immutable",
                    lambda a=attribute, v=value: setattr(self.verifier, a, v),
                )
        self.assertTrue(self.verifier.required)
        self.assertEqual(self.verifier.binding, original_binding)

    def test_verifier_ignores_environment_executable_and_openssl_injection(self):
        with patch.dict(
            os.environ,
            {
                "PATH": "/nonexistent",
                "OPENSSL_CONF": "/nonexistent/attacker.cnf",
                "OPENSSL_MODULES": "/nonexistent/modules",
                "LD_PRELOAD": "/nonexistent/injected.so",
            },
        ):
            result = self.verifier.verify(self.document, self.proof())
        self.assertEqual(result.log_id, "primary-log")

    def test_verifier_uses_absolute_openssl_sanitized_env_and_sealed_inputs(self):
        proof = self.proof()
        original = subprocess.run

        def inspect(command, **kwargs):
            if "-verify" in command:
                import fcntl

                self.assertEqual(command[0], "/usr/bin/openssl")
                self.assertEqual(len(kwargs["pass_fds"]), 3)
                self.assertEqual(kwargs["env"]["OPENSSL_CONF"], "/dev/null")
                for variable in ("LD_PRELOAD", "OPENSSL_MODULES", "PYTHONPATH"):
                    self.assertNotIn(variable, kwargs["env"])
                for descriptor in kwargs["pass_fds"]:
                    seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
                    self.assertTrue(seals & fcntl.F_SEAL_WRITE)
            return original(command, **kwargs)

        with patch(
            "services.skills.package_transparency.subprocess.run",
            side_effect=inspect,
        ):
            result = self.verifier.verify(self.document, proof)
        self.assertEqual(result.checkpoint_sha256, sha256(proof.checkpoint))

    def test_transparency_clock_errors_are_sanitized(self):
        def broken():
            raise RuntimeError("private-clock-marker")

        verifier = TransparencyVerifier({"log-v1": self.log_key}, clock=broken)
        error = None
        try:
            verifier.verify(self.document, self.proof())
        except SignedSkillError as caught:
            error = caught
        self.assertIsNotNone(error)
        self.assertEqual(error.code, "skill_transparency_clock_invalid")
        self.assertIsNone(error.__cause__)
        self.assertNotIn("private-clock-marker", repr(error))

    def test_proof_expiring_during_package_verification_rolls_back(self):
        registry = self.registry()
        short = self.proof(checkpoint_changes={"expires_at": 1001})
        original = registry._verify

        def late(*args):
            result = original(*args)
            self.now = 1001
            return result

        with patch.object(registry, "_verify", side_effect=late):
            self.error(
                "skill_admission_expired",
                lambda: self.install(registry, proof=short),
            )
        self.assertEqual(
            registry.storage.db.execute("SELECT COUNT(*) FROM signed_skill_installed").fetchone()[0],
            0,
        )
        self.assertEqual(registry.verify_local_audit()["events"], 0)

    def test_verified_checkpoint_metadata_is_exact(self):
        proof = self.proof()
        result = self.verifier.verify(self.document, proof)
        self.assertEqual(result.log_id, "primary-log")
        self.assertEqual(result.key_id, "log-v1")
        self.assertEqual(result.checkpoint_sha256, sha256(proof.checkpoint))
        self.assertEqual(result.expires_at, 1200)


if __name__ == "__main__":
    unittest.main()
