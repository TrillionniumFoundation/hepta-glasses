from __future__ import annotations

import hashlib
import unittest

from services.control_plane.identity import (
    DeviceRegistry,
    IdentityError,
    KeyRing,
    RevocationLedger,
    SlidingWindowRateLimiter,
    TokenService,
)


class IdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000
        self.devices = DeviceRegistry()
        self.attestation_digest = hashlib.sha256(b"attestation").hexdigest()
        self.devices.register(
            device_id="g1-001",
            subject="user-1",
            attestation_digest=self.attestation_digest,
            now=self.now,
        )
        self.revocations = RevocationLedger()
        self.keys = KeyRing(keys={"k1": b"a" * 32}, active_key_id="k1")
        ids = iter(["token-1", "token-2", "token-3", "token-4"])
        self.tokens = TokenService(
            issuer="hepta-test",
            key_ring=self.keys,
            devices=self.devices,
            revocations=self.revocations,
            clock=lambda: self.now,
            token_id_factory=lambda: next(ids),
        )

    def issue(self) -> str:
        return self.tokens.issue(
            subject="user-1",
            device_id="g1-001",
            audience="hepta-control-plane",
            scopes={"realtime.connect", "task.read"},
            session_id="session-1",
            ttl_seconds=120,
        )

    def test_short_lived_device_bound_token_round_trip(self) -> None:
        token = self.issue()
        claims = self.tokens.verify(
            token,
            audience="hepta-control-plane",
            required_scopes={"realtime.connect"},
        )
        self.assertEqual(claims.subject, "user-1")
        self.assertEqual(claims.device_id, "g1-001")
        self.assertEqual(claims.token_id, "token-1")

    def test_registration_is_idempotent_but_attestation_drift_is_rejected(self) -> None:
        repeated = self.devices.register(
            device_id="g1-001",
            subject="user-1",
            attestation_digest=self.attestation_digest,
            now=self.now + 10,
        )
        self.assertEqual(repeated.registered_at, self.now)
        with self.assertRaises(IdentityError) as drift:
            self.devices.register(
                device_id="g1-001",
                subject="user-1",
                attestation_digest=hashlib.sha256(b"different").hexdigest(),
                now=self.now + 20,
            )
        self.assertEqual(drift.exception.code, "device_attestation_conflict")

    def test_lost_or_revoked_device_cannot_self_reactivate_by_registering(self) -> None:
        for status in ("lost", "revoked"):
            with self.subTest(status=status):
                devices = DeviceRegistry()
                devices.register(
                    device_id="g1-001",
                    subject="user-1",
                    attestation_digest=self.attestation_digest,
                    now=self.now,
                )
                devices.set_status("g1-001", status)
                with self.assertRaises(IdentityError) as raised:
                    devices.register(
                        device_id="g1-001",
                        subject="user-1",
                        attestation_digest=self.attestation_digest,
                        now=self.now + 1,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "device_reactivation_requires_recovery",
                )
                self.assertEqual(devices.get("g1-001").status, status)


    def test_terminal_status_cannot_be_reactivated_by_status_update(self) -> None:
        for status in ("lost", "revoked"):
            with self.subTest(status=status):
                devices = DeviceRegistry()
                devices.register(
                    device_id="g1-001",
                    subject="user-1",
                    attestation_digest=self.attestation_digest,
                    now=self.now,
                )
                devices.set_status("g1-001", status)
                with self.assertRaises(IdentityError) as raised:
                    devices.set_status("g1-001", "active")
                self.assertEqual(
                    raised.exception.code,
                    "device_reactivation_requires_recovery",
                )
                self.assertEqual(devices.get("g1-001").status, status)

    def test_revoked_status_is_terminal_but_lost_can_escalate(self) -> None:
        devices = DeviceRegistry()
        devices.register(
            device_id="g1-001",
            subject="user-1",
            attestation_digest=self.attestation_digest,
            now=self.now,
        )
        devices.set_status("g1-001", "lost")
        self.assertEqual(devices.set_status("g1-001", "revoked").status, "revoked")
        with self.assertRaises(IdentityError) as raised:
            devices.set_status("g1-001", "lost")
        self.assertEqual(raised.exception.code, "device_revocation_terminal")

    def test_registration_rejects_noncanonical_attestation_digest(self) -> None:
        devices = DeviceRegistry()
        with self.assertRaises(IdentityError) as raised:
            devices.register(
                device_id="g1-002",
                subject="user-1",
                attestation_digest="z" * 64,
                now=self.now,
            )
        self.assertEqual(raised.exception.code, "device_registration_invalid")

    def test_rotation_keeps_old_key_until_retired(self) -> None:
        old = self.issue()
        self.keys.rotate(key_id="k2", secret=b"b" * 32)
        new = self.issue()
        self.assertEqual(
            self.tokens.verify(old, audience="hepta-control-plane").key_id, "k1"
        )
        self.assertEqual(
            self.tokens.verify(new, audience="hepta-control-plane").key_id, "k2"
        )
        self.keys.retire("k1")
        with self.assertRaises(IdentityError) as raised:
            self.tokens.verify(old, audience="hepta-control-plane")
        self.assertEqual(raised.exception.code, "signing_key_unknown")

    def test_device_and_session_revocation_fail_closed(self) -> None:
        token = self.issue()
        claims = self.tokens.verify(token, audience="hepta-control-plane")
        self.revocations.revoke_session(claims.session_id)
        with self.assertRaises(IdentityError) as raised:
            self.tokens.verify(token, audience="hepta-control-plane")
        self.assertEqual(raised.exception.code, "token_revoked")

        token2 = self.tokens.issue(
            subject="user-1",
            device_id="g1-001",
            audience="hepta-control-plane",
            scopes={"task.read"},
            session_id="session-2",
            ttl_seconds=120,
        )
        self.devices.set_status("g1-001", "lost")
        with self.assertRaises(IdentityError) as lost:
            self.tokens.verify(token2, audience="hepta-control-plane")
        self.assertEqual(lost.exception.code, "device_lost")

    def test_scope_and_expiry_are_enforced(self) -> None:
        token = self.issue()
        with self.assertRaises(IdentityError) as scope:
            self.tokens.verify(
                token,
                audience="hepta-control-plane",
                required_scopes={"account.write"},
            )
        self.assertEqual(scope.exception.code, "token_scope_insufficient")
        with self.assertRaises(IdentityError) as expired:
            self.tokens.verify(
                token,
                audience="hepta-control-plane",
                now=self.now + 120,
            )
        self.assertEqual(expired.exception.code, "token_expired")

    def test_rate_limiter_has_a_deterministic_window(self) -> None:
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
        limiter.consume("key", now=100)
        limiter.consume("key", now=101)
        with self.assertRaises(IdentityError):
            limiter.consume("key", now=102)
        limiter.consume("key", now=111)

    def test_wrong_audience_returns_stable_identity_error(self) -> None:
        token = self.issue()
        with self.assertRaises(IdentityError) as raised:
            self.tokens.verify(token, audience="wrong-audience")
        self.assertEqual(raised.exception.code, "token_audience_invalid")


if __name__ == "__main__":
    unittest.main()
