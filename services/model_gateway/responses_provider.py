"""Text-only foreground OpenAI Responses adapter; never an execution authority.

One HTTPS POST, no automatic retry, proxy, redirect, stored conversation, tools,
background task, or response cache. A lost response cannot be recovered by the
client request ID; reconcile returns unknown instead of repeating the request.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

from services.control_plane.durable_state import deadline
from services.model_gateway.production import (
    MAX_ANSWER_BYTES, ModelExecutionError, ProviderResult, canonical, context_bytes,
    digest, fail, identifier,
)

MAX_RESPONSE_BYTES = 262144


def _request_key(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail("model_provider_request_key_invalid")
    return value


def _json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("model_provider_json_invalid")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: fail("model_provider_json_invalid"))
        if type(value) is not dict:
            fail("model_provider_json_invalid")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ModelExecutionError("model_provider_json_invalid") from None


@dataclass(frozen=True)
class ResponsesProvider:
    model: str
    deployment_id: str
    credential: Callable[[], str] = field(repr=False, compare=False)
    maximum_output_tokens: int = 1024

    def __post_init__(self) -> None:
        identifier(self.model)
        identifier(self.deployment_id)
        if (not callable(self.credential) or type(self.maximum_output_tokens) is not int
                or not 1 <= self.maximum_output_tokens <= 4096):
            fail("model_provider_configuration_invalid")

    @property
    def binding_id(self) -> str:
        # Non-secret, operator-governed deployment label binds the actual project.
        return digest(canonical({"provider": "openai-responses-foreground-v1", "host": "api.openai.com",
            "model": self.model, "deployment": self.deployment_id, "output_tokens": self.maximum_output_tokens,
            "store": False, "tools": [], "background": False}))

    def generate(self, *, question: str, context: Mapping[str, object], request_key: str,
                 timeout_seconds: float) -> ProviderResult:
        _request_key(request_key)
        if not deadline(timeout_seconds):
            fail("model_provider_deadline_invalid")
        if type(question) is not str or not question.strip() or len(question) > 8000:
            fail("model_question_invalid")
        encoded_context = context_bytes(context)
        try:
            text = canonical({"question": question, "context": json.loads(encoded_context)}).decode("utf-8")
            payload = canonical({"model": self.model, "input": [{"role": "user", "content": [
                {"type": "input_text", "text": text}]}], "store": False, "stream": False,
                "background": False, "tools": [], "tool_choice": "none",
                "max_output_tokens": self.maximum_output_tokens})
        except UnicodeError:
            raise ModelExecutionError("model_question_invalid") from None
        if len(payload) > 131072:
            fail("model_provider_request_limit")
        stop = time.monotonic() + timeout_seconds
        connection = None
        response = None
        token = None
        try:
            token = self.credential()
            if (type(token) is not str or not 20 <= len(token) <= 4096
                    or any(not 33 <= ord(char) <= 126 for char in token)):
                fail("model_provider_credential_unavailable")
            def remaining():
                value = stop - time.monotonic()
                if value <= 0:
                    fail("model_provider_deadline_expired")
                return min(value, 10.0)
            connection = http.client.HTTPSConnection("api.openai.com", 443,
                context=ssl.create_default_context(), timeout=remaining())
            connection.connect()
            connection.sock.settimeout(remaining())
            connection.request("POST", "/v1/responses", body=payload, headers={
                "Authorization": "Bearer " + token, "Content-Type": "application/json",
                "Accept": "application/json", "Accept-Encoding": "identity",
                "X-Client-Request-Id": request_key, "Connection": "close"})
            token = None
            connection.sock.settimeout(remaining())
            transport = connection.sock
            response = connection.getresponse()
            if response.status != 200:
                # Do not read/reflect an error body or follow Location. A response
                # status alone does not prove that no remote work was performed.
                fail("model_provider_http_indeterminate")
            headers = {}
            for key, value in response.getheaders():
                key = key.lower()
                if key in {"content-type", "content-length", "content-encoding", "transfer-encoding", "x-request-id"}:
                    if key in headers:
                        fail("model_provider_headers_invalid")
                    headers[key] = value
            if (headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                    or headers.get("content-encoding", "identity").lower() != "identity"
                    or headers.get("transfer-encoding", "chunked").lower() != "chunked"):
                fail("model_provider_headers_invalid")
            length = headers.get("content-length")
            if length is not None and (not re.fullmatch(r"[0-9]{1,7}", length)
                                      or not 1 <= int(length) <= MAX_RESPONSE_BYTES
                                      or "transfer-encoding" in headers):
                fail("model_provider_response_limit")
            provider_request = identifier(headers.get("x-request-id"))
            data = bytearray()
            while True:
                # Capture the socket before getresponse: with Connection: close,
                # HTTPResponse owns it and the HTTPSConnection can clear sock.
                if transport is not None:
                    transport.settimeout(remaining())
                chunk = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    fail("model_provider_response_limit")
                if response.isclosed():
                    break
            remaining()
            if length is not None and len(data) != int(length):
                fail("model_provider_response_truncated")
            return self._result(_json(bytes(data)), provider_request, request_key)
        except ModelExecutionError:
            raise
        except Exception:
            # Includes credential/vault errors. No raw exception chaining.
            raise ModelExecutionError("model_provider_transport_indeterminate") from None
        finally:
            token = None
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()

    def _result(self, value: dict, provider_request: str, request_key: str) -> ProviderResult:
        if (value.get("object") != "response" or value.get("status") != "completed"
                or value.get("model") != self.model or value.get("store") is not False
                or value.get("background") is not False or value.get("tools") != []
                or value.get("error") is not None or value.get("incomplete_details") is not None):
            fail("model_provider_response_invalid")
        response_id = identifier(value.get("id"))
        if not response_id.startswith("resp_"):
            fail("model_provider_response_invalid")
        output = value.get("output")
        if type(output) is not list or not 1 <= len(output) <= 64:
            fail("model_provider_output_invalid")
        parts, size = [], 0
        for item in output:
            if type(item) is not dict:
                fail("model_provider_output_invalid")
            if item.get("type") == "reasoning":
                continue  # never expose, persist, or treat reasoning as authority
            if (item.get("type") != "message" or item.get("role") != "assistant"
                    or item.get("status") != "completed" or type(item.get("content")) is not list
                    or not 1 <= len(item["content"]) <= 64):
                fail("model_provider_output_invalid")
            for part in item["content"]:
                if type(part) is not dict or part.get("type") != "output_text" or type(part.get("text")) is not str:
                    fail("model_provider_output_invalid")
                try:
                    size += len(part["text"].encode("utf-8"))
                except UnicodeError:
                    raise ModelExecutionError("model_provider_output_invalid") from None
                if size > MAX_ANSWER_BYTES:
                    fail("model_provider_output_limit")
                parts.append(part["text"])
        answer = "".join(parts)
        if not answer.strip():
            fail("model_provider_output_invalid")
        usage = value.get("usage")
        if type(usage) is not dict:
            fail("model_provider_usage_invalid")
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            if type(usage.get(name)) is not int or not 0 <= usage[name] <= 10000000:
                fail("model_provider_usage_invalid")
        if (usage["output_tokens"] > self.maximum_output_tokens
                or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]):
            fail("model_provider_usage_invalid")
        return ProviderResult(answer, provider_request, response_id, request_key)

    def reconcile(self, *, request_key: str, timeout_seconds: float) -> None:
        _request_key(request_key)
        if not deadline(timeout_seconds):
            fail("model_provider_deadline_invalid")
        # X-Client-Request-Id is diagnostic correlation, NOT an idempotency or
        # response-retrieval API. Foreground store=false cannot promise readback.
        return None
