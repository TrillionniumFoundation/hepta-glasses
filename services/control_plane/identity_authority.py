"""Authenticated broker composition for durable identity and Ed25519 access tokens.

The HTTPS broker delegates real KMS/HSM and platform-verifier calls; it is not a
claim that such deployments exist. Local key material is public verification
material only. The reference HMAC TokenService is intentionally not reused.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import ssl
import subprocess
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from services.control_plane.bounded_calls import BoundedCalls
from services.control_plane.durable_identity import (
    DurableIdentityError, DurableIdentityStore, EnrollmentChallenge,
    _digest, _text, canonical_claims,
)
from services.control_plane.durable_state import deadline, timestamp


MAX_JSON_BYTES = 65536
MAX_TOKEN_BYTES = 32768
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: object, *, maximum: int) -> bytes:
    if (not isinstance(value, str) or not value or len(value) > maximum * 2
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise DurableIdentityError("identity_encoding_invalid")
    try:
        data = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError as error:
        raise DurableIdentityError("identity_encoding_invalid") from error
    if len(data) > maximum or _b64(data) != value:
        raise DurableIdentityError("identity_encoding_invalid")
    return data


def strict_json(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or len(payload) > MAX_JSON_BYTES:
        raise DurableIdentityError("identity_json_size_invalid")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DurableIdentityError("identity_json_duplicate")
            result[key] = value
        return result
    def constant(value):
        raise DurableIdentityError("identity_json_nonfinite")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise DurableIdentityError("identity_json_invalid") from error
    if not isinstance(value, dict):
        raise DurableIdentityError("identity_json_invalid")
    return value


class AuthorityBroker(Protocol):
    def verify_attestation(self, challenge: EnrollmentChallenge, proof: bytes, *, timeout_seconds: float) -> dict: ...
    def sign(self, payload: bytes, *, key_id: str, request_id: str, timeout_seconds: float) -> dict: ...


class HttpsAuthorityBroker:
    """Concrete HTTPS transport for contracts/identity-authority-v1.json.

    endpoint and expected_host are protected deployment configuration, never user
    input. There is no redirect, environment proxy, caller TLS context or custom
    connection factory. Tests patch HTTPConnection at the module boundary only.
    """
    def __init__(self, *, endpoint: str, expected_host: str,
                 workload_token: Callable[[], str], maximum_workers: int = 4):
        _text(endpoint, 2048)
        _text(expected_host, 253)
        parsed = urlsplit(endpoint)
        try:
            valid = (parsed.scheme == "https" and parsed.hostname == expected_host
                     and expected_host == expected_host.lower()
                     and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", expected_host)
                     and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                     and not parsed.query and not parsed.fragment and parsed.path in ("", "/"))
        except ValueError:
            valid = False
        if not valid or not callable(workload_token):
            raise DurableIdentityError("identity_broker_configuration_invalid")
        self.host = expected_host
        self._workload_token = workload_token
        self._calls = BoundedCalls(maximum_workers)

    def _post(self, path: str, body: dict, timeout_seconds: float) -> dict:
        if not deadline(timeout_seconds):
            raise DurableIdentityError("identity_broker_deadline_invalid")
        payload = canonical_claims(body)
        if len(payload) > MAX_JSON_BYTES:
            raise DurableIdentityError("identity_broker_request_too_large")
        def exchange():
            credential = self._workload_token()
            if (not isinstance(credential, str) or not 1 <= len(credential) <= 8192
                    or not credential.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in credential)):
                raise DurableIdentityError("identity_workload_identity_unavailable")
            connection = http.client.HTTPSConnection(self.host, 443, timeout=timeout_seconds,
                                                     context=ssl.create_default_context())
            try:
                connection.request("POST", path, body=payload, headers={
                    "Authorization": "Bearer " + credential,
                    "Content-Type": "application/json", "Accept": "application/json",
                })
                response = connection.getresponse()
                if response.status != 200:
                    raise DurableIdentityError("identity_broker_rejected")
                if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise DurableIdentityError("identity_broker_content_type_invalid")
                raw_length = response.getheader("Content-Length")
                if raw_length is not None and (not raw_length.isdecimal() or int(raw_length) > MAX_JSON_BYTES):
                    raise DurableIdentityError("identity_broker_response_too_large")
                response_payload = response.read(MAX_JSON_BYTES + 1)
                if raw_length is not None and len(response_payload) != int(raw_length):
                    raise DurableIdentityError("identity_broker_response_truncated")
                return strict_json(response_payload)
            finally:
                connection.close()
        outcome = self._calls.run(exchange, timeout_seconds=timeout_seconds)
        if outcome.state != "completed":
            # Provider bodies and credentials are deliberately not put in exceptions.
            raise DurableIdentityError("identity_broker_unavailable_or_indeterminate")
        return outcome.value

    def verify_attestation(self, challenge: EnrollmentChallenge, proof: bytes, *, timeout_seconds: float = 8) -> dict:
        if not isinstance(proof, bytes) or not 1 <= len(proof) <= 32768:
            raise DurableIdentityError("identity_attestation_size_invalid")
        return self._post("/v1/attestations/verify", {
            "subject": challenge.subject, "device_id": challenge.device_id,
            "platform": challenge.platform, "application_id": challenge.application_id,
            "signer_digest": challenge.signer_digest, "nonce": challenge.nonce,
            "proof": _b64(proof), "expires_at": challenge.expires_at,
        }, timeout_seconds)

    def sign(self, payload: bytes, *, key_id: str, request_id: str, timeout_seconds: float = 8) -> dict:
        _text(key_id)
        _text(request_id)
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 16384:
            raise DurableIdentityError("identity_signing_input_invalid")
        return self._post("/v1/signatures/ed25519", {
            "algorithm": "Ed25519", "key_id": key_id, "request_id": request_id,
            "payload": _b64(payload), "payload_sha256": hashlib.sha256(payload).hexdigest(),
        }, timeout_seconds)


@dataclass(frozen=True)
class VerificationKey:
    public_der: bytes
    not_before: int
    not_after: int
    revoked: bool = False


class PinnedEd25519Verifier:
    """Immutable externally provisioned public-key set, verified by system OpenSSL."""
    def __init__(self, keys: Mapping[str, VerificationKey]):
        if not isinstance(keys, Mapping) or not 1 <= len(keys) <= 32:
            raise DurableIdentityError("identity_keyset_invalid")
        values = dict(keys)
        fingerprints = set()
        for key_id, key in values.items():
            _text(key_id)
            if (not isinstance(key, VerificationKey) or type(key.public_der) is not bytes
                    or len(key.public_der) != 44 or not key.public_der.startswith(SPKI_PREFIX)
                    or not timestamp(key.not_before) or not timestamp(key.not_after)
                    or key.not_before >= key.not_after or type(key.revoked) is not bool):
                raise DurableIdentityError("identity_verification_key_invalid")
            if key.public_der in fingerprints:
                raise DurableIdentityError("identity_verification_key_alias")
            fingerprints.add(key.public_der)
        self.keys = MappingProxyType(values)

    def require_key(self, key_id: str, *, now: int, expires_at: int | None = None) -> VerificationKey:
        key = self.keys.get(key_id)
        if (key is None or key.revoked or not timestamp(now)
                or not key.not_before <= now < key.not_after
                or (expires_at is not None and expires_at > key.not_after)):
            raise DurableIdentityError("identity_signing_key_unavailable")
        return key

    def verify(self, payload: bytes, signature: bytes, *, key_id: str, now: int) -> None:
        if (not isinstance(payload, bytes) or not 1 <= len(payload) <= 16384
                or not isinstance(signature, bytes) or len(signature) != 64):
            raise DurableIdentityError("identity_signature_invalid")
        key = self.require_key(key_id, now=now)
        from tools.external_evidence.openssl_policy import (
            trusted_openssl_path, trusted_subprocess_environment,
        )
        def fail(message):
            raise DurableIdentityError("identity_verifier_runtime_unavailable")
        executable = trusted_openssl_path(fail=fail)
        # Token components remain in sealed anonymous memory, not scratch files.
        # Linux is the supported control-plane verifier platform; no disk fallback.
        import fcntl
        if not hasattr(os, "memfd_create") or not hasattr(fcntl, "F_ADD_SEALS"):
            raise DurableIdentityError("identity_verifier_memory_files_unavailable")
        descriptors = []
        try:
            for data in (key.public_der, payload, signature):
                fd = os.memfd_create("hepta-token-check", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
                descriptors.append(fd)
                remaining = memoryview(data)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise DurableIdentityError("identity_verifier_memory_write_failed")
                    remaining = remaining[written:]
                os.lseek(fd, 0, os.SEEK_SET)
                fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK
                            | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL)
            public_path, input_path, signature_path = (f"/proc/self/fd/{fd}" for fd in descriptors)
            result = subprocess.run([
                executable, "pkeyutl", "-verify", "-pubin", "-keyform", "DER",
                "-inkey", public_path, "-rawin", "-in", input_path,
                "-sigfile", signature_path,
            ], capture_output=True, timeout=5, env=trusted_subprocess_environment(),
                pass_fds=tuple(descriptors), check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise DurableIdentityError("identity_verifier_runtime_unavailable") from error
        finally:
            for fd in descriptors:
                os.close(fd)
        if result.returncode != 0:
            raise DurableIdentityError("identity_signature_invalid")


class DurableIdentityAuthority:
    def __init__(self, store: DurableIdentityStore, *, broker: AuthorityBroker,
                 verifier: PinnedEd25519Verifier, active_key_id: str):
        _text(active_key_id)
        self.store, self.broker, self.verifier = store, broker, verifier
        self.active_key_id = active_key_id

    def enroll(self, challenge: EnrollmentChallenge, proof: bytes, *, timeout_seconds: float = 8) -> dict:
        if not isinstance(challenge, EnrollmentChallenge) or not isinstance(proof, bytes) or not 1 <= len(proof) <= 32768:
            raise DurableIdentityError("identity_attestation_input_invalid")
        if not deadline(timeout_seconds):
            raise DurableIdentityError("identity_broker_deadline_invalid")
        verdict = self.broker.verify_attestation(challenge, proof, timeout_seconds=timeout_seconds)
        expected = {"subject": challenge.subject, "device_id": challenge.device_id,
                    "platform": challenge.platform, "application_id": challenge.application_id,
                    "signer_digest": challenge.signer_digest,
                    "nonce_sha256": hashlib.sha256(challenge.nonce.encode()).hexdigest(),
                    "proof_sha256": hashlib.sha256(proof).hexdigest()}
        if (not isinstance(verdict, dict) or set(verdict) != set(expected) | {"verified", "verified_at", "expires_at", "receipt_id"}
                or verdict.get("verified") is not True or any(verdict.get(k) != v for k, v in expected.items())):
            raise DurableIdentityError("identity_attestation_verdict_invalid")
        now = self.store._now()
        if (not timestamp(verdict["verified_at"]) or not timestamp(verdict["expires_at"])
                or not now - 120 <= verdict["verified_at"] <= now
                or not now < verdict["expires_at"] <= challenge.expires_at):
            raise DurableIdentityError("identity_attestation_freshness_invalid")
        return self.store.accept_attestation(challenge=challenge, proof_digest=expected["proof_sha256"],
                                             verification_receipt=_text(verdict["receipt_id"]))

    def issue(self, *, subject: str, device_id: str, session_id: str, audience: str,
              scopes: list[str], ttl_seconds: int = 300, timeout_seconds: float = 8) -> str:
        if not deadline(timeout_seconds):
            raise DurableIdentityError("identity_broker_deadline_invalid")
        now = self.store._now()
        self.verifier.require_key(self.active_key_id, now=now)
        claims = self.store.prepare_token(subject=subject, device_id=device_id, session_id=session_id,
                                           audience=audience, scopes=scopes, key_id=self.active_key_id,
                                           ttl_seconds=ttl_seconds)
        try:
            self.verifier.require_key(self.active_key_id, now=self.store._now(), expires_at=claims["exp"])
            header = {"alg": "EdDSA", "typ": "HGAT2", "kid": self.active_key_id}
            encoded = _b64(canonical_claims(header)) + "." + _b64(canonical_claims(claims))
            payload = encoded.encode("ascii")
            signed = self.broker.sign(payload, key_id=self.active_key_id, request_id=claims["jti"],
                                      timeout_seconds=timeout_seconds)
            if (not isinstance(signed, dict)
                    or set(signed) != {"key_id", "algorithm", "request_id", "payload_sha256", "signature", "receipt_id"}
                    or signed["key_id"] != self.active_key_id or signed["algorithm"] != "Ed25519"
                    or signed["request_id"] != claims["jti"]
                    or signed["payload_sha256"] != hashlib.sha256(payload).hexdigest()):
                raise DurableIdentityError("identity_signer_response_invalid")
            signature = _unb64(signed["signature"], maximum=64)
            self.verifier.verify(payload, signature, key_id=self.active_key_id, now=self.store._now())
            self.store.commit_token(claims, signer_receipt=_text(signed["receipt_id"]))
            return encoded + "." + _b64(signature)
        except BaseException:
            self.store.abandon_token(claims["jti"])
            raise

    def verify(self, token: str, *, audience: str, required_scopes: list[str]) -> dict:
        if not isinstance(token, str) or not 1 <= len(token) <= MAX_TOKEN_BYTES:
            raise DurableIdentityError("identity_token_size_invalid")
        parts = token.split(".")
        if len(parts) != 3:
            raise DurableIdentityError("identity_token_format_invalid")
        raw_header, raw_claims = _unb64(parts[0], maximum=1024), _unb64(parts[1], maximum=12000)
        header, claims = strict_json(raw_header), strict_json(raw_claims)
        if (set(header) != {"alg", "typ", "kid"} or header["alg"] != "EdDSA" or header["typ"] != "HGAT2"
                or canonical_claims(header) != raw_header or canonical_claims(claims) != raw_claims
                or not isinstance(header["kid"], str) or header["kid"] != claims.get("kid")):
            raise DurableIdentityError("identity_token_header_invalid")
        self.verifier.verify((parts[0] + "." + parts[1]).encode("ascii"),
                             _unb64(parts[2], maximum=64), key_id=header["kid"], now=self.store._now())
        return self.store.require_token(claims, audience=audience, required_scopes=required_scopes)
