from __future__ import annotations

import unittest
from dataclasses import replace

from services.control_plane.authenticated_principals import (
    ActivePairBinding,
    AuthenticatedPrincipalAdapter,
    PrincipalAdapterError,
    VerifiedAccessClaims,
)
from services.control_plane.mutation_authority import (
    DEFAULT_AUDIENCE as MUTATION_AUDIENCE,
    REQUIRED_SCOPE as MUTATION_SCOPE,
    MutationPrincipal,
)
from services.model_gateway.model_ingress import (
    DEFAULT_AUDIENCE as MODEL_AUDIENCE,
    REQUIRED_SCOPE as MODEL_SCOPE,
    ModelPrincipal,
)
from services.model_gateway.speech_ingress import (
    DEFAULT_AUDIENCE as SPEECH_AUDIENCE,
    REQUIRED_SCOPE as SPEECH_SCOPE,
    SpeechPrincipal,
)


class Access:
    def __init__(self, claims: VerifiedAccessClaims) -> None:
        self.claims = claims
        self.calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def verify_access(self, *, bearer_token: str, audience: str,
                      required_scope: str) -> VerifiedAccessClaims:
        self.calls.append({
            "bearer_token": bearer_token,
            "audience": audience,
            "required_scope": required_scope,
        })
        if self.failure is not None:
            raise self.failure
        return replace(
            self.claims,
            audience=audience,
            scopes=(required_scope,),
        )


class Pairs:
    def __init__(self, binding: ActivePairBinding) -> None:
        self.binding = binding
        self.calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def resolve_pair(self, *, subject: str, device_id: str,
                     session_id: str) -> ActivePairBinding:
        self.calls.append({
            "subject": subject,
            "device_id": device_id,
            "session_id": session_id,
        })
        if self.failure is not None:
            raise self.failure
        return self.binding


class AuthenticatedPrincipalAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1000
        self.claims = VerifiedAccessClaims(
            subject="subject-1",
            device_id="phone-1",
            session_id="session-1",
            audience=MODEL_AUDIENCE,
            scopes=(MODEL_SCOPE,),
            expires_at=1200,
            policy_hash="a" * 64,
            user_present=True,
            biometric_verified=False,
        )
        self.pair = ActivePairBinding(
            subject="subject-1",
            device_id="phone-1",
            session_id="session-1",
            pair_identity="Pair_7",
            active=True,
            expires_at=1100,
        )
        self.access = Access(self.claims)
        self.pairs = Pairs(self.pair)
        self.adapter = AuthenticatedPrincipalAdapter(
            access=self.access,
            pairs=self.pairs,
            clock=lambda: self.now,
        )

    def test_model_principal_uses_access_claims_without_pair_lookup(self) -> None:
        principal = self.adapter.verify(
            bearer_token="account-token-123456789",
            audience=MODEL_AUDIENCE,
            required_scope=MODEL_SCOPE,
        )
        self.assertIsInstance(principal, ModelPrincipal)
        self.assertEqual(principal.subject, "subject-1")
        self.assertEqual(principal.session_id, "session-1")
        self.assertEqual(principal.consent_expires_at, 1200)
        self.assertEqual(self.pairs.calls, [])

    def test_speech_principal_requires_exact_active_pair(self) -> None:
        principal = self.adapter.verify(
            bearer_token="account-token-123456789",
            audience=SPEECH_AUDIENCE,
            required_scope=SPEECH_SCOPE,
        )
        self.assertIsInstance(principal, SpeechPrincipal)
        self.assertEqual(principal.pair_identity, "Pair_7")
        self.assertEqual(self.pairs.calls, [{
            "subject": "subject-1",
            "device_id": "phone-1",
            "session_id": "session-1",
        }])

    def test_mutation_principal_targets_pair_not_registered_phone(self) -> None:
        principal = self.adapter.verify(
            bearer_token="account-token-123456789",
            audience=MUTATION_AUDIENCE,
            required_scope=MUTATION_SCOPE,
        )
        self.assertIsInstance(principal, MutationPrincipal)
        self.assertEqual(principal.device_id, "Pair_7")
        self.assertEqual(principal.expires_at, 1100)
        self.assertTrue(principal.user_present)
        self.assertFalse(principal.biometric_verified)

    def test_unknown_or_crossed_audience_scope_is_rejected_before_access(self) -> None:
        with self.assertRaises(PrincipalAdapterError) as raised:
            self.adapter.verify(
                bearer_token="account-token-123456789",
                audience=MODEL_AUDIENCE,
                required_scope=SPEECH_SCOPE,
            )
        self.assertEqual(raised.exception.code, "identity_audience_scope_invalid")
        self.assertEqual(self.access.calls, [])

    def test_stale_mismatched_or_inactive_pair_fails_closed(self) -> None:
        for binding in (
            replace(self.pair, subject="subject-2"),
            replace(self.pair, session_id="session-2"),
            replace(self.pair, active=False),
            replace(self.pair, expires_at=self.now),
            replace(self.pair, expires_at=1300),
        ):
            self.pairs.binding = binding
            with self.assertRaises(PrincipalAdapterError) as raised:
                self.adapter.verify(
                    bearer_token="account-token-123456789",
                    audience=SPEECH_AUDIENCE,
                    required_scope=SPEECH_SCOPE,
                )
            self.assertEqual(raised.exception.code, "identity_pair_denied")

    def test_access_exception_and_expiry_are_sanitized(self) -> None:
        self.access.failure = RuntimeError("sensitive verifier text")
        with self.assertRaises(PrincipalAdapterError) as raised:
            self.adapter.verify(
                bearer_token="account-token-123456789",
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            )
        self.assertEqual(raised.exception.code, "identity_access_denied")
        self.assertNotIn("sensitive", str(raised.exception))

        self.access.failure = None
        self.access.claims = replace(self.claims, expires_at=self.now)
        with self.assertRaises(PrincipalAdapterError) as expired:
            self.adapter.verify(
                bearer_token="account-token-123456789",
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            )
        self.assertEqual(expired.exception.code, "identity_access_denied")

    def test_invalid_clock_never_returns_a_principal(self) -> None:
        adapter = AuthenticatedPrincipalAdapter(
            access=self.access,
            pairs=self.pairs,
            clock=lambda: True,
        )
        with self.assertRaises(PrincipalAdapterError) as raised:
            adapter.verify(
                bearer_token="account-token-123456789",
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            )
        self.assertEqual(raised.exception.code, "identity_clock_invalid")


if __name__ == "__main__":
    unittest.main()
