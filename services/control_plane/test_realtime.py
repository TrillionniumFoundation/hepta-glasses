from __future__ import annotations

import hashlib
import unittest

from services.control_plane.identity import (
    DeviceRegistry,
    KeyRing,
    RevocationLedger,
    SlidingWindowRateLimiter,
    TokenService,
)
from services.control_plane.realtime import (
    RealtimeError,
    RealtimeSessionBroker,
    SessionState,
)


class RealtimeBrokerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1_800_000_000
        self.devices = DeviceRegistry()
        self.devices.register(
            device_id="g1-001",
            subject="user-1",
            attestation_digest=hashlib.sha256(b"attestation").hexdigest(),
            now=self.now,
        )
        revocations = RevocationLedger()
        access_ids = iter(["access-1", "access-2"])
        bootstrap_ids = iter(["bootstrap-1", "bootstrap-2"])
        self.access = TokenService(
            issuer="hepta-access",
            key_ring=KeyRing(keys={"a1": b"a" * 32}, active_key_id="a1"),
            devices=self.devices,
            revocations=revocations,
            clock=lambda: self.now,
            token_id_factory=lambda: next(access_ids),
        )
        self.bootstrap = TokenService(
            issuer="hepta-bootstrap",
            key_ring=KeyRing(keys={"b1": b"b" * 32}, active_key_id="b1"),
            devices=self.devices,
            revocations=revocations,
            maximum_ttl_seconds=120,
            clock=lambda: self.now,
            token_id_factory=lambda: next(bootstrap_ids),
        )
        sessions = iter(["realtime-1", "realtime-2"])
        self.broker = RealtimeSessionBroker(
            access_tokens=self.access,
            bootstrap_tokens=self.bootstrap,
            rate_limiter=SlidingWindowRateLimiter(limit=4, window_seconds=60),
            allowed_provider_profiles={"primary", "economy"},
            clock=lambda: self.now,
            session_id_factory=lambda: next(sessions),
        )
        self.access_token = self.access.issue(
            subject="user-1",
            device_id="g1-001",
            audience="hepta-control-plane",
            scopes={"realtime.connect"},
            session_id="mobile-session",
            ttl_seconds=300,
        )

    def test_ticket_is_one_time_and_never_contains_provider_secret(self) -> None:
        ticket = self.broker.issue_ticket(
            access_token=self.access_token,
            requested_scopes={"audio.input", "transcript.delta"},
            provider_profile="primary",
        )
        self.assertNotIn("api_key", ticket.bootstrap_token.lower())
        session = self.broker.activate(ticket.bootstrap_token)
        self.assertEqual(session.state, SessionState.CONNECTING)
        with self.assertRaises(RealtimeError) as replay:
            self.broker.activate(ticket.bootstrap_token)
        self.assertEqual(replay.exception.code, "bootstrap_ticket_replayed")

    def test_barge_in_rotates_generation_and_rejects_stale_events(self) -> None:
        ticket = self.broker.issue_ticket(
            access_token=self.access_token,
            requested_scopes={"audio.input", "audio.output"},
            provider_profile="primary",
        )
        self.broker.activate(ticket.bootstrap_token)
        listening = self.broker.transition(
            ticket.session_id, event="connected", generation=0
        )
        self.assertTrue(listening.microphone_indicator)
        responding = self.broker.transition(
            ticket.session_id, event="response_started", generation=0
        )
        self.assertFalse(responding.microphone_indicator)
        interrupted = self.broker.interrupt(ticket.session_id, generation=0)
        self.assertEqual(interrupted.generation, 1)
        with self.assertRaises(RealtimeError) as stale:
            self.broker.transition(
                ticket.session_id, event="response_completed", generation=0
            )
        self.assertEqual(stale.exception.code, "stale_realtime_generation")
        resumed = self.broker.transition(
            ticket.session_id, event="interrupt_completed", generation=1
        )
        self.assertEqual(resumed.state, SessionState.LISTENING)
        self.assertTrue(resumed.microphone_indicator)

    def test_scope_and_provider_profile_are_allowlisted(self) -> None:
        with self.assertRaises(RealtimeError) as scope:
            self.broker.issue_ticket(
                access_token=self.access_token,
                requested_scopes={"credential.read"},
                provider_profile="primary",
            )
        self.assertEqual(scope.exception.code, "realtime_scope_invalid")
        with self.assertRaises(RealtimeError) as profile:
            self.broker.issue_ticket(
                access_token=self.access_token,
                requested_scopes={"audio.input"},
                provider_profile="arbitrary",
            )
        self.assertEqual(profile.exception.code, "provider_profile_not_allowed")


if __name__ == "__main__":
    unittest.main()
