from __future__ import annotations

import hashlib
import unittest

from services.skills.registry import (
    SkillError,
    SkillManifest,
    SkillRegistry,
    SkillState,
    SkillTrustStore,
)


class SkillRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.trust = SkillTrustStore({"dev-1": b"d" * 32})
        self.registry = SkillRegistry(
            trust_store=self.trust,
            allowed_publishers=frozenset({"trillionnium"}),
            allowed_network_domains=frozenset({"calendar.example"}),
        )

    def manifest(self, **updates: object) -> SkillManifest:
        values: dict[str, object] = {
            "skill_id": "calendar-summary",
            "version": "1.0.0",
            "publisher": "trillionnium",
            "entrypoint": "calendar.summary",
            "required_capabilities": frozenset({"calendar.read"}),
            "risk_tier": "R0",
            "data_classes": frozenset({"personal"}),
            "allowed_network_domains": frozenset({"calendar.example"}),
            "timeout_ms": 5_000,
            "package_digest": hashlib.sha256(b"package").hexdigest(),
            "signature_key_id": "dev-1",
            "signature": "",
        }
        values.update(updates)
        unsigned = SkillManifest(**values)  # type: ignore[arg-type]
        return self.trust.sign_development(unsigned)

    def test_signed_skill_installs_and_revokes(self) -> None:
        installed = self.registry.install(
            self.manifest(),
            consented_capabilities=frozenset({"calendar.read"}),
            consented_data_classes=frozenset({"personal"}),
            now=100,
        )
        self.assertEqual(installed.state, SkillState.INSTALLED)
        self.registry.revoke("calendar-summary")
        with self.assertRaises(SkillError) as raised:
            self.registry.resolve("calendar-summary")
        self.assertEqual(raised.exception.code, "skill_revoked")

    def test_tampering_and_r4_fail_closed(self) -> None:
        signed = self.manifest()
        tampered = SkillManifest(
            **{**signed.__dict__, "timeout_ms": 9_999}
        )
        with self.assertRaises(SkillError) as signature:
            self.registry.install(
                tampered,
                consented_capabilities=frozenset({"calendar.read"}),
                consented_data_classes=frozenset({"personal"}),
                now=100,
            )
        self.assertEqual(signature.exception.code, "skill_signature_invalid")

        with self.assertRaises(SkillError) as r4:
            self.registry.install(
                self.manifest(skill_id="flash", risk_tier="R4"),
                consented_capabilities=frozenset({"calendar.read"}),
                consented_data_classes=frozenset({"personal"}),
                now=100,
            )
        self.assertEqual(r4.exception.code, "skill_r4_forbidden")

    def test_upgrade_requires_new_capability_and_data_consent(self) -> None:
        self.registry.install(
            self.manifest(),
            consented_capabilities=frozenset({"calendar.read"}),
            consented_data_classes=frozenset({"personal"}),
            now=100,
        )
        upgraded = self.manifest(
            version="2.0.0",
            required_capabilities=frozenset({"calendar.read", "location.read"}),
            data_classes=frozenset({"personal", "sensitive"}),
        )
        with self.assertRaises(SkillError):
            self.registry.install(
                upgraded,
                consented_capabilities=frozenset({"calendar.read"}),
                consented_data_classes=frozenset({"personal"}),
                now=200,
            )
        installed = self.registry.install(
            upgraded,
            consented_capabilities=frozenset(
                {"calendar.read", "location.read"}
            ),
            consented_data_classes=frozenset({"personal", "sensitive"}),
            now=200,
        )
        self.assertEqual(installed.manifest.version, "2.0.0")


if __name__ == "__main__":
    unittest.main()
