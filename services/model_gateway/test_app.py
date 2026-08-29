from __future__ import annotations

import unittest
from http import HTTPStatus

from services.model_gateway.app import (
    RequestError,
    authorize,
    deterministic_answer,
    validate_chat_request,
)


class ModelGatewayTest(unittest.TestCase):
    def test_valid_request_is_minimized(self) -> None:
        request = validate_chat_request(
            {"question": "  status  ", "task_id": "task-1", "context": {}}
        )
        self.assertEqual(request.question, "status")
        self.assertEqual(deterministic_answer(request)["provider"], "deterministic-development")

    def test_unknown_field_fails_closed(self) -> None:
        with self.assertRaises(RequestError) as raised:
            validate_chat_request({"question": "status", "credential": "secret"})
        self.assertEqual(raised.exception.code, "unknown_request_fields")

    def test_large_question_has_stable_status(self) -> None:
        with self.assertRaises(RequestError) as raised:
            validate_chat_request({"question": "x" * 8_001})
        self.assertEqual(raised.exception.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    def test_token_comparison(self) -> None:
        self.assertTrue(authorize("Bearer expected", "expected"))
        self.assertFalse(authorize("Bearer wrong", "expected"))
        self.assertTrue(authorize(None, None))


if __name__ == "__main__":
    unittest.main()
