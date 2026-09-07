from __future__ import annotations

import json
import unittest

from services.control_plane.authenticated_principals import (
    ActivePairBinding,
    AuthenticatedPrincipalAdapter,
    PrincipalAdapterError,
    VerifiedAccessClaims,
)
from services.control_plane.durable_realtime import DurableRealtimeError
from services.model_gateway.realtime_ingress import (
    DEFAULT_AUDIENCE,
    REQUIRED_SCOPE,
    AuthenticatedRealtimeIngress,
    RealtimeIngressError,
    RealtimePrincipal,
)


class Identity:
    def __init__(self, principal: RealtimePrincipal) -> None:
        self.principal = principal
        self.calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def verify(
        self,
        *,
        bearer_token: str,
        audience: str,
        required_scope: str,
    ) -> RealtimePrincipal:
        self.calls.append(
            {
                "bearer_token": bearer_token,
                "audience": audience,
                "required_scope": required_scope,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.principal


class Store:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure: DurableRealtimeError | None = None
        self.ticket: object = "bootstrap-ticket-123456789"
        self.row: object = {
            "session_id": "identity-session-1",
            "subject": "subject-1",
            "state": "active",
            "generation": 1,
            "provider_session_id": "provider-session-1",
            "provider_receipt_id": "provider-receipt-1",
        }

    def _call(self, name: str, values: dict[str, object]) -> object:
        self.calls.append((name, values))
        if self.failure is not None:
            raise self.failure
        return self.row

    def issue_ticket(self, *, subject: str, session_id: str) -> str:
        self.calls.append(
            ("issue_ticket", {"subject": subject, "session_id": session_id})
        )
        if self.failure is not None:
            raise self.failure
        return self.ticket  # type: ignore[return-value]

    def activate(self, **values: object) -> object:
        return self._call("activate", dict(values))

    def reconcile(self, session_id: str, **values: object) -> object:
        return self._call(
            "reconcile",
            {"session_id": session_id, **values},
        )

    def revoke(self, session_id: str, **values: object) -> object:
        return self._call(
            "revoke",
            {"session_id": session_id, **values},
        )


class SequenceClock:
    def __init__(self, *values: int) -> None:
        self.values = list(values)

    def __call__(self) -> int:
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class Access:
    def __init__(self, claims: VerifiedAccessClaims) -> None:
        self.claims = claims
        self.failure: Exception | None = None
        self.calls: list[tuple[str, str, str]] = []

    def verify_access(
        self,
        *,
        bearer_token: str,
        audience: str,
        required_scope: str,
    ) -> VerifiedAccessClaims:
        self.calls.append((bearer_token, audience, required_scope))
        if self.failure is not None:
            raise self.failure
        return self.claims


class Pairs:
    def __init__(self, binding: ActivePairBinding) -> None:
        self.binding = binding
        self.failure: Exception | None = None
        self.calls: list[tuple[str, str, str]] = []

    def resolve_pair(
        self,
        *,
        subject: str,
        device_id: str,
        session_id: str,
    ) -> ActivePairBinding:
        self.calls.append((subject, device_id, session_id))
        if self.failure is not None:
            raise self.failure
        return self.binding


class AuthenticatedRealtimeIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = RealtimePrincipal(
            subject="subject-1",
            device_id="g1-pair-1",
            session_id="identity-session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            expires_at=200,
        )
        self.identity = Identity(self.principal)
        self.store = Store()
        self.ingress = AuthenticatedRealtimeIngress(
            store=self.store,  # type: ignore[arg-type]
            identity=self.identity,
            clock=lambda: 100,
        )

    @staticmethod
    def authorization() -> str:
        return "Bearer account-session-token-123456"

    def error(self, code: str, status: int, callback) -> None:
        with self.assertRaises(RealtimeIngressError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, status)

    def test_issue_derives_subject_device_and_session_from_identity(self) -> None:
        result = self.ingress.issue(
            authorization=self.authorization(),
            body=b"{}",
        )
        self.assertEqual(
            result,
            {
                "session_id": "identity-session-1",
                "device_id": "g1-pair-1",
                "ticket": "bootstrap-ticket-123456789",
            },
        )
        self.assertEqual(
            self.store.calls,
            [
                (
                    "issue_ticket",
                    {
                        "subject": "subject-1",
                        "session_id": "identity-session-1",
                    },
                )
            ],
        )
        self.assertEqual(
            self.identity.calls,
            [
                {
                    "bearer_token": "account-session-token-123456",
                    "audience": DEFAULT_AUDIENCE,
                    "required_scope": REQUIRED_SCOPE,
                }
            ],
        )

    def test_activate_readback_and_revoke_are_exact_session_bound(self) -> None:
        activated = self.ingress.activate(
            authorization=self.authorization(),
            body=json.dumps(
                {"ticket": "bootstrap-ticket-123456789"},
                separators=(",", ":"),
            ).encode(),
            timeout_seconds=4,
        )
        self.assertEqual(activated["session_id"], "identity-session-1")
        self.assertEqual(activated["device_id"], "g1-pair-1")
        self.assertEqual(activated["state"], "active")
        self.ingress.reconcile(
            authorization=self.authorization(),
            body=b"{}",
            timeout_seconds=3,
        )
        self.ingress.revoke(
            authorization=self.authorization(),
            body=b"{}",
            timeout_seconds=2,
        )
        self.assertEqual(
            self.store.calls,
            [
                (
                    "activate",
                    {
                        "ticket": "bootstrap-ticket-123456789",
                        "subject": "subject-1",
                        "session_id": "identity-session-1",
                        "timeout_seconds": 4.0,
                    },
                ),
                (
                    "reconcile",
                    {
                        "session_id": "identity-session-1",
                        "timeout_seconds": 3.0,
                    },
                ),
                (
                    "revoke",
                    {
                        "session_id": "identity-session-1",
                        "timeout_seconds": 2.0,
                    },
                ),
            ],
        )

    def test_client_authority_fields_and_duplicate_json_fail_before_identity(self) -> None:
        for body in (
            b'{"subject":"attacker"}',
            b'{"session_id":"attacker"}',
            b'{"ticket":"a","ticket":"b"}',
        ):
            self.error(
                "realtime_ingress_request_shape_invalid"
                if b"subject" in body or b"session_id" in body
                else "realtime_ingress_json_invalid",
                400,
                lambda body=body: self.ingress.activate(
                    authorization=self.authorization(),
                    body=body,
                ),
            )
        self.assertEqual(self.identity.calls, [])
        self.assertEqual(self.store.calls, [])

    def test_expired_or_malformed_identity_fails_before_store(self) -> None:
        self.identity.principal = RealtimePrincipal(
            subject="subject-1",
            device_id="g1-pair-1",
            session_id="identity-session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            expires_at=100,
        )
        self.error(
            "realtime_ingress_unauthorized",
            401,
            lambda: self.ingress.issue(
                authorization=self.authorization(),
                body=b"{}",
            ),
        )
        self.identity.principal = object()  # type: ignore[assignment]
        self.error(
            "realtime_ingress_unauthorized",
            401,
            lambda: self.ingress.issue(
                authorization=self.authorization(),
                body=b"{}",
            ),
        )
        self.assertEqual(self.store.calls, [])

    def test_durable_errors_are_sanitized_and_mapped(self) -> None:
        self.store.failure = DurableRealtimeError("realtime_ticket_replayed")
        self.error(
            "realtime_ticket_replayed",
            409,
            lambda: self.ingress.activate(
                authorization=self.authorization(),
                body=b'{"ticket":"bootstrap-ticket-123456789"}',
            ),
        )
        self.store.failure = DurableRealtimeError("realtime_capacity_exhausted")
        self.error(
            "realtime_capacity_exhausted",
            429,
            lambda: self.ingress.issue(
                authorization=self.authorization(),
                body=b"{}",
            ),
        )

    def test_unbound_store_response_is_rejected(self) -> None:
        self.store.row = {
            "session_id": "other-session",
            "subject": "subject-1",
            "state": "active",
            "generation": 1,
            "provider_session_id": "provider-session-1",
            "provider_receipt_id": "provider-receipt-1",
        }
        self.error(
            "realtime_ingress_response_invalid",
            503,
            lambda: self.ingress.activate(
                authorization=self.authorization(),
                body=b'{"ticket":"bootstrap-ticket-123456789"}',
            ),
        )

    def test_unified_principal_adapter_binds_realtime_to_fresh_active_pair(self) -> None:
        claims = VerifiedAccessClaims(
            subject="subject-1",
            device_id="phone-1",
            session_id="identity-session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            expires_at=200,
            policy_hash="a" * 64,
            user_present=True,
            biometric_verified=False,
        )
        pair = ActivePairBinding(
            subject="subject-1",
            device_id="phone-1",
            session_id="identity-session-1",
            pair_identity="g1-pair-1",
            active=True,
            expires_at=150,
        )
        access = Access(claims)
        pairs = Pairs(pair)
        adapter = AuthenticatedPrincipalAdapter(
            access=access,
            pairs=pairs,
            clock=SequenceClock(100, 101),
        )
        principal = adapter.verify(
            bearer_token="account-session-token-123456",
            audience=DEFAULT_AUDIENCE,
            required_scope=REQUIRED_SCOPE,
        )
        self.assertEqual(
            principal,
            RealtimePrincipal(
                subject="subject-1",
                device_id="g1-pair-1",
                session_id="identity-session-1",
                audience=DEFAULT_AUDIENCE,
                scopes=(REQUIRED_SCOPE,),
                expires_at=150,
            ),
        )
        self.assertEqual(
            pairs.calls,
            [("subject-1", "phone-1", "identity-session-1")],
        )

    def test_pair_lookup_exception_and_clock_rollback_fail_closed(self) -> None:
        claims = VerifiedAccessClaims(
            subject="subject-1",
            device_id="phone-1",
            session_id="identity-session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            expires_at=200,
            policy_hash="a" * 64,
            user_present=True,
            biometric_verified=False,
        )
        pair = ActivePairBinding(
            subject="subject-1",
            device_id="phone-1",
            session_id="identity-session-1",
            pair_identity="g1-pair-1",
            active=True,
            expires_at=150,
        )
        access = Access(claims)
        pairs = Pairs(pair)
        pairs.failure = RuntimeError("sensitive pair error")
        adapter = AuthenticatedPrincipalAdapter(
            access=access,
            pairs=pairs,
            clock=SequenceClock(100),
        )
        with self.assertRaises(PrincipalAdapterError) as raised:
            adapter.verify(
                bearer_token="account-session-token-123456",
                audience=DEFAULT_AUDIENCE,
                required_scope=REQUIRED_SCOPE,
            )
        self.assertEqual(raised.exception.code, "identity_pair_denied")
        self.assertNotIn("sensitive", str(raised.exception))

        pairs.failure = None
        adapter = AuthenticatedPrincipalAdapter(
            access=access,
            pairs=pairs,
            clock=SequenceClock(100, 99),
        )
        with self.assertRaises(PrincipalAdapterError) as raised:
            adapter.verify(
                bearer_token="account-session-token-123456",
                audience=DEFAULT_AUDIENCE,
                required_scope=REQUIRED_SCOPE,
            )
        self.assertEqual(raised.exception.code, "identity_clock_invalid")


if __name__ == "__main__":
    unittest.main()
