"""Authenticated speech-bootstrap ingress with exact request authority.

This module is framework-neutral. A trusted service adapter supplies an identity
verifier and passes the raw Authorization header plus bounded request bytes. The
client body cannot select its subject, session authority, pair authority or
scope. No audio, transcript, provider token or response body is logged here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from services.model_gateway.speech import (
    ProductionSpeechGateway,
    SpeechBootstrap,
    SpeechGatewayError,
)

MAX_REQUEST_BYTES = 4096
MAX_BEARER_BYTES = 8192
REQUIRED_SCOPE = "speech.bootstrap"
DEFAULT_AUDIENCE = "hepta-speech-bootstrap"


class SpeechIngressError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class SpeechPrincipal:
    subject: str
    session_id: str
    pair_identity: str
    audience: str
    scopes: tuple[str, ...]


class SpeechIdentityVerifier(Protocol):
    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> SpeechPrincipal: ...


class SpeechBootstrapIngress:
    """Translate one authenticated request into one consumed bootstrap.

    Authentication must be backed by current identity/session/revocation state.
    A timeout or lost response after dispatch is indeterminate; the caller must
    not retry with the same session ID because the durable gateway prevents a
    second mint. Start a new assistant session only after authorized recovery.
    """

    def __init__(self, *, gateway: ProductionSpeechGateway,
                 identity: SpeechIdentityVerifier,
                 audience: str = DEFAULT_AUDIENCE) -> None:
        if not isinstance(gateway, ProductionSpeechGateway):
            raise SpeechIngressError("speech_ingress_gateway_invalid", 500)
        if not callable(getattr(identity, "verify", None)):
            raise SpeechIngressError("speech_ingress_identity_invalid", 500)
        self._identifier(audience, "speech_ingress_audience_invalid")
        self.gateway = gateway
        self.identity = identity
        self.audience = audience

    def issue(self, *, authorization: str | None, body: bytes,
              timeout_seconds: float = 8) -> dict[str, object]:
        token = self._bearer(authorization)
        request = self._request(body)
        try:
            principal = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=REQUIRED_SCOPE,
            )
            self._principal(principal)
        except SpeechIngressError as error:
            if error.code == "speech_ingress_unauthorized":
                raise SpeechIngressError(
                    "speech_ingress_unauthorized", 401
                ) from None
            raise
        except Exception:
            raise SpeechIngressError("speech_ingress_unauthorized", 401) from None
        if (principal.audience != self.audience
                or REQUIRED_SCOPE not in principal.scopes
                or principal.session_id != request["session_id"]
                or principal.pair_identity != request["pair_identity"]):
            raise SpeechIngressError("speech_ingress_authority_mismatch", 403)

        try:
            bootstrap = self.gateway.bootstrap_for_delivery(
                subject=principal.subject,
                session_id=principal.session_id,
                generation=request["generation"],
                pair_identity=principal.pair_identity,
                locale=request["locale"],
                timeout_seconds=timeout_seconds,
            )
        except SpeechGatewayError as error:
            status = 409 if error.code in {
                "speech_bootstrap_replayed",
                "speech_bootstrap_recovery_required",
                "speech_session_revoked",
            } else 429 if error.code == "speech_quota_exhausted" else 503
            raise SpeechIngressError(error.code, status) from None
        except Exception:
            raise SpeechIngressError("speech_ingress_unavailable", 503) from None
        return self._response(bootstrap)

    def _request(self, body: bytes) -> dict[str, object]:
        if type(body) is not bytes or not 1 <= len(body) <= MAX_REQUEST_BYTES:
            raise SpeechIngressError("speech_ingress_body_invalid", 413)
        try:
            document = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=self._unique_object,
                parse_constant=lambda _: self._json_invalid(),
            )
        except (UnicodeError, json.JSONDecodeError, SpeechIngressError):
            raise SpeechIngressError("speech_ingress_json_invalid") from None
        if type(document) is not dict or set(document) != {
            "session_id", "generation", "pair_identity", "locale"
        }:
            raise SpeechIngressError("speech_ingress_request_shape_invalid")
        session_id = self._identifier(
            document["session_id"], "speech_ingress_binding_invalid"
        )
        pair_identity = self._identifier(
            document["pair_identity"], "speech_ingress_binding_invalid"
        )
        generation = document["generation"]
        locale = document["locale"]
        if (type(generation) is not int or type(generation) is bool
                or not 1 <= generation <= 2_147_483_647
                or type(locale) is not str
                or re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", locale) is None):
            raise SpeechIngressError("speech_ingress_binding_invalid")
        return {
            "session_id": session_id,
            "generation": generation,
            "pair_identity": pair_identity,
            "locale": locale,
        }

    def _principal(self, value: object) -> SpeechPrincipal:
        if type(value) is not SpeechPrincipal:
            raise SpeechIngressError("speech_ingress_unauthorized", 401)
        try:
            self._identifier(value.subject, "speech_ingress_unauthorized")
            self._identifier(value.session_id, "speech_ingress_unauthorized")
            self._identifier(value.pair_identity, "speech_ingress_unauthorized")
            self._identifier(value.audience, "speech_ingress_unauthorized")
        except SpeechIngressError:
            raise SpeechIngressError("speech_ingress_unauthorized", 401) from None
        if (type(value.scopes) is not tuple or not value.scopes
                or len(value.scopes) > 32
                or any(type(scope) is not str or not scope
                       or len(scope) > 128 for scope in value.scopes)
                or len(set(value.scopes)) != len(value.scopes)):
            raise SpeechIngressError("speech_ingress_unauthorized", 401)
        return value

    def _response(self, value: SpeechBootstrap) -> dict[str, object]:
        if type(value) is not SpeechBootstrap:
            raise SpeechIngressError("speech_ingress_response_invalid", 503)
        return {
            "bootstrap_id": value.bootstrap_id,
            "session_id": value.session_id,
            "generation": value.generation,
            "pair_identity": value.pair_identity,
            "locale": value.locale,
            "endpoint": value.endpoint,
            "bearer_token": value.bearer_token,
            "provider": value.provider,
            "expires_at": value.expires_at,
            "maximum_audio_bytes": value.maximum_audio_bytes,
        }

    @staticmethod
    def _bearer(value: str | None) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise SpeechIngressError("speech_ingress_unauthorized", 401)
        token = value[7:]
        if not 16 <= len(token.encode("utf-8")) <= MAX_BEARER_BYTES:
            raise SpeechIngressError("speech_ingress_unauthorized", 401)
        if any(ord(character) <= 32 or ord(character) == 127 for character in token):
            raise SpeechIngressError("speech_ingress_unauthorized", 401)
        return token

    @staticmethod
    def _identifier(value: object, code: str) -> str:
        if (type(value) is not str or not 1 <= len(value) <= 128
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None):
            raise SpeechIngressError(code)
        return value

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SpeechIngressError("speech_ingress_json_invalid")
            result[key] = value
        return result

    @staticmethod
    def _json_invalid() -> object:
        raise SpeechIngressError("speech_ingress_json_invalid")
