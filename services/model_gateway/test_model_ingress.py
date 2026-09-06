from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import dataclass

from services.model_gateway.model_ingress import (
    DEFAULT_AUDIENCE,
    REQUIRED_SCOPE,
    AuthenticatedModelIngress,
    ModelIngressError,
    ModelPrincipal,
)
from services.model_gateway.production import ProductionModelGateway


class Identity:
    def __init__(self, principal: ModelPrincipal) -> None:
        self.principal = principal
        self.failure: Exception | None = None
        self.calls: list[dict[str, str]] = []

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> ModelPrincipal:
        self.calls.append({
            "bearer_token": bearer_token,
            "audience": audience,
            "required_scope": required_scope,
        })
        if self.failure is not None:
            raise self.failure
        return self.principal


@dataclass(frozen=True)
class Result:
    answer: str


class Backend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result: object = Result("hello")
        self.failure: Exception | None = None

    def execute(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        if self.failure is not None:
            raise self.failure
        return self.result


class CodedError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__("sensitive detail")
        self.code = code


class ModelIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = ModelPrincipal(
            subject="subject-1",
            session_id="session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            consent_expires_at=1200,
        )
        self.identity = Identity(self.principal)
        self.backend = Backend()
        self.ingress = AuthenticatedModelIngress(
            backend=self.backend,
            identity=self.identity,
        )

    @staticmethod
    def body(**changes: object) -> bytes:
        value: dict[str, object] = {
            "question": "status",
            "task_id": "task-1",
            "context": {"locale": "en-US"},
        }
        value.update(changes)
        return json.dumps(value, separators=(",", ":")).encode()

    def answer(self, **changes: object) -> dict[str, object]:
        return self.ingress.answer(
            authorization="Bearer account-session-token-123456",
            body=self.body(**changes),
            timeout_seconds=10,
        )

    def error(self, code: str, status: int, callback) -> None:
        with self.assertRaises(ModelIngressError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, status)
        self.assertNotIn("sensitive", str(raised.exception))

    def test_subject_session_and_consent_come_from_principal(self) -> None:
        self.assertEqual(self.answer(), {"answer": "hello"})
        self.assertEqual(len(self.backend.calls), 1)
        call = self.backend.calls[0]
        self.assertEqual(call["subject"], "subject-1")
        self.assertEqual(call["session_id"], "session-1")
        self.assertEqual(call["idempotency_key"], "task-1")
        self.assertEqual(call["expires_at"], 1200)
        self.assertEqual(call["timeout_seconds"], 10.0)
        self.assertEqual(call["question"], "status")
        self.assertEqual(call["context"], {"locale": "en-US"})
        self.assertEqual(self.identity.calls, [{
            "bearer_token": "account-session-token-123456",
            "audience": DEFAULT_AUDIENCE,
            "required_scope": REQUIRED_SCOPE,
        }])

    def test_client_cannot_supply_identity_or_consent_fields(self) -> None:
        for name in ("subject", "session_id", "expires_at", "provider"):
            self.error(
                "model_ingress_request_shape_invalid",
                400,
                lambda name=name: self.answer(**{name: "attacker"}),
            )
        self.assertEqual(self.backend.calls, [])

    def test_duplicate_unknown_and_nonfinite_json_fail_before_identity(self) -> None:
        duplicate = (
            b'{"question":"a","question":"b","task_id":"task-1",'
            b'"context":{}}'
        )
        self.error(
            "model_ingress_json_invalid",
            400,
            lambda: self.ingress.answer(
                authorization="Bearer account-session-token-123456",
                body=duplicate,
            ),
        )
        nonfinite = (
            b'{"question":"a","task_id":"task-1",'
            b'"context":{"score":NaN}}'
        )
        self.error(
            "model_ingress_json_invalid",
            400,
            lambda: self.ingress.answer(
                authorization="Bearer account-session-token-123456",
                body=nonfinite,
            ),
        )
        self.assertEqual(self.identity.calls, [])

    def test_scope_and_malformed_principal_fail_before_backend(self) -> None:
        self.identity.principal = ModelPrincipal(
            subject="subject-1",
            session_id="session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=("model.read",),
            consent_expires_at=1200,
        )
        self.error("model_ingress_scope_denied", 403, self.answer)
        self.identity.principal = ModelPrincipal(
            subject="bad subject",
            session_id="session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            consent_expires_at=1200,
        )
        self.error("model_ingress_unauthorized", 401, self.answer)
        self.assertEqual(self.backend.calls, [])

    def test_identity_and_backend_exceptions_are_sanitized(self) -> None:
        self.identity.failure = RuntimeError("sensitive identity detail")
        self.error("model_ingress_unauthorized", 401, self.answer)
        self.identity.failure = None
        self.backend.failure = RuntimeError("sensitive provider response")
        self.error("model_ingress_unavailable", 503, self.answer)
        self.backend.failure = CodedError("idempotency_conflict")
        self.error("idempotency_conflict", 409, self.answer)

    def test_context_and_response_are_bounded(self) -> None:
        self.error(
            "model_ingress_context_invalid",
            400,
            lambda: self.answer(context={"x": object()}),
        )
        self.backend.result = Result("x" * 65_537)
        self.error("model_ingress_response_invalid", 503, self.answer)

    def test_production_gateway_execute_signature_matches_ingress(self) -> None:
        parameters = inspect.signature(ProductionModelGateway.execute).parameters
        for name in (
            "subject",
            "session_id",
            "idempotency_key",
            "question",
            "context",
            "expires_at",
            "timeout_seconds",
        ):
            self.assertIn(name, parameters)


if __name__ == "__main__":
    unittest.main()
