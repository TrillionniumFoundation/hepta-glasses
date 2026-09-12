"""Authenticated ingress for the durable production model gateway.

The client body cannot select subject, session, consent expiry, provider binding
or authority scope. The injected backend is expected to be
ProductionModelGateway or a stricter compatible implementation.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol

MAX_REQUEST_BYTES = 65_536
MAX_QUESTION_CHARACTERS = 8_000
MAX_CONTEXT_BYTES = 32_768
DEFAULT_AUDIENCE = "hepta-model-gateway"
REQUIRED_SCOPE = "model.generate"


class ModelIngressError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ModelPrincipal:
    subject: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    consent_expires_at: int


class ModelIdentityVerifier(Protocol):
    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> ModelPrincipal: ...


class ModelExecutionBackend(Protocol):
    def execute(self, *, subject: str, session_id: str,
                idempotency_key: str, question: str,
                context: dict[str, object], expires_at: int,
                timeout_seconds: float) -> object: ...


class AuthenticatedModelIngress:
    def __init__(self, *, backend: ModelExecutionBackend,
                 identity: ModelIdentityVerifier,
                 audience: str = DEFAULT_AUDIENCE) -> None:
        if not callable(getattr(backend, "execute", None)):
            raise ModelIngressError("model_ingress_backend_invalid", 500)
        if not callable(getattr(identity, "verify", None)):
            raise ModelIngressError("model_ingress_identity_invalid", 500)
        self._identifier(audience, "model_ingress_configuration_invalid")
        self.backend = backend
        self.identity = identity
        self.audience = audience

    def answer(self, *, authorization: str | None, body: bytes,
               timeout_seconds: float = 30) -> dict[str, object]:
        token = self._bearer(authorization)
        request = self._request(body)
        if type(timeout_seconds) not in (int, float) or type(timeout_seconds) is bool \
                or not 0 < float(timeout_seconds) <= 60:
            raise ModelIngressError("model_ingress_timeout_invalid")
        try:
            principal = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=REQUIRED_SCOPE,
            )
            principal = self._principal(principal)
        except ModelIngressError as error:
            if error.code == "model_ingress_unauthorized":
                raise ModelIngressError(error.code, 401) from None
            raise
        except Exception:
            raise ModelIngressError("model_ingress_unauthorized", 401) from None
        if principal.audience != self.audience or REQUIRED_SCOPE not in principal.scopes:
            raise ModelIngressError("model_ingress_scope_denied", 403)

        try:
            result = self.backend.execute(
                subject=principal.subject,
                session_id=principal.session_id,
                idempotency_key=request["task_id"],
                question=request["question"],
                context=request["context"],
                expires_at=principal.consent_expires_at,
                timeout_seconds=float(timeout_seconds),
            )
        except ModelIngressError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            if type(code) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
                status = 409 if code in {
                    "idempotency_conflict",
                    "model_request_cancelled",
                    "model_session_revoked",
                    "model_request_revoked",
                } else 429 if code in {
                    "model_quota_exhausted",
                    "model_capacity_suspended",
                } else 503
                raise ModelIngressError(code, status) from None
            raise ModelIngressError("model_ingress_unavailable", 503) from None
        answer = self._answer_text(result)
        return {"answer": answer}

    def _request(self, body: bytes) -> dict[str, Any]:
        if type(body) is not bytes or not 1 <= len(body) <= MAX_REQUEST_BYTES:
            raise ModelIngressError("model_ingress_body_invalid", 413)
        try:
            value = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=self._unique_object,
                parse_constant=lambda _: self._json_invalid(),
            )
        except (UnicodeError, json.JSONDecodeError, ModelIngressError):
            raise ModelIngressError("model_ingress_json_invalid") from None
        if type(value) is not dict or set(value) != {"question", "task_id", "context"}:
            raise ModelIngressError("model_ingress_request_shape_invalid")
        question = value["question"]
        task_id = self._identifier(value["task_id"], "model_ingress_request_invalid")
        context = value["context"]
        if type(question) is not str or not question.strip() \
                or len(question) > MAX_QUESTION_CHARACTERS:
            raise ModelIngressError("model_ingress_request_invalid")
        normalized_context = self._normalize_context(context)
        encoded_context = json.dumps(
            normalized_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded_context) > MAX_CONTEXT_BYTES:
            raise ModelIngressError("model_ingress_context_too_large", 413)
        return {
            "question": question.strip(),
            "task_id": task_id,
            "context": normalized_context,
        }

    def _principal(self, value: object) -> ModelPrincipal:
        if type(value) is not ModelPrincipal:
            raise ModelIngressError("model_ingress_unauthorized", 401)
        try:
            self._identifier(value.subject, "model_ingress_unauthorized")
            self._identifier(value.session_id, "model_ingress_unauthorized")
            self._identifier(value.audience, "model_ingress_unauthorized")
        except ModelIngressError:
            raise ModelIngressError("model_ingress_unauthorized", 401) from None
        if type(value.scopes) is not tuple or not value.scopes or len(value.scopes) > 32 \
                or len(set(value.scopes)) != len(value.scopes) \
                or any(type(scope) is not str or not 1 <= len(scope) <= 128
                       for scope in value.scopes) \
                or type(value.consent_expires_at) is not int \
                or type(value.consent_expires_at) is bool \
                or not 0 < value.consent_expires_at <= 253_402_300_799:
            raise ModelIngressError("model_ingress_unauthorized", 401)
        return value

    @classmethod
    def _normalize_context(cls, value: object, *, depth: int = 0) -> dict[str, object]:
        if type(value) is not dict or depth != 0:
            raise ModelIngressError("model_ingress_context_invalid")
        if len(value) > 256 or any(type(key) is not str for key in value):
            raise ModelIngressError("model_ingress_context_invalid")
        return {
            key: cls._normalize_value(value[key], depth=1)
            for key in sorted(value)
        }

    @classmethod
    def _normalize_value(cls, value: object, *, depth: int) -> object:
        if depth > 8:
            raise ModelIngressError("model_ingress_context_invalid")
        if value is None or type(value) in (str, bool, int):
            if type(value) is str and len(value) > 8_000:
                raise ModelIngressError("model_ingress_context_invalid")
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ModelIngressError("model_ingress_context_invalid")
            return value
        if type(value) is list:
            if len(value) > 256:
                raise ModelIngressError("model_ingress_context_invalid")
            return [cls._normalize_value(item, depth=depth + 1) for item in value]
        if type(value) is dict:
            if len(value) > 256 or any(type(key) is not str for key in value):
                raise ModelIngressError("model_ingress_context_invalid")
            return {
                key: cls._normalize_value(value[key], depth=depth + 1)
                for key in sorted(value)
            }
        raise ModelIngressError("model_ingress_context_invalid")

    @staticmethod
    def _answer_text(result: object) -> str:
        answer = result if type(result) is str else getattr(result, "answer", None)
        if type(answer) is not str:
            answer = getattr(result, "text", None)
        if type(answer) is not str:
            raise ModelIngressError("model_ingress_response_invalid", 503)
        answer = answer.strip()
        if not answer or len(answer.encode("utf-8")) > 65_536:
            raise ModelIngressError("model_ingress_response_invalid", 503)
        return answer

    @staticmethod
    def _bearer(value: str | None) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise ModelIngressError("model_ingress_unauthorized", 401)
        token = value[7:]
        if not 16 <= len(token) <= 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in token):
            raise ModelIngressError("model_ingress_unauthorized", 401)
        return token

    @staticmethod
    def _identifier(value: object, code: str) -> str:
        if type(value) is not str or not 1 <= len(value) <= 256 \
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None:
            raise ModelIngressError(code)
        return value

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ModelIngressError("model_ingress_json_invalid")
            result[key] = value
        return result

    @staticmethod
    def _json_invalid() -> object:
        raise ModelIngressError("model_ingress_json_invalid")
