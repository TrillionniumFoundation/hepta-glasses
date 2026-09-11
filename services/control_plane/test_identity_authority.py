"""Real Ed25519 fixture tests and isolated HTTPS protocol tests, not live KMS."""
import base64
import dataclasses
import hashlib
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from services.control_plane import identity_authority as module
from services.control_plane.durable_identity import DurableIdentityError, DurableIdentityStore
from services.control_plane.identity_authority import (
    DurableIdentityAuthority, HttpsAuthorityBroker, PinnedEd25519Verifier,
    VerificationKey, _b64, strict_json,
)


class SignedBroker:
    def __init__(self, private_key, clock):
        self.private_key, self.clock = private_key, clock
        self.on_sign = lambda: None
        self.on_verify = lambda: None
        self.damage = False
        self.calls = 0

    def sign(self, payload, *, key_id, request_id, timeout_seconds):
        self.calls += 1
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture-input"
            source.write_bytes(payload)
            result = subprocess.run(["/usr/bin/openssl", "pkeyutl", "-sign", "-inkey", str(self.private_key),
                                     "-keyform", "DER", "-rawin", "-in", str(source)],
                                    capture_output=True, check=True, timeout=5)
        signature = b"\x00" * 64 if self.damage else result.stdout
        self.on_sign()
        return dict(key_id=key_id, request_id=request_id, algorithm="Ed25519",
                    payload_sha256=hashlib.sha256(payload).hexdigest(), signature=_b64(signature), receipt_id="fixture-receipt")

    def verify_attestation(self, challenge, proof, *, timeout_seconds):
        self.on_verify()
        return dict(subject=challenge.subject, device_id=challenge.device_id, platform=challenge.platform,
                    application_id=challenge.application_id, signer_digest=challenge.signer_digest,
                    nonce_sha256=hashlib.sha256(challenge.nonce.encode()).hexdigest(),
                    proof_sha256=hashlib.sha256(proof).hexdigest(), verified=True,
                    verified_at=self.clock(), expires_at=challenge.expires_at, receipt_id="fixture-attestation")


class IdentityAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        cls.private_key = Path(cls.keys.name) / "fixture-key.der"
        subprocess.run(["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER",
                        "-out", str(cls.private_key)], check=True, capture_output=True, timeout=5)
        cls.public = subprocess.run(["/usr/bin/openssl", "pkey", "-inform", "DER", "-in", str(cls.private_key),
                                     "-pubout", "-outform", "DER"], check=True, capture_output=True, timeout=5).stdout

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000
        self.store = DurableIdentityStore(str(Path(self.tmp.name) / "i.db"), issuer="hepta",
                                          allowed_scopes=["display"], clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.broker = SignedBroker(self.private_key, lambda: self.now)
        self.key = VerificationKey(self.public, 900, 2000)
        self.verifier = PinnedEd25519Verifier({"k": self.key})
        self.authority = DurableIdentityAuthority(self.store, broker=self.broker, verifier=self.verifier, active_key_id="k")
        self.store.admit_subject("u")
        self.challenge = self.store.challenge(subject="u", device_id="d", platform="android",
                                              application_id="app", signer_digest="a" * 64)

    def session(self):
        self.authority.enroll(self.challenge, b"fixture-attestation")
        return self.store.create_session(subject="u", device_id="d", audience="mobile", scopes=["display"])

    def issue(self, session=None):
        return self.authority.issue(subject="u", device_id="d", session_id=session or self.session(),
                                    audience="mobile", scopes=["display"])

    def test_real_ed25519_roundtrip_and_durable_revoke(self):
        token = self.issue()
        claims = self.authority.verify(token, audience="mobile", required_scopes=["display"])
        self.assertEqual(claims["sub"], "u")
        self.assertNotIn(token, "\n".join(self.store.db.iterdump()))
        self.store.revoke("token", claims["jti"])
        with self.assertRaises(DurableIdentityError):
            self.authority.verify(token, audience="mobile", required_scopes=["display"])

    def test_revoked_while_signing_never_returns_token(self):
        session = self.session()
        self.broker.on_sign = lambda: self.store.revoke("session", session)
        with self.assertRaisesRegex(DurableIdentityError, "session_unavailable"):
            self.issue(session)
        self.assertEqual(self.store.db.execute("SELECT state FROM identity_tokens").fetchone()[0], "revoked")

    def test_forged_signature_never_activates(self):
        session = self.session()
        self.broker.damage = True
        with self.assertRaisesRegex(DurableIdentityError, "signature_invalid"):
            self.issue(session)
        self.assertEqual(self.store.db.execute("SELECT state FROM identity_tokens").fetchone()[0], "indeterminate")

    def test_signer_timeout_does_not_return_active_authority(self):
        session = self.session()
        with mock.patch.object(self.broker, "sign", side_effect=TimeoutError("fixture")):
            with self.assertRaises(TimeoutError):
                self.issue(session)
        self.assertEqual(len(self.store.pending_tokens()), 1)

    def test_signer_identity_and_request_binding_rejected(self):
        session = self.session()
        original = self.broker.sign
        for field, value in (("key_id", "other"), ("algorithm", "HS256"),
                             ("request_id", "other"), ("payload_sha256", "c" * 64)):
            def wrong(*args, **kwargs):
                return {**original(*args, **kwargs), field: value}
            with self.subTest(field=field), mock.patch.object(self.broker, "sign", side_effect=wrong):
                with self.assertRaisesRegex(DurableIdentityError, "signer_response"):
                    self.issue(session)

    def test_attestation_wrong_field_or_truthy_number_rejected(self):
        original = self.broker.verify_attestation
        for field, value in (("subject", "other"), ("device_id", "other"), ("verified", 1),
                             ("platform", "ios"), ("nonce_sha256", "c" * 64), ("proof_sha256", "c" * 64)):
            def wrong(*args, **kwargs):
                return {**original(*args, **kwargs), field: value}
            with self.subTest(field=field), mock.patch.object(self.broker, "verify_attestation", side_effect=wrong):
                with self.assertRaisesRegex(DurableIdentityError, "verdict_invalid"):
                    self.authority.enroll(self.challenge, b"fixture")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM identity_devices").fetchone()[0], 0)

    def test_attestation_revocation_during_call_blocks_enrollment(self):
        self.broker.on_verify = lambda: self.store.revoke("device", "d")
        with self.assertRaises(DurableIdentityError):
            self.authority.enroll(self.challenge, b"fixture")

    def test_attestation_freshness_and_size_rejected(self):
        original = self.broker.verify_attestation
        with mock.patch.object(self.broker, "verify_attestation", side_effect=lambda *a, **k: {
            **original(*a, **k), "verified_at": 1,
        }):
            with self.assertRaisesRegex(DurableIdentityError, "freshness"):
                self.authority.enroll(self.challenge, b"fixture")
        with self.assertRaises(DurableIdentityError):
            self.authority.enroll(self.challenge, b"x" * 32769)

    def test_token_algorithm_type_signature_and_encoding_downgrades_fail(self):
        token = self.issue()
        head, body, signature = token.split(".")
        for changed in ("x", token + "=", ".".join((head, body, _b64(bytes(64)))),
                        ".".join((_b64(b'{"alg":"none","typ":"HGAT2","kid":"k"}'), body, signature)),
                        ".".join((head, body + "=", signature))):
            with self.subTest(token=changed[:15]):
                with self.assertRaises(DurableIdentityError):
                    self.authority.verify(changed, audience="mobile", required_scopes=["display"])

    def test_public_key_set_snapshot_alias_and_expiry_policy(self):
        keys = {"k": self.key}
        verifier = PinnedEd25519Verifier(keys)
        keys.clear()
        verifier.require_key("k", now=1000)
        with self.assertRaises(DurableIdentityError):
            PinnedEd25519Verifier({"k": self.key, "alias": self.key})
        for key in (dataclasses.replace(self.key, revoked=True), dataclasses.replace(self.key, not_after=1000),
                    dataclasses.replace(self.key, not_before=1001)):
            with self.subTest(key=key), self.assertRaises(DurableIdentityError):
                PinnedEd25519Verifier({"k": key}).require_key("k", now=1000)

    def test_key_expiry_blocks_issuance_before_signer(self):
        session = self.session()
        self.authority.verifier = PinnedEd25519Verifier({"k": dataclasses.replace(self.key, not_after=1100)})
        with self.assertRaises(DurableIdentityError):
            self.issue(session)
        self.assertEqual(self.broker.calls, 0)

    def test_duplicate_or_nonfinite_json_fail(self):
        for payload in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'{"a":Infinity}'):
            with self.assertRaises(DurableIdentityError):
                strict_json(payload)

    def test_verifier_ignores_environment_program_injection(self):
        token = self.issue()
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent", "OPENSSL_CONF": "/nonexistent/evil"}):
            self.authority.verify(token, audience="mobile", required_scopes=["display"])

    def test_signed_payloads_only_use_sealed_memory_descriptors(self):
        token = self.issue()
        original = subprocess.run
        def inspect(command, **kwargs):
            if command[1] == "pkeyutl":
                self.assertEqual(command[0], "/usr/bin/openssl")
                self.assertEqual(len(kwargs["pass_fds"]), 3)
                import fcntl
                for fd in kwargs["pass_fds"]:
                    seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
                    self.assertTrue(seals & fcntl.F_SEAL_WRITE)
                self.assertNotIn("LD_PRELOAD", kwargs["env"])
            return original(command, **kwargs)
        with mock.patch.object(subprocess, "run", side_effect=inspect):
            self.authority.verify(token, audience="mobile", required_scopes=["display"])


class Response:
    status = 200
    def __init__(self, payload=b'{"fixture":true}', content_type="application/json", status=200, length=None):
        self.payload, self.content_type, self.status = payload, content_type, status
        self.length = str(len(payload)) if length is None else length
    def getheader(self, name, default=None):
        return {"Content-Type": self.content_type, "Content-Length": self.length}.get(name, default)
    def read(self, limit): return self.payload[:limit]


class HttpsAuthorityTransportTests(unittest.TestCase):
    def broker(self, **kwargs):
        return HttpsAuthorityBroker(endpoint="https://authority.example", expected_host="authority.example",
                                    workload_token=lambda: "fixture-workload", **kwargs)

    def test_exact_https_post_and_closed_connection(self):
        connection = mock.Mock()
        connection.getresponse.return_value = Response()
        with mock.patch.object(module.http.client, "HTTPSConnection", return_value=connection) as constructor:
            result = self.broker().sign(b"payload", key_id="key", request_id="r")
        self.assertEqual(result, {"fixture": True})
        args = constructor.call_args
        self.assertEqual(args.args, ("authority.example", 443))
        self.assertTrue(args.kwargs["context"].check_hostname)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", "/v1/signatures/ed25519"))
        connection.close.assert_called_once()

    def test_redirect_errors_duplicate_json_truncation_and_oversize_rejected(self):
        for response in (Response(status=302), Response(status=503), Response(content_type="text/html"),
                         Response(b'{"a":1,"a":2}'), Response(length="999"),
                         Response(b"x" * 65537), Response(length="x")):
            connection = mock.Mock()
            connection.getresponse.return_value = response
            with self.subTest(status=response.status), mock.patch.object(module.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaises(DurableIdentityError):
                    self.broker().sign(b"p", key_id="k", request_id="r")
                connection.close.assert_called_once()

    def test_protected_endpoint_configuration_rejects_unsafe_urls(self):
        for endpoint in ("http://authority.example", "https://user@authority.example", "https://@authority.example", "https://:@authority.example", "https://authority.example?token=a",
                         "https://authority.example:8080", "https://authority.example/path", "https://other.example"):
            with self.subTest(endpoint=endpoint), self.assertRaises(DurableIdentityError):
                HttpsAuthorityBroker(endpoint=endpoint, expected_host="authority.example", workload_token=lambda: "fixture")

    def test_secret_header_injection_rejected_without_network(self):
        broker = self.broker()
        broker._workload_token = lambda: "fixture\r\nInjected:yes"
        with mock.patch.object(module.http.client, "HTTPSConnection") as connection:
            with self.assertRaises(DurableIdentityError):
                broker.sign(b"p", key_id="k", request_id="r")
            connection.assert_not_called()

    def test_timeout_is_bounded_and_worker_capacity_retained(self):
        connection = mock.Mock()
        release, entered = threading.Event(), threading.Event()
        errors = []
        def blocked():
            entered.set()
            release.wait(3)
            return Response()
        connection.getresponse.side_effect = blocked
        broker = self.broker(maximum_workers=1)
        with mock.patch.object(module.http.client, "HTTPSConnection", return_value=connection) as constructor:
            caller = None
            try:
                started = time.monotonic()
                def first_call():
                    try:
                        broker.sign(b"p", key_id="k", request_id="r", timeout_seconds=.1)
                    except DurableIdentityError as error:
                        errors.append(error)
                caller = threading.Thread(target=first_call)
                caller.start()
                self.assertTrue(entered.wait(1), "fixture provider worker never entered")
                caller.join(1)
                self.assertFalse(caller.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertLess(time.monotonic() - started, 1)
                # The provider worker remains blocked and retains the only permit.
                with self.assertRaises(DurableIdentityError):
                    broker.sign(b"p", key_id="k", request_id="r2", timeout_seconds=.02)
                self.assertEqual(constructor.call_count, 1)
            finally:
                release.set()
                if caller is not None:
                    caller.join(1)
                # Wait for the single test worker to close its connection before patch exit.
                for _ in range(100):
                    if connection.close.called: break
                    time.sleep(.002)

    def test_invalid_deadline_fails_without_network(self):
        for timeout in (True, 0, -1, float("nan"), float("inf"), 61):
            with self.subTest(timeout=timeout), mock.patch.object(module.http.client, "HTTPSConnection") as connection:
                with self.assertRaises(DurableIdentityError):
                    self.broker().sign(b"p", key_id="k", request_id="r", timeout_seconds=timeout)
                connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
