from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from services.skills.package_vault import (
    EncryptedSkillPackageVault,
    PackageVaultError,
    VerifiedPackage,
)


class Cipher:
    def __init__(self) -> None:
        self.key = b"v" * 32

    def current_key_id(self, *, subject: str) -> str:
        return "vault-key-a"

    def encrypt(self, *, subject: str, key_id: str,
                plaintext: bytes, aad: bytes) -> bytes:
        stream = hashlib.sha256(self.key + subject.encode() + aad).digest()
        body = bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(plaintext))
        return hmac.new(self.key, aad + body, hashlib.sha256).digest() + body

    def decrypt(self, *, subject: str, key_id: str,
                ciphertext: bytes, aad: bytes) -> bytes:
        tag, body = ciphertext[:32], ciphertext[32:]
        if not hmac.compare_digest(
                tag, hmac.new(self.key, aad + body, hashlib.sha256).digest()):
            raise ValueError("integrity")
        stream = hashlib.sha256(self.key + subject.encode() + aad).digest()
        return bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(body))


class PackageVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "packages.sqlite")
        self.now = 100
        self.vault = EncryptedSkillPackageVault(
            self.path, cipher=Cipher(), clock=lambda: self.now
        )
        self.addCleanup(self.vault.close)
        self.bytes = (
            b"import json,sys\n"
            b"value=json.loads(sys.stdin.read())\n"
            b"print(json.dumps({'echo':value},sort_keys=True,separators=(',',':')))\n"
        )
        self.digest = hashlib.sha256(self.bytes).hexdigest()
        self.package = VerifiedPackage(
            package_id="package-a",
            skill_id="echo-skill",
            publisher_id="publisher-a",
            version="1.0.0",
            manifest_digest="a" * 64,
            package_digest=self.digest,
            package_bytes=self.bytes,
        )
        self.policy = "b" * 64

    def install_and_consent(self) -> None:
        self.vault.install(package=self.package, key_subject="package-keyring")
        self.vault.grant_consent(
            subject="subject-a",
            skill_id="echo-skill",
            version="1.0.0",
            package_digest=self.digest,
            capabilities=("calendar.read",),
            policy_digest=self.policy,
            expires_at=500,
        )

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(PackageVaultError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_verified_bytes_are_encrypted_and_exactly_leased(self) -> None:
        self.install_and_consent()
        checks = []
        lease = self.vault.lease(
            subject="subject-a",
            skill_id="echo-skill",
            required_capabilities=("calendar.read",),
            policy_digest=self.policy,
            authorize=lambda: checks.append("checked"),
        )
        self.assertEqual(lease.bytes, self.bytes)
        self.assertEqual(lease.package_digest, self.digest)
        self.assertEqual(lease.capabilities, ("calendar.read",))
        self.assertEqual(checks, ["checked", "checked"])
        self.vault.checkpoint()
        raw = Path(self.path).read_bytes()
        self.assertNotIn(self.bytes, raw)
        self.assertIn(self.digest.encode("ascii"), raw)

    def test_install_is_idempotent_but_version_collision_fails(self) -> None:
        self.vault.install(package=self.package, key_subject="package-keyring")
        self.vault.install(package=self.package, key_subject="package-keyring")
        changed = VerifiedPackage(
            package_id="package-other",
            skill_id="echo-skill",
            publisher_id="publisher-a",
            version="1.0.0",
            manifest_digest="c" * 64,
            package_digest=hashlib.sha256(b"changed").hexdigest(),
            package_bytes=b"changed",
        )
        self.assert_code(
            "skill_vault_version_conflict",
            lambda: self.vault.install(
                package=changed, key_subject="package-keyring"
            ),
        )

    def test_package_digest_is_recomputed_before_storage(self) -> None:
        bad = VerifiedPackage(
            package_id="bad-package",
            skill_id="bad-skill",
            publisher_id="publisher-a",
            version="1.0.0",
            manifest_digest="a" * 64,
            package_digest="d" * 64,
            package_bytes=b"not-that-digest",
        )
        self.assert_code(
            "skill_vault_package_invalid",
            lambda: self.vault.install(
                package=bad, key_subject="package-keyring"
            ),
        )

    def test_consent_is_exact_version_package_policy_and_capability_bound(self) -> None:
        self.install_and_consent()
        for capabilities, policy, code in (
            (("calendar.write",), self.policy, "skill_vault_capability_denied"),
            (("calendar.read",), "c" * 64, "skill_vault_consent_denied"),
        ):
            self.assert_code(
                code,
                lambda capabilities=capabilities, policy=policy: self.vault.lease(
                    subject="subject-a",
                    skill_id="echo-skill",
                    required_capabilities=capabilities,
                    policy_digest=policy,
                    authorize=lambda: None,
                ),
            )
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.vault.lease(
                subject="subject-b",
                skill_id="echo-skill",
                required_capabilities=("calendar.read",),
                policy_digest=self.policy,
                authorize=lambda: None,
            ),
        )

    def test_consent_revoke_is_immediate_and_persistent(self) -> None:
        self.install_and_consent()
        self.vault.revoke_consent(subject="subject-a", skill_id="echo-skill")
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.vault.lease(
                subject="subject-a",
                skill_id="echo-skill",
                required_capabilities=("calendar.read",),
                policy_digest=self.policy,
                authorize=lambda: None,
            ),
        )
        cipher = self.vault.cipher
        self.vault.close()
        self.vault = EncryptedSkillPackageVault(
            self.path, cipher=cipher, clock=lambda: self.now
        )
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.vault.lease(
                subject="subject-a",
                skill_id="echo-skill",
                required_capabilities=("calendar.read",),
                policy_digest=self.policy,
                authorize=lambda: None,
            ),
        )

    def test_package_skill_and_publisher_revocations_are_terminal(self) -> None:
        for kind, identifier in (
            ("package", "package-a"),
            ("skill", "echo-skill"),
            ("publisher", "publisher-a"),
        ):
            with self.subTest(kind=kind):
                path = str(Path(self.temp.name) / f"{kind}.sqlite")
                vault = EncryptedSkillPackageVault(
                    path, cipher=Cipher(), clock=lambda: self.now
                )
                try:
                    vault.install(package=self.package, key_subject="package-keyring")
                    vault.grant_consent(
                        subject="subject-a",
                        skill_id="echo-skill",
                        version="1.0.0",
                        package_digest=self.digest,
                        capabilities=(),
                        policy_digest=self.policy,
                        expires_at=500,
                    )
                    vault.revoke(kind=kind, identifier=identifier)
                    with self.assertRaises(PackageVaultError):
                        vault.lease(
                            subject="subject-a",
                            skill_id="echo-skill",
                            required_capabilities=(),
                            policy_digest=self.policy,
                            authorize=lambda: None,
                        )
                    with self.assertRaises(PackageVaultError):
                        vault.install(package=self.package,
                                      key_subject="package-keyring")
                finally:
                    vault.close()

    def test_ciphertext_and_metadata_tamper_fail_closed(self) -> None:
        self.install_and_consent()
        row = self.vault.db.execute(
            "SELECT ciphertext FROM skill_vault_packages WHERE package_id='package-a'"
        ).fetchone()
        changed = bytearray(row[0])
        changed[-1] ^= 1
        self.vault.db.execute(
            "UPDATE skill_vault_packages SET ciphertext=? WHERE package_id='package-a'",
            (bytes(changed),),
        )
        self.assert_code(
            "skill_vault_integrity_invalid",
            lambda: self.vault.lease(
                subject="subject-a",
                skill_id="echo-skill",
                required_capabilities=("calendar.read",),
                policy_digest=self.policy,
                authorize=lambda: None,
            ),
        )

    def test_expiry_is_checked_after_decryption(self) -> None:
        self.install_and_consent()
        calls = 0

        def authorize() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                self.now = 500

        self.assert_code(
            "skill_vault_authority_revoked",
            lambda: self.vault.lease(
                subject="subject-a",
                skill_id="echo-skill",
                required_capabilities=("calendar.read",),
                policy_digest=self.policy,
                authorize=authorize,
            ),
        )


if __name__ == "__main__":
    unittest.main()
