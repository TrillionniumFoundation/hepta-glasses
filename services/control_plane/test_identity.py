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
        self.devices.register(
            device_id="g1-001",
            subject="user-1",
            attestation_digest=hashlib.sha256(b"attestation").hexdigest(),
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

    def test_rotation_keeps_old_key_until_retired(self) -> None:
        old = self.issue()
        self.keys.rotate(key_id="k2", secret=b"b" * 32)
        new = self.issue()
        self.assertEqual(self.tokens.verify(old, audience="hepta-control-plane").key_id, "k1")
        self.assertEqual(self.tokens.verify(new, audience="hepta-control-plane").key_id, "k2")
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


if __name__ == "__main__":
    unittest.main()
