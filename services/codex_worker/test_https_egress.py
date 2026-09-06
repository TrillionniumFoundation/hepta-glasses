from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest.mock import patch

from services.codex_worker.https_egress import (
    EgressError,
    EgressPolicy,
    ExactDomainHttpsBroker,
)
from services.codex_worker.https_egress_dns import Address, validate_addresses


class HttpsEgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = EgressPolicy(("api.example.com",), timeout_seconds=1,
                                   maximum_request_bytes=1024,
                                   maximum_response_bytes=1024,
                                   maximum_response_headers=16,
                                   maximum_response_header_bytes=4096)
        self.broker = ExactDomainHttpsBroker(self.policy)

    def error(self, code, callback):
        with self.assertRaises(EgressError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def exchange(self, response: bytes, *, url="https://api.example.com/v1?q=1", method="GET", body=b"", delay=0):
        client, server = socket.socketpair()
        observed = []

        def serve():
            with server:
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    request.extend(chunk)
                head, pending = bytes(request).split(b"\r\n\r\n", 1)
                length = 0
                for line in head.split(b"\r\n")[1:]:
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                while len(pending) < length:
                    chunk = server.recv(4096)
                    if not chunk:
                        break
                    pending += chunk
                observed.append(head + b"\r\n\r\n" + pending[:length])
                if delay:
                    time.sleep(delay)
                try:
                    server.sendall(response)
                except BrokenPipeError:
                    pass

        thread = threading.Thread(target=serve)
        thread.start()
        with patch("services.codex_worker.https_egress.resolve_addresses",
                   return_value=(Address(socket.AF_INET, "1.1.1.1"),)), \
             patch("services.codex_worker.https_egress.connect_tls", return_value=client) as connect:
            try:
                result = self.broker.request(url, method=method, body=body)
            finally:
                client.close()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        return result, observed, connect

    def test_get_uses_exact_host_and_one_http_request(self):
        result, observed, connect = self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        self.assertEqual((result.status, result.body), (200, b"ok"))
        self.assertIn(b"GET /v1?q=1 HTTP/1.1\r\nHost: api.example.com\r\n", observed[0])
        self.assertEqual(connect.call_args.args[1], "api.example.com")
        self.assertEqual(connect.call_count, 1)

    def test_post_body_and_fixed_headers(self):
        result, observed, _ = self.exchange(
            b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n",
            method="POST", body=b"payload")
        self.assertEqual(result.status, 201)
        self.assertIn(b"Content-Type: application/octet-stream\r\n", observed[0])
        self.assertIn(b"Accept-Encoding: identity\r\n", observed[0])
        self.assertTrue(observed[0].endswith(b"payload"))

    def test_url_and_method_boundaries(self):
        for url in (
            "http://api.example.com/",
            "https://user@api.example.com/",
            "https://api.example.com:444/",
            "https://API.EXAMPLE.COM/",
            "https://api.example.com/#fragment",
            "https://other.example.com/",
        ):
            code = ("egress_url_invalid" if url.startswith("http:") or "user@" in url
                    or ":444" in url or "#" in url else "egress_domain_denied")
            self.error(code, lambda u=url: self.broker.request(u))
        self.error("egress_method_denied",
                   lambda: self.broker.request("https://api.example.com/", method="PUT"))
        self.error("egress_request_invalid",
                   lambda: self.broker.request("https://api.example.com/", body=b"x"))

    def test_target_rejects_crlf_backslash_space_and_noncanonical_percent(self):
        for suffix in ("/%0dX", "/%0AX", "/bad\\path", "/bad path", "/%2f", "/%G0"):
            self.error("egress_target_invalid",
                       lambda s=suffix: self.broker.request("https://api.example.com" + s))

    def test_policy_rejects_wildcards_ip_literals_duplicates_and_unsorted(self):
        for domains in (
            ("*.example.com",),
            ("1.1.1.1",),
            ("b.example.com", "a.example.com"),
            ("a.example.com", "a.example.com"),
        ):
            self.error("egress_domains_invalid", lambda d=domains: EgressPolicy(d))

    def test_private_or_mixed_dns_is_rejected(self):
        for rows in (
            [[int(socket.AF_INET), "127.0.0.1"]],
            [[int(socket.AF_INET), "1.1.1.1"], [int(socket.AF_INET), "10.0.0.1"]],
            [[int(socket.AF_INET6), "fe80::1"]],
        ):
            self.error("egress_dns_address_rejected",
                       lambda r=rows: validate_addresses(r))

    def test_redirect_location_and_upgrade_are_rejected(self):
        for response, code in (
            (b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n",
             "egress_redirect_rejected"),
            (b"HTTP/1.1 200 OK\r\nLocation: https://api.example.com/x\r\nContent-Length: 0\r\n\r\n",
             "egress_redirect_rejected"),
            (b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: upgrade\r\n\r\n",
             "egress_redirect_rejected"),
        ):
            self.error(code, lambda r=response: self.exchange(r))

    def test_invalid_response_status_is_rejected(self):
        self.error("egress_response_status_invalid", lambda: self.exchange(
            b"HTTP/1.1 700 Unknown\r\nContent-Length: 0\r\n\r\n"))

    def test_compression_and_transfer_encoding_are_rejected(self):
        self.error("egress_compression_rejected", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 0\r\n\r\n"))
        self.error("egress_response_headers_invalid", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"))

    def test_duplicate_or_malformed_content_length_is_rejected(self):
        self.error("egress_response_headers_invalid", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\nx"))
        self.error("egress_response_headers_invalid", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Length: +1\r\n\r\nx"))

    def test_declared_and_streamed_response_limits(self):
        self.error("egress_response_too_large", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2048\r\n\r\n"))
        self.error("egress_response_too_large", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + b"x" * 1025))

    def test_truncated_and_slow_responses_fail_closed(self):
        self.error("egress_response_truncated", lambda: self.exchange(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nx"))
        short = ExactDomainHttpsBroker(EgressPolicy(("api.example.com",), timeout_seconds=.1))
        original = self.broker
        self.broker = short
        try:
            self.error("egress_transport_failed", lambda: self.exchange(
                b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", delay=.3))
        finally:
            self.broker = original

    def test_policy_and_response_headers_are_immutable(self):
        self.assertEqual(self.broker.policy.domains, ("api.example.com",))
        result, _, _ = self.exchange(
            b"HTTP/1.1 200 OK\r\nH-Test: yes\r\nContent-Length: 0\r\n\r\n")
        with self.assertRaises(TypeError):
            result.headers["x-test"] = "no"


if __name__ == "__main__":
    unittest.main()
