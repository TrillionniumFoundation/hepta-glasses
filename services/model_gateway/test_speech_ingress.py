from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.model_gateway.speech import (
    ProductionSpeechGateway,
    ProviderSpeechTicket,
)
from services.model_gateway.speech_ingress import (
    DEFAULT_AUDIENCE,
    REQUIRED_SCOPE,
    SpeechBootstrapIngress,
    SpeechIngressError,
    SpeechPrincipal,
)


class Broker:
    binding_id = "fixture"

    def __init__(self) -> None:
        self.mints: list[dict[str, object]] = []
        self.revokes: list[str] = []

    def mint_ticket(self, **kwargs: object) -> ProviderSpeechTicket:
        self.mints.append(dict(kwargs))
        return ProviderSpeechTicket(
            endpoint="https://speech.example/v1/asr",
            bearer_token="provider-ephemeral-token-123456",
            provider="fixture",
            provider_ticket_id=f"ticket-{len(self.mints)}",
            expires_at=int(kwargs["expires_at"]),
            maximum_audio_bytes=int(kwargs["maximum_audio_bytes"]),
        )

    def revoke_session(self, *, session_id: str, timeout_seconds: float) -> None:
        self.revokes.append(session_id)


class Identity:
    def __init__(self, principal: SpeechPrincipal) -> None:
        self.principal = principal
        self.calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> SpeechPrincipal:
        self.calls.append({
            "bearer_token": bearer_token,
            "audience": audience,
            "required_scope": required_scope,
        })
        if self.failure is not None:
            raise self.failure
        return self.principal


class SpeechIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.broker = Broker()
        self.gateway = ProductionSpeechGateway(
            str(Path(self.temp.name) / "speech.db"),
            broker=self.broker,
            provider_binding="fixture",
            clock=lambda: self.now,
        )
        self.addCleanup(self.gateway.close)
        self.principal = SpeechPrincipal(
            subject="subject-1",
            session_id="session-1",
            pair_identity="Pair_7",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
        )
        self.identity = Identity(self.principal)
        self.ingress = SpeechBootstrapIngress(
            gateway=self.gateway,
            identity=self.identity,
        )

    @staticmethod
    def body(**changes: object) -> bytes:
        document: dict[str, object] = {
            "session_id": "session-1",
            "generation": 9,
            "pair_identity": "Pair_7",
            "locale": "en-US",
        }
        document.update(changes)
        return json.dumps(document, separators=(",", ":")).encode()

    def issue(self, **changes: object) -> dict[str, object]:
        return self.ingress.issue(
            authorization="Bearer client-session-token-123456",
            body=self.body(**changes),
        )

    def error(self, code: str, status: int, callback) -> None:
        with self.assertRaises(SpeechIngressError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, status)

    def test_success_uses_server_principal_and_consumes_before_return(self) -> None:
        response = self.issue()
        self.assertEqual(set(response), {
            "bootstrap_id", "session_id", "generation", "pair_identity",
            "locale", "endpoint", "bearer_token", "provider", "expires_at",
            "maximum_audio_bytes",
        })
        self.assertEqual(response["session_id"], "session-1")
        self.assertEqual(response["generation"], 9)
        self.assertEqual(response["pair_identity"], "Pair_7")
        state = self.gateway.db.execute(
            "SELECT state FROM bootstraps WHERE session_id='session-1'"
        ).fetchone()[0]
        self.assertEqual(state, "consumed")
        self.assertEqual(self.identity.calls, [{
            "bearer_token": "client-session-token-123456",
            "audience": DEFAULT_AUDIENCE,
            "required_scope": REQUIRED_SCOPE,
        }])
        mint = self.broker.mints[0]
        self.assertEqual(mint["subject"], "subject-1")
        self.assertEqual(mint["generation"], 9)
        self.assertEqual(
            mint["pair_identity_digest"],
            hashlib.sha256(b"Pair_7").hexdigest(),
        )
        dump = "\n".join(self.gateway.db.iterdump())
        self.assertNotIn("provider-ephemeral-token", dump)
        self.assertNotIn("client-session-token", dump)

    def test_body_cannot_select_another_session_or_pair(self) -> None:
        self.error(
            "speech_ingress_authority_mismatch",
            403,
            lambda: self.issue(session_id="session-2"),
        )
        self.error(
            "speech_ingress_authority_mismatch",
            403,
            lambda: self.issue(pair_identity="Pair_8"),
        )
        self.assertEqual(self.broker.mints, [])

    def test_scope_and_audience_are_exact(self) -> None:
        self.identity.principal = SpeechPrincipal(
            subject="subject-1",
            session_id="session-1",
            pair_identity="Pair_7",
            audience="other-audience",
            scopes=(REQUIRED_SCOPE,),
        )
        self.error(
            "speech_ingress_authority_mismatch",
            403,
            self.issue,
        )
        self.identity.principal = SpeechPrincipal(
            subject="subject-1",
            session_id="session-1",
            pair_identity="Pair_7",
            audience=DEFAULT_AUDIENCE,
            scopes=("speech.read",),
        )
        self.error(
            "speech_ingress_authority_mismatch",
            403,
            self.issue,
        )

    def test_duplicate_unknown_and_boolean_fields_fail_before_identity(self) -> None:
        duplicate = (
            b'{"session_id":"session-1","session_id":"session-1",'
            b'"generation":9,"pair_identity":"Pair_7","locale":"en-US"}'
        )
        self.error(
            "speech_ingress_json_invalid",
            400,
            lambda: self.ingress.issue(
                authorization="Bearer client-session-token-123456",
                body=duplicate,
            ),
        )
        self.error(
            "speech_ingress_request_shape_invalid",
            400,
            lambda: self.issue(extra=True),
        )
        self.error(
            "speech_ingress_binding_invalid",
            400,
            lambda: self.issue(generation=True),
        )
        self.assertEqual(self.identity.calls, [])
        self.assertEqual(self.broker.mints, [])

    def test_authentication_failure_is_bounded_and_sanitized(self) -> None:
        self.error(
            "speech_ingress_unauthorized",
            401,
            lambda: self.ingress.issue(
                authorization="Basic secret",
                body=self.body(),
            ),
        )
        self.identity.failure = RuntimeError("sensitive upstream text")
        self.error(
            "speech_ingress_unauthorized",
            401,
            self.issue,
        )
        self.assertNotIn("sensitive", str(self.assertRaises))

    def test_retry_after_delivered_or_lost_response_cannot_remint(self) -> None:
        first = self.issue()
        self.assertEqual(first["session_id"], "session-1")
        self.error(
            "speech_bootstrap_replayed",
            409,
            self.issue,
        )
        self.assertEqual(len(self.broker.mints), 1)

    def test_revoked_session_does_not_issue_provider_ticket(self) -> None:
        self.gateway.revoke_session("session-1")
        self.error(
            "speech_session_revoked",
            409,
            self.issue,
        )
        self.assertEqual(self.broker.mints, [])


if __name__ == "__main__":
    unittest.main()
