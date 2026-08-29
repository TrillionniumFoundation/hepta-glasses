#!/usr/bin/env python3
"""Development model gateway with a deterministic provider.

This server exists to prove the mobile-to-gateway boundary. It deliberately
contains no production provider integration or permanent credential handling.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

MAX_BODY_BYTES = 64 * 1024
MAX_QUESTION_CHARACTERS = 8_000
MAX_CONTEXT_BYTES = 32 * 1024


class RequestError(ValueError):
    """A stable client-visible request validation error."""

    def __init__(self, code: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ChatRequest:
    question: str
    task_id: str | None
    context: dict[str, Any]


def authorize(header_value: str | None, expected_token: str | None) -> bool:
    if not expected_token:
        return True
    if not header_value or not header_value.startswith("Bearer "):
        return False
    supplied = header_value.removeprefix("Bearer ")
    return hmac.compare_digest(supplied, expected_token)


def validate_chat_request(document: Any) -> ChatRequest:
    if not isinstance(document, Mapping):
        raise RequestError("request_must_be_object")
    unknown = set(document) - {"question", "task_id", "context"}
    if unknown:
        raise RequestError("unknown_request_fields")

    question = document.get("question")
    if not isinstance(question, str) or not question.strip():
        raise RequestError("question_required")
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARACTERS:
        raise RequestError("question_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    task_id = document.get("task_id")
    if task_id is not None and (not isinstance(task_id, str) or len(task_id) > 128):
        raise RequestError("invalid_task_id")

    context = document.get("context", {})
    if not isinstance(context, Mapping):
        raise RequestError("context_must_be_object")
    context_dict = {str(key): value for key, value in context.items()}
    encoded_context = json.dumps(
        context_dict, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded_context) > MAX_CONTEXT_BYTES:
        raise RequestError("context_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    return ChatRequest(question=question, task_id=task_id, context=context_dict)


def deterministic_answer(request: ChatRequest) -> dict[str, Any]:
    """Return a non-production deterministic response without logging content."""
    return {
        "answer": f"Hepta development gateway received {len(request.question)} characters.",
        "provider": "deterministic-development",
        "task_id": request.task_id,
    }


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "HeptaModelGateway/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib interface
        if self.path != "/healthz":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._write_json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib interface
        if self.path != "/v1/chat":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        expected_token = os.environ.get("HEPTA_GATEWAY_DEV_TOKEN")
        if not authorize(self.headers.get("Authorization"), expected_token):
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._write_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "body_size_invalid"},
            )
            return

        try:
            document = json.loads(self.rfile.read(length).decode("utf-8"))
            request = validate_chat_request(document)
            response = deterministic_answer(request)
        except UnicodeDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_utf8"})
            return
        except json.JSONDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        except RequestError as error:
            self._write_json(error.status, {"error": error.code})
            return

        self._write_json(HTTPStatus.OK, response)

    def log_message(self, format: str, *args: object) -> None:
        # Do not emit request paths, query text, headers, or bodies by default.
        return

    def _write_json(self, status: HTTPStatus, document: Mapping[str, Any]) -> None:
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
