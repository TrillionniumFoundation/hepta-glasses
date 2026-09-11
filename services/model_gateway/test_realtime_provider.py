from __future__ import annotations

import json
import ssl
import unittest

from services.model_gateway.realtime_provider import (
    HttpsRealtimeProvider,
    RealtimeProviderError,
    StaticRealtimeAccessTokenProvider,
)


class Response:
    def __init__(
        self,
        status: int,
        body: bytes = b"",
        *,
        content_type: str | None = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        self.headers.setdefault("Content-Length", str(len(body)))

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)

    def read(self, maximum: int) -> bytes:
        return self.body[:maximum]


class Connection:
    def __init__(self, response: Response, events: list[str]) -> None:
        self.response = response
        self.events = events
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []

    def connect(self) -> None:
        self.events.append("connect")

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.events.append("request")
        self.requests.append((method, path, body, dict(headers or {})))

    def getresponse(self) -> Response:
        self.events.append("response")
        return self.response

    def close(self) -> None:
        self.events.append("close")


class Factory:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = responses
        self.events: list[str] = []
        self.connections: list[Connection] = []
        self.arguments: list[tuple[str, int, ssl.SSLContext, float]] = []

    def __call__(
        self,
        host: str,
        port: int,
        context: ssl.SSLContext,
        timeout: float,
    ) -> Connection:
        self.arguments.append((host, port, context, timeout))
        connection = Connection(self.responses.pop(0), self.events)
        self.connections.append(connection)
        return connection


def activation(
    *,
    session_id: str = "session-1",
    provider_session_id: str = "provider-session-1",
    provider_receipt_id: str = "provider-receipt-1",
    binding: str = "tenant-binding-1",
) -> bytes:
    return json.dumps(
        {
            "session_id": session_id,
            "provider_session_id": provider_session_id,
            "provider_receipt_id": provider_receipt_id,
            "provider_binding": binding,
            "state": "active",
        },
        separators=(",", ":"),
    ).encode()


class HttpsRealtimeProviderTests(unittest.TestCase):
    def provider(
        self,
        responses: list[Response],
        *,
        authority=None,
        token: str | None = "provider-access-token-123456",
    ) -> tuple[HttpsRealtimeProvider, Factory, list[tuple[str, str]]]:
        factory = Factory(responses)
        authority_calls: list[tuple[str, str]] = []

        def check(operation: str, identity: str) -> None:
            authority_calls.append((operation, identity))
            factory.events.append("authority")
            if authority is not None:
                authority(operation, identity)

        return (
            HttpsRealtimeProvider(
                base_url="https://realtime.example/v1/realtime",
                provider_binding="tenant-binding-1",
                token_provider=StaticRealtimeAccessTokenProvider(token),
                pre_send_authority=check,
                connection_factory=factory,
            ),
            factory,
            authority_calls,
        )

    def test_activate_binds_request_response_and_pre_send_order(self) -> None:
        provider, factory, authority = self.provider(
            [Response(201, activation())],
        )
        result = provider.activate(
            ticket="bootstrap-ticket-123456789",
            subject="subject-1",
            session_id="session-1",
            timeout_seconds=4,
        )
        self.assertEqual(result.provider_session_id, "provider-session-1")
        self.assertEqual(result.provider_receipt_id, "provider-receipt-1")
        self.assertEqual(authority, [("activate", "session-1")])
        self.assertEqual(
            factory.events[:4],
            ["connect", "authority", "request", "response"],
        )
        method, path, body, headers = factory.connections[0].requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/realtime/sessions")
        self.assertEqual(headers["X-Hepta-Provider-Binding"], "tenant-binding-1")
        self.assertEqual(headers["Authorization"], "Bearer provider-access-token-123456")
        self.assertEqual(
            json.loads(body or b"{}"),
            {
                "ticket": "bootstrap-ticket-123456789",
                "subject": "subject-1",
                "session_id": "session-1",
                "provider_binding": "tenant-binding-1",
            },
        )
        self.assertEqual(factory.arguments[0][0:2], ("realtime.example", 443))
        self.assertEqual(factory.arguments[0][3], 4.0)

    def test_readback_is_single_bounded_get_and_absence_is_unknown(self) -> None:
        provider, factory, authority = self.provider(
            [Response(200, activation()), Response(404, b"", content_type=None)],
        )
        result = provider.reconcile_activation(
            session_id="session-1",
            timeout_seconds=3,
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            factory.connections[0].requests[0][0:2],
            ("GET", "/v1/realtime/sessions/by-client/session-1"),
        )
        self.assertIsNone(
            provider.reconcile_activation(
                session_id="session-1",
                timeout_seconds=3,
            )
        )
        self.assertEqual(
            authority,
            [("readback", "session-1"), ("readback", "session-1")],
        )
        self.assertEqual(len(factory.connections), 2)

    def test_revoke_accepts_only_bound_terminal_response(self) -> None:
        body = json.dumps(
            {
                "provider_session_id": "provider-session-1",
                "provider_binding": "tenant-binding-1",
                "state": "revoked",
            },
            separators=(",", ":"),
        ).encode()
        provider, factory, authority = self.provider([Response(200, body)])
        provider.revoke(
            provider_session_id="provider-session-1",
            timeout_seconds=2,
        )
        self.assertEqual(authority, [("revoke", "provider-session-1")])
        self.assertEqual(
            factory.connections[0].requests[0][0:2],
            ("DELETE", "/v1/realtime/sessions/provider-session-1"),
        )

    def test_wrong_binding_duplicate_redirect_and_oversize_fail_closed(self) -> None:
        duplicate = (
            b'{"session_id":"session-1","session_id":"session-1",'
            b'"provider_session_id":"provider-session-1",'
            b'"provider_receipt_id":"provider-receipt-1",'
            b'"provider_binding":"tenant-binding-1","state":"active"}'
        )
        cases = [
            Response(200, activation(binding="other-binding")),
            Response(200, duplicate),
            Response(200, activation(), headers={"Location": "https://other.example"}),
            Response(200, b"x" * 32_769, content_type="application/json"),
        ]
        for response in cases:
            provider, _, _ = self.provider([response])
            with self.assertRaises(RealtimeProviderError):
                provider.activate(
                    ticket="bootstrap-ticket-123456789",
                    subject="subject-1",
                    session_id="session-1",
                    timeout_seconds=4,
                )

    def test_invalid_endpoint_token_timeout_and_authority_never_send(self) -> None:
        with self.assertRaises(RealtimeProviderError):
            HttpsRealtimeProvider(
                base_url="http://realtime.example/v1",
                provider_binding="tenant-binding-1",
                token_provider=StaticRealtimeAccessTokenProvider(
                    "provider-access-token-123456",
                ),
                pre_send_authority=lambda _operation, _identity: None,
            )
        provider, factory, _ = self.provider(
            [Response(201, activation())],
            token=None,
        )
        with self.assertRaises(RealtimeProviderError) as raised:
            provider.activate(
                ticket="bootstrap-ticket-123456789",
                subject="subject-1",
                session_id="session-1",
                timeout_seconds=4,
            )
        self.assertEqual(raised.exception.code, "realtime_provider_unauthenticated")
        self.assertEqual(factory.connections, [])

        def deny(_operation: str, _identity: str) -> None:
            raise RuntimeError("sensitive authority detail")

        provider, factory, _ = self.provider(
            [Response(201, activation())],
            authority=deny,
        )
        with self.assertRaises(RealtimeProviderError) as raised:
            provider.activate(
                ticket="bootstrap-ticket-123456789",
                subject="subject-1",
                session_id="session-1",
                timeout_seconds=4,
            )
        self.assertEqual(raised.exception.code, "realtime_provider_authority_denied")
        self.assertNotIn("sensitive", str(raised.exception))
        self.assertEqual(factory.events, ["connect", "authority", "close"])

        provider, _, _ = self.provider([Response(201, activation())])
        with self.assertRaises(RealtimeProviderError) as raised:
            provider.activate(
                ticket="bootstrap-ticket-123456789",
                subject="subject-1",
                session_id="session-1",
                timeout_seconds=float("inf"),
            )
        self.assertEqual(raised.exception.code, "realtime_provider_timeout_invalid")


if __name__ == "__main__":
    unittest.main()
