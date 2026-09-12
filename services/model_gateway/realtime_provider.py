"""Bounded fixed-endpoint HTTPS adapter for durable realtime custody.

The adapter performs one provider request per method, rejects redirects and
unbound responses, and never persists credentials or provider payloads.  A
service-owned pre-send authority hook runs after TLS connection establishment
and immediately before request bytes are emitted.
"""
from __future__ import annotations

import http.client
import json
import math
import re
import ssl
from typing import Callable, Protocol
from urllib.parse import quote, urlsplit

from services.control_plane.durable_realtime import RealtimeActivation

MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 32_768


class RealtimeProviderError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RealtimeAccessTokenProvider(Protocol):
    def get_token(self) -> str | None: ...


class StaticRealtimeAccessTokenProvider:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def get_token(self) -> str | None:
        return self.token


class UnavailableRealtimeAccessTokenProvider:
    def get_token(self) -> str | None:
        return None


ConnectionFactory = Callable[
    [str, int, ssl.SSLContext, float],
    http.client.HTTPSConnection,
]
PreSendAuthority = Callable[[str, str], None]


def _connection(
    host: str,
    port: int,
    context: ssl.SSLContext,
    timeout: float,
) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(
        host,
        port=port,
        context=context,
        timeout=timeout,
    )


class HttpsRealtimeProvider:
    """Concrete provider exchange for ``DurableRealtimeStore``.

    ``provider_binding`` is the immutable provider/tenant contract identity
    already persisted by the durable store.  The remote API is deliberately
    narrow:

    * ``POST <base>/sessions`` activates one client session;
    * ``GET <base>/sessions/by-client/<session>`` performs readback only; and
    * ``DELETE <base>/sessions/<provider-session>`` requests idempotent revoke.
    """

    def __init__(
        self,
        *,
        base_url: str,
        provider_binding: str,
        token_provider: RealtimeAccessTokenProvider,
        pre_send_authority: PreSendAuthority,
        tls_context: ssl.SSLContext | None = None,
        connection_factory: ConnectionFactory = _connection,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise RealtimeProviderError("realtime_provider_endpoint_invalid")
        if not _identifier(provider_binding):
            raise RealtimeProviderError("realtime_provider_binding_invalid")
        if not callable(getattr(token_provider, "get_token", None)):
            raise RealtimeProviderError("realtime_provider_token_source_invalid")
        if not callable(pre_send_authority) or not callable(connection_factory):
            raise RealtimeProviderError("realtime_provider_configuration_invalid")
        prefix = parsed.path.rstrip("/")
        self._host = parsed.hostname
        self._port = parsed.port or 443
        self._prefix = prefix
        self.provider_binding = provider_binding
        self._token_provider = token_provider
        self._pre_send_authority = pre_send_authority
        self._tls_context = tls_context or ssl.create_default_context()
        self._connection_factory = connection_factory

    def activate(
        self,
        *,
        ticket: str,
        subject: str,
        session_id: str,
        timeout_seconds: float,
    ) -> RealtimeActivation:
        for value in (ticket, subject, session_id):
            if not _identifier(value, maximum=512):
                raise RealtimeProviderError("realtime_provider_request_invalid")
        status, content_type, raw = self._request(
            operation="activate",
            authority_identity=session_id,
            method="POST",
            path=self._path("sessions"),
            payload={
                "ticket": ticket,
                "subject": subject,
                "session_id": session_id,
                "provider_binding": self.provider_binding,
            },
            timeout_seconds=timeout_seconds,
        )
        if status not in (200, 201) or content_type != "application/json":
            raise RealtimeProviderError("realtime_provider_activate_rejected")
        document = self._activation_document(raw)
        if document["session_id"] != session_id:
            raise RealtimeProviderError("realtime_provider_response_binding_invalid")
        return RealtimeActivation(
            provider_session_id=document["provider_session_id"],
            provider_receipt_id=document["provider_receipt_id"],
        )

    def reconcile_activation(
        self,
        *,
        session_id: str,
        timeout_seconds: float,
    ) -> RealtimeActivation | None:
        if not _identifier(session_id):
            raise RealtimeProviderError("realtime_provider_request_invalid")
        status, content_type, raw = self._request(
            operation="readback",
            authority_identity=session_id,
            method="GET",
            path=self._path(
                "sessions/by-client/" + quote(session_id, safe=""),
            ),
            payload=None,
            timeout_seconds=timeout_seconds,
        )
        if status == 404:
            if raw:
                raise RealtimeProviderError("realtime_provider_response_invalid")
            return None
        if status != 200 or content_type != "application/json":
            raise RealtimeProviderError("realtime_provider_readback_rejected")
        document = self._activation_document(raw)
        if document["session_id"] != session_id:
            raise RealtimeProviderError("realtime_provider_response_binding_invalid")
        return RealtimeActivation(
            provider_session_id=document["provider_session_id"],
            provider_receipt_id=document["provider_receipt_id"],
        )

    def revoke(
        self,
        *,
        provider_session_id: str,
        timeout_seconds: float,
    ) -> None:
        if not _identifier(provider_session_id):
            raise RealtimeProviderError("realtime_provider_request_invalid")
        status, content_type, raw = self._request(
            operation="revoke",
            authority_identity=provider_session_id,
            method="DELETE",
            path=self._path(
                "sessions/" + quote(provider_session_id, safe=""),
            ),
            payload={"provider_binding": self.provider_binding},
            timeout_seconds=timeout_seconds,
        )
        if status == 204:
            if raw:
                raise RealtimeProviderError("realtime_provider_response_invalid")
            return
        if status != 200 or content_type != "application/json":
            raise RealtimeProviderError("realtime_provider_revoke_rejected")
        document = _json_object(raw)
        if set(document) != {
            "provider_session_id",
            "provider_binding",
            "state",
        }:
            raise RealtimeProviderError("realtime_provider_response_invalid")
        if (
            document["provider_session_id"] != provider_session_id
            or document["provider_binding"] != self.provider_binding
            or document["state"] != "revoked"
        ):
            raise RealtimeProviderError("realtime_provider_response_binding_invalid")

    def _activation_document(self, raw: bytes) -> dict[str, object]:
        document = _json_object(raw)
        if set(document) != {
            "session_id",
            "provider_session_id",
            "provider_receipt_id",
            "provider_binding",
            "state",
        }:
            raise RealtimeProviderError("realtime_provider_response_invalid")
        if (
            not _identifier(document["session_id"])
            or not _identifier(document["provider_session_id"])
            or not _identifier(document["provider_receipt_id"])
            or document["provider_binding"] != self.provider_binding
            or document["state"] != "active"
        ):
            raise RealtimeProviderError("realtime_provider_response_binding_invalid")
        return document

    def _request(
        self,
        *,
        operation: str,
        authority_identity: str,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        timeout_seconds: float,
    ) -> tuple[int, str | None, bytes]:
        timeout = _timeout(timeout_seconds)
        try:
            token = self._token_provider.get_token()
        except Exception:
            raise RealtimeProviderError("realtime_provider_unauthenticated") from None
        if not _bearer(token):
            raise RealtimeProviderError("realtime_provider_unauthenticated")
        body = b""
        if payload is not None:
            try:
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, UnicodeError):
                raise RealtimeProviderError("realtime_provider_request_invalid") from None
            if len(body) > MAX_REQUEST_BYTES:
                raise RealtimeProviderError("realtime_provider_request_too_large")
        connection = self._connection_factory(
            self._host,
            self._port,
            self._tls_context,
            timeout,
        )
        try:
            connection.connect()
            try:
                self._pre_send_authority(operation, authority_identity)
            except RealtimeProviderError:
                raise
            except Exception:
                raise RealtimeProviderError(
                    "realtime_provider_authority_denied",
                ) from None
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-Hepta-Provider-Binding": self.provider_binding,
            }
            if payload is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            connection.request(
                method,
                path,
                body=body if payload is not None else None,
                headers=headers,
            )
            response = connection.getresponse()
            if response.getheader("Location") is not None:
                raise RealtimeProviderError("realtime_provider_redirect_rejected")
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    declared_length = int(declared)
                except ValueError:
                    raise RealtimeProviderError(
                        "realtime_provider_response_invalid",
                    ) from None
                if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                    raise RealtimeProviderError(
                        "realtime_provider_response_too_large",
                    )
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RealtimeProviderError(
                    "realtime_provider_response_too_large",
                )
            content_type = response.getheader("Content-Type")
            if content_type is not None:
                content_type = content_type.split(";", 1)[0].strip().lower()
            return response.status, content_type, raw
        except RealtimeProviderError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError):
            raise RealtimeProviderError("realtime_provider_unavailable") from None
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _path(self, suffix: str) -> str:
        return f"{self._prefix}/{suffix}" if self._prefix else f"/{suffix}"


def _json_object(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise RealtimeProviderError("realtime_provider_response_invalid")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RealtimeProviderError("realtime_provider_response_invalid")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                RealtimeProviderError("realtime_provider_response_invalid"),
            ),
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        RealtimeProviderError,
    ):
        raise RealtimeProviderError("realtime_provider_response_invalid") from None
    if type(value) is not dict:
        raise RealtimeProviderError("realtime_provider_response_invalid")
    return value


def _identifier(value: object, *, maximum: int = 256) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= maximum
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None
    )


def _bearer(value: object) -> bool:
    return (
        type(value) is str
        and 16 <= len(value) <= 8192
        and all(33 <= ord(character) <= 126 for character in value)
    )


def _timeout(value: object) -> float:
    if (
        type(value) not in (int, float)
        or type(value) is bool
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 60
    ):
        raise RealtimeProviderError("realtime_provider_timeout_invalid")
    return float(value)
