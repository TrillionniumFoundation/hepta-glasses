"""Authenticated service ingress for durable realtime activation custody.

The request body cannot choose subject, device, identity-session authority,
provider binding or scopes.  The injected identity verifier must derive those
facts from current durable identity/session/revocation state.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from services.control_plane.durable_realtime import (
    DurableRealtimeError,
    DurableRealtimeStore,
)

MAX_REQUEST_BYTES = 4096
MAX_BEARER_BYTES = 8192
DEFAULT_AUDIENCE = "hepta-realtime-gateway"
REQUIRED_SCOPE = "realtime.connect"


class RealtimeIngressError(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class RealtimePrincipal:
    subject: str
    device_id: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    expires_at: int


class RealtimeIdentityVerifier(Protocol):
    def verify(
        self,
        *,
        bearer_token: str,
        audience: str,
        required_scope: str,
    ) -> RealtimePrincipal: ...


class AuthenticatedRealtimeIngress:
    """Expose issue/activate/readback/revoke without client-selected authority."""

    def __init__(
        self,
        *,
        store: DurableRealtimeStore,
        identity: RealtimeIdentityVerifier,
        clock,
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        required_store = ("issue_ticket", "activate", "reconcile", "revoke")
        if any(not callable(getattr(store, name, None)) for name in required_store):
            raise RealtimeIngressError("realtime_ingress_store_invalid", 500)
        if not callable(getattr(identity, "verify", None)):
            raise RealtimeIngressError("realtime_ingress_identity_invalid", 500)
        if not callable(clock):
            raise RealtimeIngressError("realtime_ingress_clock_invalid", 500)
        self._identifier(audience, "realtime_ingress_configuration_invalid")
        self.store = store
        self.identity = identity
        self.clock = clock
        self.audience = audience

    def issue(
        self,
        *,
        authorization: str | None,
        body: bytes,
    ) -> dict[str, object]:
        self._empty_request(body)
        principal = self._authorize(authorization)
        try:
            ticket = self.store.issue_ticket(
                subject=principal.subject,
                session_id=principal.session_id,
            )
        except DurableRealtimeError as error:
            raise self._mapped(error.code) from None
        except Exception:
            raise RealtimeIngressError("realtime_ingress_unavailable", 503) from None
        if not self._identifier_value(ticket, maximum=512):
            raise RealtimeIngressError("realtime_ingress_response_invalid", 503)
        return {
            "session_id": principal.session_id,
            "device_id": principal.device_id,
            "ticket": ticket,
        }

    def activate(
        self,
        *,
        authorization: str | None,
        body: bytes,
        timeout_seconds: float = 10,
    ) -> dict[str, object]:
        request = self._request(body, fields={"ticket"})
        ticket = self._identifier(
            request["ticket"],
            "realtime_ingress_ticket_invalid",
            maximum=512,
        )
        principal = self._authorize(authorization)
        timeout = self._timeout(timeout_seconds)
        try:
            row = self.store.activate(
                ticket=ticket,
                subject=principal.subject,
                session_id=principal.session_id,
                timeout_seconds=timeout,
            )
        except DurableRealtimeError as error:
            raise self._mapped(error.code) from None
        except Exception:
            raise RealtimeIngressError("realtime_ingress_unavailable", 503) from None
        return self._session_response(row, principal)

    def reconcile(
        self,
        *,
        authorization: str | None,
        body: bytes,
        timeout_seconds: float = 5,
    ) -> dict[str, object]:
        self._empty_request(body)
        principal = self._authorize(authorization)
        timeout = self._timeout(timeout_seconds)
        try:
            row = self.store.reconcile(
                principal.session_id,
                timeout_seconds=timeout,
            )
        except DurableRealtimeError as error:
            raise self._mapped(error.code) from None
        except Exception:
            raise RealtimeIngressError("realtime_ingress_unavailable", 503) from None
        return self._session_response(row, principal)

    def revoke(
        self,
        *,
        authorization: str | None,
        body: bytes,
        timeout_seconds: float = 5,
    ) -> dict[str, object]:
        self._empty_request(body)
        principal = self._authorize(authorization)
        timeout = self._timeout(timeout_seconds)
        try:
            row = self.store.revoke(
                principal.session_id,
                timeout_seconds=timeout,
            )
        except DurableRealtimeError as error:
            raise self._mapped(error.code) from None
        except Exception:
            raise RealtimeIngressError("realtime_ingress_unavailable", 503) from None
        return self._session_response(row, principal)

    def _authorize(self, authorization: str | None) -> RealtimePrincipal:
        token = self._bearer(authorization)
        try:
            principal = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=REQUIRED_SCOPE,
            )
            principal = self._principal(principal)
        except RealtimeIngressError:
            raise
        except Exception:
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401) from None
        now = self._now()
        if (
            principal.audience != self.audience
            or REQUIRED_SCOPE not in principal.scopes
            or principal.expires_at <= now
        ):
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401)
        return principal

    def _principal(self, value: object) -> RealtimePrincipal:
        if type(value) is not RealtimePrincipal:
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401)
        try:
            self._identifier(value.subject, "realtime_ingress_unauthorized")
            self._identifier(value.device_id, "realtime_ingress_unauthorized")
            self._identifier(value.session_id, "realtime_ingress_unauthorized")
            self._identifier(value.audience, "realtime_ingress_unauthorized")
        except RealtimeIngressError:
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401) from None
        if (
            type(value.scopes) is not tuple
            or not value.scopes
            or len(value.scopes) > 32
            or len(set(value.scopes)) != len(value.scopes)
            or any(
                type(scope) is not str or not 1 <= len(scope) <= 128
                for scope in value.scopes
            )
            or type(value.expires_at) is not int
            or type(value.expires_at) is bool
            or not 0 < value.expires_at <= 253_402_300_799
        ):
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401)
        return value

    def _session_response(
        self,
        value: object,
        principal: RealtimePrincipal,
    ) -> dict[str, object]:
        try:
            row = value if isinstance(value, Mapping) else {
                key: value[key] for key in value.keys()
            }
            session_id = row["session_id"]
            subject = row["subject"]
            state = row["state"]
            generation = row["generation"]
            provider_session_id = row.get("provider_session_id")
            provider_receipt_id = row.get("provider_receipt_id")
        except Exception:
            raise RealtimeIngressError("realtime_ingress_response_invalid", 503) from None
        if (
            session_id != principal.session_id
            or subject != principal.subject
            or state not in {
                "new",
                "activating",
                "indeterminate",
                "active",
                "revoked",
            }
            or type(generation) is not int
            or type(generation) is bool
            or generation < 1
            or (
                provider_session_id is not None
                and not self._identifier_value(provider_session_id)
            )
            or (
                provider_receipt_id is not None
                and not self._identifier_value(provider_receipt_id)
            )
        ):
            raise RealtimeIngressError("realtime_ingress_response_invalid", 503)
        return {
            "session_id": session_id,
            "device_id": principal.device_id,
            "state": state,
            "generation": generation,
            "provider_session_id": provider_session_id,
            "provider_receipt_id": provider_receipt_id,
        }

    def _empty_request(self, body: bytes) -> None:
        if self._request(body, fields=set()):
            raise RealtimeIngressError("realtime_ingress_request_shape_invalid")

    def _request(
        self,
        body: bytes,
        *,
        fields: set[str],
    ) -> dict[str, object]:
        if type(body) is not bytes or not 1 <= len(body) <= MAX_REQUEST_BYTES:
            raise RealtimeIngressError("realtime_ingress_body_invalid", 413)

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise RealtimeIngressError("realtime_ingress_json_invalid")
                result[key] = value
            return result

        try:
            document = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    RealtimeIngressError("realtime_ingress_json_invalid"),
                ),
            )
        except (
            UnicodeError,
            json.JSONDecodeError,
            RealtimeIngressError,
        ):
            raise RealtimeIngressError("realtime_ingress_json_invalid") from None
        if type(document) is not dict or set(document) != fields:
            raise RealtimeIngressError("realtime_ingress_request_shape_invalid")
        return document

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise RealtimeIngressError("realtime_ingress_clock_invalid", 503) from None
        if (
            type(value) is not int
            or type(value) is bool
            or not 0 <= value <= 253_402_300_799
        ):
            raise RealtimeIngressError("realtime_ingress_clock_invalid", 503)
        return value

    @staticmethod
    def _bearer(value: str | None) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401)
        token = value[7:]
        try:
            length = len(token.encode("utf-8"))
        except UnicodeError:
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401) from None
        if (
            not 16 <= length <= MAX_BEARER_BYTES
            or any(ord(character) <= 32 or ord(character) == 127 for character in token)
        ):
            raise RealtimeIngressError("realtime_ingress_unauthorized", 401)
        return token

    @staticmethod
    def _identifier(
        value: object,
        code: str,
        *,
        maximum: int = 256,
    ) -> str:
        if not AuthenticatedRealtimeIngress._identifier_value(
            value,
            maximum=maximum,
        ):
            raise RealtimeIngressError(code)
        return value

    @staticmethod
    def _identifier_value(value: object, *, maximum: int = 256) -> bool:
        return (
            type(value) is str
            and 1 <= len(value) <= maximum
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None
        )

    @staticmethod
    def _timeout(value: object) -> float:
        if (
            type(value) not in (int, float)
            or type(value) is bool
            or not math.isfinite(float(value))
            or not 0 < float(value) <= 60
        ):
            raise RealtimeIngressError("realtime_ingress_timeout_invalid")
        return float(value)

    @staticmethod
    def _mapped(code: str) -> RealtimeIngressError:
        if code in {
            "realtime_ticket_replayed",
            "realtime_session_not_new",
            "realtime_session_revoked_or_stale",
            "realtime_activation_indeterminate",
            "realtime_reconcile_invalid",
        }:
            return RealtimeIngressError(code, 409)
        if code in {
            "realtime_capacity_exhausted",
            "realtime_readback_budget_exhausted",
        }:
            return RealtimeIngressError(code, 429)
        if code in {
            "realtime_binding_invalid",
            "realtime_ticket_invalid",
            "realtime_ticket_expired",
        }:
            return RealtimeIngressError(code, 400)
        return RealtimeIngressError(code, 503)
