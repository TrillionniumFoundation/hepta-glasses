"""Wire-contract and resource tests; no external requests or live credentials."""
from __future__ import annotations

import copy
import dataclasses
import json
import os
import ssl
import tempfile
import unittest
from unittest.mock import patch

from services.model_gateway.production import ModelExecutionError, ProductionModelGateway, canonical
from services.model_gateway.responses_provider import MAX_RESPONSE_BYTES, ResponsesProvider, _json


KEY = "f" * 64  # inert correlation digest, not a credential


def document():
    return {"id": "resp_fixture", "object": "response", "status": "completed", "model": "fixture-model-2026-09-01",
        "store": False, "background": False, "tools": [], "error": None, "incomplete_details": None,
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "inert answer"}]}],
        "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}}


class Socket:
    def __init__(self):
        self.closed = False
        self.timeouts = []

    def settimeout(self, value):
        if self.closed:
            raise OSError("closed fixture socket")
        self.timeouts.append(value)


class Response:
    def __init__(self, body, *, headers=None, status=200):
        self.body, self.position = body, 0
        self.status = status
        self.headers = headers if headers is not None else [("Content-Type", "application/json"),
            ("Content-Length", str(len(body))), ("x-request-id", "req_fixture")]
        self.socket = None
        self.closed = False
        self.on_read = lambda: None

    def getheaders(self):
        return self.headers

    def read1(self, size):
        self.on_read()
        part = self.body[self.position:self.position + min(size, 1024)]
        self.position += len(part)
        if self.position == len(self.body):
            self.closed = True
            self.socket.closed = True
        return part

    def isclosed(self):
        return self.closed

    def close(self):
        self.closed = True
        if self.socket is not None:
            self.socket.closed = True


class Connection:
    def __init__(self, response):
        self.response = response
        self.transport = self.sock = Socket()
        self.response.socket = self.sock
        self.requests = []
        self.closed = False
        self.failure = None

    def connect(self):
        if self.failure:
            raise self.failure

    def request(self, method, path, *, body, headers):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        self.sock = None  # real http.client can detach on Connection: close
        return self.response

    def close(self):
        self.closed = True
        self.transport.closed = True


class ResponsesProviderTests(unittest.TestCase):
    def setUp(self):
        # Random fixture string is generated at runtime, never a real API key.
        self.token = os.urandom(24).hex()
        self.provider = ResponsesProvider("fixture-model-2026-09-01", "fixture-project", lambda: self.token)

    def call(self, response=None, **changes):
        response = response or Response(canonical(document()))
        conn = Connection(response)
        args = dict(question="inert question", context={}, request_key=KEY, timeout_seconds=1)
        args.update(changes)
        with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn) as factory:
            result = self.provider.generate(**args)
        return result, conn, factory

    def error(self, operation):
        with self.assertRaises(ModelExecutionError) as result:
            operation()
        self.assertNotIn(self.token, str(result.exception))
        return result.exception.code

    def altered(self, **changes):
        value = document(); value.update(changes)
        return Response(canonical(value))

    def test_exact_endpoint_tls_payload_and_diagnostic_binding(self):
        result, conn, factory = self.call()
        args, kwargs = factory.call_args
        self.assertEqual(args, ("api.openai.com", 443))
        self.assertEqual(kwargs["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(kwargs["context"].check_hostname)
        method, path, body, headers = conn.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/responses"))
        value = json.loads(body)
        self.assertIs(value["store"], False)
        self.assertIs(value["background"], False)
        self.assertIs(value["stream"], False)
        self.assertEqual(value["tools"], [])
        self.assertEqual(value["tool_choice"], "none")
        self.assertEqual(headers["X-Client-Request-Id"], KEY)
        self.assertEqual(headers["Authorization"], "Bearer " + self.token)
        self.assertNotIn("Idempotency-Key", headers)
        self.assertNotIn(self.token, body.decode())
        self.assertEqual(result.request_key, KEY)
        self.assertEqual(result.answer, "inert answer")
        self.assertTrue(conn.closed)
        self.assertTrue(conn.response.closed)
        self.assertTrue(all(0 < t <= 1 for t in conn.transport.timeouts))

    def test_connection_close_socket_detach_does_not_break_last_read(self):
        result, conn, _ = self.call()
        self.assertEqual(result.receipt_id, "resp_fixture")
        self.assertTrue(conn.transport.closed)

    def test_tools_in_context_are_plain_user_data_not_api_options(self):
        _, conn, _ = self.call(context={"tools": [{"type": "shell"}], "store": True, "base_url": "https://invalid.example"})
        body = json.loads(conn.requests[0][2])
        self.assertEqual(body["tools"], [])
        self.assertFalse(body["store"])
        self.assertEqual(len(body["input"]), 1)
        self.assertEqual(body["input"][0]["role"], "user")

    def test_provider_configuration_is_frozen_and_nonsecret(self):
        self.assertNotIn(self.token, repr(self.provider))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.provider.model = "another"
        self.assertEqual(len(self.provider.binding_id), 64)
        self.assertNotEqual(self.provider.binding_id, dataclasses.replace(self.provider, deployment_id="another").binding_id)
        self.assertNotEqual(self.provider.binding_id, dataclasses.replace(self.provider, maximum_output_tokens=2).binding_id)
        self.assertEqual(self.provider.binding_id, dataclasses.replace(self.provider, credential=lambda: "unused").binding_id)

    def test_invalid_config(self):
        for changes in ({"maximum_output_tokens": True}, {"maximum_output_tokens": 4097}, {"model": "x/y"}, {"credential": "literal"}):
            self.error(lambda: dataclasses.replace(self.provider, **changes))

    def test_credential_failure_never_opens_connection_or_exposes_error(self):
        def bad(): raise ValueError(self.token)
        self.provider = dataclasses.replace(self.provider, credential=bad)
        with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection") as factory:
            self.error(lambda: self.provider.generate(question="q", context={}, request_key=KEY, timeout_seconds=1))
            factory.assert_not_called()

    def test_missing_header_injection_or_bad_credential(self):
        for token in ("", "short", "x" * 5000, "x" * 24 + "\r\nInjected: yes", "界" * 24, None):
            self.provider = dataclasses.replace(self.provider, credential=lambda t=token: t)
            self.error(self.call)

    def test_no_environment_proxy_or_model_overrides(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://invalid.example", "OPENAI_BASE_URL": "https://invalid.example", "OPENAI_API_KEY": "unused"}):
            _, conn, factory = self.call()
        self.assertEqual(factory.call_args.args[0], "api.openai.com")
        self.assertEqual(json.loads(conn.requests[0][2])["model"], self.provider.model)

    def test_redirect_4xx_and_5xx_are_not_retried_or_reflected(self):
        for status in (301, 302, 307, 400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                response = Response(self.token.encode(), status=status)
                conn = Connection(response)
                with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn):
                    self.error(lambda: self.provider.generate(question="q", context={}, request_key=KEY, timeout_seconds=1))
                self.assertEqual(len(conn.requests), 1)
                self.assertEqual(response.position, 0)
                self.assertTrue(conn.closed)
                self.assertTrue(response.closed)

    def test_transport_error_is_sanitized_and_closed(self):
        conn = Connection(Response(b"")); conn.failure = OSError(self.token)
        with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn):
            self.error(lambda: self.provider.generate(question="q", context={}, request_key=KEY, timeout_seconds=1))
        self.assertTrue(conn.closed)
        self.assertEqual(conn.requests, [])

    def test_duplicate_protected_headers_rejected(self):
        for name, value in (("CONTENT-TYPE", "application/json"), ("Content-Length", "1"), ("X-REQUEST-ID", "req_other")):
            response = Response(canonical(document()))
            response.headers.append((name, value))
            self.error(lambda: self.call(response))

    def test_invalid_media_type_compression_and_transfer_encoding(self):
        for extra in (("Content-Type", "text/html"), ("Content-Encoding", "gzip"), ("Transfer-Encoding", "evil")):
            headers = [("x-request-id", "req_fixture"), extra]
            if extra[0] != "Content-Type": headers.append(("Content-Type", "application/json"))
            self.error(lambda: self.call(Response(canonical(document()), headers=headers)))

    def test_ambiguous_length_and_transfer_encoding_rejected(self):
        response = Response(canonical(document()))
        response.headers.append(("Transfer-Encoding", "chunked"))
        self.error(lambda: self.call(response))

    def test_chunked_json_without_content_length_is_supported(self):
        headers = [("Content-Type", "application/json"), ("Transfer-Encoding", "chunked"), ("x-request-id", "req_fixture")]
        result, _, _ = self.call(Response(canonical(document()), headers=headers))
        self.assertEqual(result.answer, "inert answer")

    def test_oversized_unknown_length_response_is_bounded_and_closed(self):
        response = Response(b"x" * (MAX_RESPONSE_BYTES + 100), headers=[("Content-Type", "application/json"), ("x-request-id", "req_fixture")])
        conn = Connection(response)
        with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn):
            self.error(lambda: self.provider.generate(question="q", context={}, request_key=KEY, timeout_seconds=1))
        self.assertEqual(response.position, MAX_RESPONSE_BYTES + 1)
        self.assertTrue(response.closed)

    def test_malformed_content_length_or_truncation_rejected(self):
        for length in ("-1", "0", "9999999", "abc", str(len(canonical(document())) + 1)):
            headers = [("Content-Type", "application/json"), ("Content-Length", length), ("x-request-id", "req_fixture")]
            self.error(lambda: self.call(Response(canonical(document()), headers=headers)))

    def test_deadline_is_rechecked_after_body_read(self):
        clock = [0.0]
        response = Response(canonical(document()))
        response.on_read = lambda: clock.__setitem__(0, 2.0)
        with patch("services.model_gateway.responses_provider.time.monotonic", side_effect=lambda: clock[0]):
            self.error(lambda: self.call(response))

    def test_response_json_duplicates_nonfinite_and_nonobjects(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"null", b"\xff", b"not-json", b"[" * 1100):
            self.error(lambda: self.call(Response(raw)))

    def test_missing_or_invalid_request_id(self):
        for value in (None, "", "x" * 129, "\n", "a b"):
            headers = [("Content-Type", "application/json")]
            if value is not None: headers.append(("x-request-id", value))
            self.error(lambda: self.call(Response(canonical(document()), headers=headers)))

    def test_nonterminal_response_never_returns_partial_text(self):
        for state in ("queued", "in_progress", "incomplete", "cancelled", "failed"):
            self.error(lambda: self.call(self.altered(status=state)))

    def test_wrong_model_retention_or_background_rejected(self):
        for changes in ({"model": "different"}, {"store": True}, {"store": 0}, {"background": True}, {"background": 0},
                        {"tools": [{"type": "function"}]}, {"error": {"message": "inert"}}, {"incomplete_details": {"reason": "limit"}}):
            self.error(lambda: self.call(self.altered(**changes)))

    def test_response_id_must_be_bounded_response_identifier(self):
        for response_id in ("req_fixture", "resp_" + "x" * 130, [], "resp_\n"):
            self.error(lambda: self.call(self.altered(id=response_id)))

    def test_tool_call_cannot_be_used_as_answer_even_with_valid_text(self):
        value = document(); value["output"].append({"type": "function_call", "name": "shell", "arguments": "inert"})
        self.error(lambda: self.call(Response(canonical(value))))

    def test_only_completed_assistant_text_is_admitted(self):
        for changes in ({"role": "user"}, {"status": "in_progress"}, {"content": []}, {"type": "unknown"},
                        {"content": [{"type": "refusal", "refusal": "inert refusal"}]}, {"content": [{"type": "output_text", "text": 3}]}):
            value = document(); value["output"][0].update(changes)
            self.error(lambda: self.call(Response(canonical(value))))

    def test_reasoning_not_exposed_and_multiple_text_parts_supported(self):
        value = document()
        value["output"].insert(0, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "inert hidden sentinel"}]})
        value["output"][1]["content"].append({"type": "output_text", "text": " second"})
        result, _, _ = self.call(Response(canonical(value)))
        self.assertEqual(result.answer, "inert answer second")
        self.assertNotIn("hidden", result.answer)

    def test_oversized_empty_and_invalid_unicode_output(self):
        for text in ("", " ", "x" * 65537, "界" * 30000, "\ud800"):
            value = document(); value["output"][0]["content"][0]["text"] = text
            raw = json.dumps(value, ensure_ascii=True).encode()
            self.error(lambda: self.call(Response(raw)))

    def test_usage_types_sum_and_output_limit(self):
        for usage in (None, {}, {"input_tokens": True, "output_tokens": 1, "total_tokens": 2},
                      {"input_tokens": 1, "output_tokens": 1025, "total_tokens": 1026},
                      {"input_tokens": 1, "output_tokens": 2, "total_tokens": 2},
                      {"input_tokens": -1, "output_tokens": 2, "total_tokens": 1}):
            self.error(lambda: self.call(self.altered(usage=usage)))

    def test_reconcile_never_networks_or_reposts(self):
        with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection") as factory:
            self.assertIsNone(self.provider.reconcile(request_key=KEY, timeout_seconds=1))
            factory.assert_not_called()

    def test_direct_call_input_boundaries(self):
        for changes in ({"question": "x" * 8001}, {"question": "\ud800"}, {"context": {"x": "x" * 40000}},
                        {"request_key": "not-a-digest"}, {"timeout_seconds": True}, {"timeout_seconds": float("nan")}):
            self.error(lambda: self.call(**changes))

    def test_gateway_adapter_composition_persists_no_prompt_answer_or_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = ProductionModelGateway(tmp + "/g.sqlite", provider=self.provider, provider_binding=self.provider.binding_id, clock=lambda: 1000)
            try:
                conn = Connection(Response(canonical(document())))
                with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn):
                    answer, receipt = g.execute(subject="user", session_id="session", idempotency_key="key",
                        question="inert input sentinel", context={}, expires_at=1100)
                self.assertEqual(answer, "inert answer")
                self.assertEqual(receipt.state, "committed")
                self.assertEqual(len(receipt.provider_request_id), 64)
                from pathlib import Path
                for p in Path(tmp).glob("g.sqlite*"):
                    for marker in (self.token.encode(), b"inert input sentinel", b"inert answer"):
                        self.assertNotIn(marker, p.read_bytes())
            finally:
                g.close()

    def test_gateway_unknown_transport_remains_indeterminate_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = ProductionModelGateway(tmp + "/g.sqlite", provider=self.provider, provider_binding=self.provider.binding_id, clock=lambda: 1000)
            args = dict(subject="user", session_id="session", idempotency_key="key", question="q", context={}, expires_at=1100)
            try:
                conn = Connection(Response(b"", status=503))
                with patch("services.model_gateway.responses_provider.http.client.HTTPSConnection", return_value=conn) as factory:
                    self.error(lambda: g.execute(**args))
                    self.error(lambda: g.execute(**args))
                    self.assertEqual(factory.call_count, 1)
                self.assertEqual(g.status(subject="user", idempotency_key="key").state, "indeterminate")
            finally:
                g.close()


if __name__ == "__main__":
    unittest.main()
