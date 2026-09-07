from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from services.skills.package_vault import (
    EncryptedSkillPackageVault,
    VerifiedPackage,
)
from services.skills.sandbox_runtime import LinuxBrokerOnlySandbox, SandboxLimits
from services.skills.skill_service import (
    CONSENT_SCOPE,
    DEFAULT_AUDIENCE,
    EXECUTE_SCOPE,
    REVOKE_SCOPE,
    AuthenticatedSkillService,
    SkillPrincipal,
    SkillServiceError,
)


class Cipher:
    key = b"s" * 32

    def current_key_id(self, *, subject: str) -> str:
        return "skill-key-a"

    def encrypt(self, *, subject: str, key_id: str,
                plaintext: bytes, aad: bytes) -> bytes:
        stream = hashlib.sha256(self.key + aad).digest()
        body = bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(plaintext))
        return hmac.new(self.key, aad + body, hashlib.sha256).digest() + body

    def decrypt(self, *, subject: str, key_id: str,
                ciphertext: bytes, aad: bytes) -> bytes:
        tag, body = ciphertext[:32], ciphertext[32:]
        if not hmac.compare_digest(
                tag, hmac.new(self.key, aad + body, hashlib.sha256).digest()):
            raise ValueError("integrity")
        stream = hashlib.sha256(self.key + aad).digest()
        return bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(body))


class Identity:
    def __init__(self) -> None:
        self.subject = "subject-a"
        self.session_id = "session-a"
        self.expires_at = 1_000
        self.revoked = False
        self.calls = []

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> SkillPrincipal:
        self.calls.append(required_scope)
        if self.revoked:
            raise ValueError("revoked")
        return SkillPrincipal(
            subject=self.subject,
            session_id=self.session_id,
            audience=DEFAULT_AUDIENCE,
            scopes=(required_scope,),
            expires_at=self.expires_at,
        )


class SkillServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 100
        self.path = str(Path(self.temp.name) / "skills.sqlite")
        self.vault = EncryptedSkillPackageVault(
            self.path, cipher=Cipher(), clock=lambda: self.now
        )
        self.addCleanup(self.vault.close)
        self.identity = Identity()
        self.service = AuthenticatedSkillService(
            vault=self.vault,
            sandbox=LinuxBrokerOnlySandbox(),
            identity=self.identity,
            clock=lambda: self.now,
        )
        self.authorization = "Bearer authenticated-skill-session-token"
        self.policy = "a" * 64

    @staticmethod
    def package(source: str, *, skill_id: str = "echo-skill") -> VerifiedPackage:
        raw = source.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return VerifiedPackage(
            package_id=skill_id + "-package",
            skill_id=skill_id,
            publisher_id="publisher-a",
            version="1.0.0",
            manifest_digest="b" * 64,
            package_digest=digest,
            package_bytes=raw,
        )

    def install(self, source: str, *, capabilities=(), skill_id="echo-skill"):
        package = self.package(source, skill_id=skill_id)
        self.vault.install(package=package, key_subject="package-keyring")
        self.service.grant_consent(
            authorization=self.authorization,
            skill_id=skill_id,
            version="1.0.0",
            package_digest=package.package_digest,
            capabilities=capabilities,
            policy_digest=self.policy,
            expires_at=900,
        )
        return package

    def assert_code(self, code: str, callback, status: int | None = None) -> None:
        with self.assertRaises(SkillServiceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        if status is not None:
            self.assertEqual(raised.exception.status, status)

    def test_authenticated_subject_grants_consent_and_executes(self) -> None:
        package = self.install(
            "import json,sys\n"
            "value=json.loads(sys.stdin.read())\n"
            "print(json.dumps({'subject_result':value},sort_keys=True,separators=(',',':')))\n"
        )
        result = self.service.execute(
            authorization=self.authorization,
            skill_id=package.skill_id,
            required_capabilities=(),
            policy_digest=self.policy,
            input_value={"value": 7},
            capability_handler=lambda capability, arguments: {},
            limits=SandboxLimits(wall_seconds=3),
        )
        self.assertEqual(result.output, {"subject_result": {"value": 7}})
        self.assertEqual(self.identity.calls[0], CONSENT_SCOPE)
        self.assertIn(EXECUTE_SCOPE, self.identity.calls)

    def test_broker_effect_is_exact_consent_and_identity_bound(self) -> None:
        source = (
            "import json,os,struct\n"
            "fd=int(os.environ['HEPTA_CAPABILITY_FD'])\n"
            "raw=json.dumps({'request_id':'effect-a','capability':'calendar.create',"
            "'arguments':{'title':'meeting'}},sort_keys=True,separators=(',',':')).encode()\n"
            "os.write(fd,struct.pack('>I',len(raw))+raw)\n"
            "size=struct.unpack('>I',os.read(fd,4))[0]\n"
            "body=b''\n"
            "while len(body)<size: body+=os.read(fd,size-len(body))\n"
            "print(json.dumps(json.loads(body),sort_keys=True,separators=(',',':')))\n"
        )
        package = self.install(source, capabilities=("calendar.create",))
        effects = []
        result = self.service.execute(
            authorization=self.authorization,
            skill_id=package.skill_id,
            required_capabilities=("calendar.create",),
            policy_digest=self.policy,
            input_value={},
            capability_handler=lambda capability, arguments: effects.append(
                (capability, dict(arguments))
            ) or {"operation_id": "operation-a"},
        )
        self.assertEqual(
            effects, [("calendar.create", {"title": "meeting"})]
        )
        self.assertTrue(result.output["ok"])
        self.assertEqual(result.output["result"], {"operation_id": "operation-a"})

    def test_missing_capability_or_policy_is_denied_before_execution(self) -> None:
        package = self.install(
            "print('{\"should_not_run\":true}')\n",
            capabilities=("calendar.read",),
        )
        self.assert_code(
            "skill_vault_capability_denied",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=("calendar.write",),
                policy_digest=self.policy,
                input_value={},
                capability_handler=lambda capability, arguments: {},
            ),
            403,
        )
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=("calendar.read",),
                policy_digest="c" * 64,
                input_value={},
                capability_handler=lambda capability, arguments: {},
            ),
            403,
        )

    def test_consent_revoke_prevents_new_execution(self) -> None:
        package = self.install("print('{\"ok\":true}')\n")
        self.service.revoke_consent(
            authorization=self.authorization, skill_id=package.skill_id
        )
        self.assertEqual(self.identity.calls[-1], REVOKE_SCOPE)
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=(),
                policy_digest=self.policy,
                input_value={},
                capability_handler=lambda capability, arguments: {},
            ),
            403,
        )

    def test_live_identity_revoke_terminates_running_task(self) -> None:
        package = self.install(
            "import time\n"
            "while True: time.sleep(.05)\n",
            skill_id="long-skill",
        )
        execute_checks = 0
        original = self.identity.verify

        def verify(**kwargs):
            nonlocal execute_checks
            if kwargs["required_scope"] == EXECUTE_SCOPE:
                execute_checks += 1
                if execute_checks >= 5:
                    self.identity.revoked = True
            return original(**kwargs)

        self.identity.verify = verify
        self.assert_code(
            "skill_authority_revoked",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=(),
                policy_digest=self.policy,
                input_value={},
                capability_handler=lambda capability, arguments: {},
                limits=SandboxLimits(wall_seconds=3),
            ),
            403,
        )
        self.assertGreaterEqual(execute_checks, 5)

    def test_cross_subject_and_expired_identity_fail_closed(self) -> None:
        package = self.install("print('{\"ok\":true}')\n")
        self.identity.subject = "subject-b"
        self.assert_code(
            "skill_vault_consent_denied",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=(),
                policy_digest=self.policy,
                input_value={},
                capability_handler=lambda capability, arguments: {},
            ),
            403,
        )
        self.identity.subject = "subject-a"
        self.identity.expires_at = self.now
        self.assert_code(
            "skill_service_unauthorized",
            lambda: self.service.execute(
                authorization=self.authorization,
                skill_id=package.skill_id,
                required_capabilities=(),
                policy_digest=self.policy,
                input_value={},
                capability_handler=lambda capability, arguments: {},
            ),
            401,
        )

    def test_bearer_and_package_plaintext_are_not_persisted(self) -> None:
        source = "print('{\"PRIVATE-PACKAGE-SENTINEL\":true}')\n"
        self.install(source)
        self.vault.checkpoint()
        raw = Path(self.path).read_bytes()
        self.assertNotIn(self.authorization.encode(), raw)
        self.assertNotIn(source.encode(), raw)


if __name__ == "__main__":
    unittest.main()
