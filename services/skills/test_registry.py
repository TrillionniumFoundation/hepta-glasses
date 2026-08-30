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
            allowed_network_domains=frozenset(
                {"calendar.example", "location.example"}
            ),
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

    def install(self, manifest: SkillManifest, *, now: int = 100):
        return self.registry.install(
            manifest,
            consented_capabilities=frozenset({"calendar.read", "location.read"}),
            consented_data_classes=frozenset({"personal", "sensitive"}),
            consented_network_domains=frozenset(
                {"calendar.example", "location.example"}
            ),
            now=now,
        )

    def test_signed_skill_installs_and_revokes(self) -> None:
        installed = self.install(self.manifest())
        self.assertEqual(installed.state, SkillState.INSTALLED)
        self.registry.revoke("calendar-summary")
        with self.assertRaises(SkillError) as raised:
            self.registry.resolve("calendar-summary")
        self.assertEqual(raised.exception.code, "skill_revoked")

    def test_tampering_and_r4_fail_closed(self) -> None:
        signed = self.manifest()
        tampered = SkillManifest(**{**signed.__dict__, "timeout_ms": 9_999})
        with self.assertRaises(SkillError) as signature:
            self.install(tampered)
        self.assertEqual(signature.exception.code, "skill_signature_invalid")

        with self.assertRaises(SkillError) as r4:
            self.install(self.manifest(skill_id="flash", risk_tier="R4"))
        self.assertEqual(r4.exception.code, "skill_r4_forbidden")

    def test_initial_install_requires_explicit_network_domain_consent(self) -> None:
        with self.assertRaises(SkillError) as raised:
            self.registry.install(
                self.manifest(),
                consented_capabilities=frozenset({"calendar.read"}),
                consented_data_classes=frozenset({"personal"}),
                consented_network_domains=frozenset(),
                now=100,
            )
        self.assertEqual(
            raised.exception.code,
            "skill_network_domain_consent_missing",
        )

    def test_upgrade_requires_new_capability_data_and_network_consent(self) -> None:
        self.install(self.manifest())
        upgraded = self.manifest(
            version="2.0.0",
            required_capabilities=frozenset({"calendar.read", "location.read"}),
            data_classes=frozenset({"personal", "sensitive"}),
            allowed_network_domains=frozenset(
                {"calendar.example", "location.example"}
            ),
        )
        with self.assertRaises(SkillError):
            self.registry.install(
                upgraded,
                consented_capabilities=frozenset({"calendar.read"}),
                consented_data_classes=frozenset({"personal"}),
                consented_network_domains=frozenset({"calendar.example"}),
                now=200,
            )
        installed = self.install(upgraded, now=200)
        self.assertEqual(installed.manifest.version, "2.0.0")

    def test_same_version_is_idempotent_but_drift_and_downgrade_fail(self) -> None:
        initial = self.manifest()
        installed = self.install(initial)
        self.assertIs(self.install(initial, now=101), installed)

        with self.assertRaises(SkillError) as drift:
            self.install(
                self.manifest(
                    package_digest=hashlib.sha256(b"different").hexdigest()
                )
            )
        self.assertEqual(drift.exception.code, "skill_version_manifest_conflict")

        self.install(self.manifest(version="2.0.0"), now=200)
        with self.assertRaises(SkillError) as downgrade:
            self.install(self.manifest(version="1.9.9"), now=300)
        self.assertEqual(
            downgrade.exception.code,
            "skill_version_downgrade_forbidden",
        )

    def test_non_canonical_version_is_rejected(self) -> None:
        with self.assertRaises(SkillError) as raised:
            self.install(self.manifest(version="01.0.0"))
        self.assertEqual(raised.exception.code, "skill_version_invalid")


if __name__ == "__main__":
    unittest.main()
