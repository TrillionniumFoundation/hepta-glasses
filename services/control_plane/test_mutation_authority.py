from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.control_plane.mutation_authority import (
    DEFAULT_AUDIENCE,
    REQUIRED_SCOPE,
    MutationIngressError,
    MutationLeaseAuthority,
    MutationPrincipal,
)


class Identity:
    def __init__(self, principal: MutationPrincipal) -> None:
        self.principal = principal
        self.calls: list[dict[str, str]] = []
        self.failure: Exception | None = None

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> MutationPrincipal:
        self.calls.append({
            "bearer_token": bearer_token,
            "audience": audience,
            "required_scope": required_scope,
        })
        if self.failure is not None:
            raise self.failure
        return self.principal


class MutationLeaseAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.principal = MutationPrincipal(
            subject="subject-1",
            device_id="device-1",
            session_id="session-1",
            audience=DEFAULT_AUDIENCE,
            scopes=(REQUIRED_SCOPE,),
            policy_hash="a" * 64,
            user_present=True,
            biometric_verified=False,
            expires_at=1200,
        )
        self.identity = Identity(self.principal)
        self.path = str(Path(self.temp.name) / "authority.db")
        self.authority = MutationLeaseAuthority(
            self.path,
            identity=self.identity,
            clock=lambda: self.now,
        )
        self.addCleanup(self.authority.close)

    @staticmethod
    def body(**changes: object) -> bytes:
        document: dict[str, object] = {
            "task_id": "task-1",
            "action": "device.display_text",
            "arguments": {"text": "hello"},
            "risk_tier": "r1",
            "deadline_epoch_seconds": 1100,
        }
        document.update(changes)
        return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()

    def authorize(self, **changes: object) -> dict[str, object]:
        return self.authority.authorize(
            authorization="Bearer account-session-token-123456",
            body=self.body(**changes),
        )

    def error(self, code: str, status: int, callback) -> None:
        with self.assertRaises(MutationIngressError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.status, status)

    def test_success_is_exact_and_stores_only_argument_digest(self) -> None:
        result = self.authorize()
        self.assertEqual(set(result), {
            "task_id", "action", "risk_tier", "argument_digest", "subject",
            "device_id", "policy_hash", "authenticated", "user_present",
            "biometric_verified", "lease_id", "allowed_actions",
            "issued_at_epoch_seconds", "expires_at_epoch_seconds", "single_use",
        })
        self.assertEqual(result["task_id"], "task-1")
        self.assertEqual(result["allowed_actions"], ["device.display_text"])
        self.assertTrue(result["single_use"])
        self.assertEqual(result["expires_at_epoch_seconds"], 1060)
        expected = hashlib.sha256(b'{"text":"hello"}').hexdigest()
        self.assertEqual(result["argument_digest"], expected)
        dump = "\n".join(self.authority.db.iterdump())
        self.assertNotIn("hello", dump)
        self.assertNotIn("account-session-token", dump)
        self.assertEqual(self.identity.calls[0]["audience"], DEFAULT_AUDIENCE)

    def test_exact_duplicate_reuses_one_lease_without_new_row(self) -> None:
        first = self.authorize()
        second = self.authorize()
        self.assertEqual(first["lease_id"], second["lease_id"])
        count = self.authority.db.execute(
            "SELECT COUNT(*) FROM mutation_leases"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_action_risk_and_presence_policy_fail_before_lease(self) -> None:
        self.error(
            "mutation_authority_action_denied",
            403,
            lambda: self.authorize(risk_tier="r2"),
        )
        self.principal = MutationPrincipal(
            **{**self.principal.__dict__, "user_present": False}
        )
        self.identity.principal = self.principal
        self.error(
            "mutation_authority_user_presence_required",
            403,
            lambda: self.authorize(
                action="device.microphone_on",
                risk_tier="r2",
            ),
        )
        self.assertEqual(
            self.authority.db.execute(
                "SELECT COUNT(*) FROM mutation_leases"
            ).fetchone()[0],
            0,
        )

    def test_r3_requires_current_biometric_proof(self) -> None:
        authority = MutationLeaseAuthority(
            str(Path(self.temp.name) / "r3.db"),
            identity=self.identity,
            clock=lambda: self.now,
            action_policy={"account.sensitive": "r3"},
        )
        self.addCleanup(authority.close)
        body = json.dumps({
            "task_id": "task-1",
            "action": "account.sensitive",
            "arguments": {},
            "risk_tier": "r3",
            "deadline_epoch_seconds": 1010,
        }, separators=(",", ":")).encode()
        self.error(
            "mutation_authority_biometric_required",
            403,
            lambda: authority.authorize(
                authorization="Bearer account-session-token-123456",
                body=body,
            ),
        )

    def test_revocation_is_monotonic_and_invalidates_issued_lease(self) -> None:
        lease = self.authorize()
        self.authority.revoke("session", "session-1")
        state = self.authority.db.execute(
            "SELECT state FROM mutation_leases WHERE lease_id=?",
            (lease["lease_id"],),
        ).fetchone()[0]
        self.assertEqual(state, "revoked")
        self.error(
            "mutation_authority_revoked",
            403,
            self.authorize,
        )
        self.authority.revoke("session", "session-1")
        self.assertEqual(
            self.authority.db.execute(
                "SELECT COUNT(*) FROM mutation_revocations"
            ).fetchone()[0],
            1,
        )

    def test_duplicate_json_unknown_fields_and_bool_deadline_fail(self) -> None:
        duplicate = (
            b'{"task_id":"task-1","task_id":"task-1",'
            b'"action":"device.display_text","arguments":{},'
            b'"risk_tier":"r1","deadline_epoch_seconds":1100}'
        )
        self.error(
            "mutation_authority_json_invalid",
            400,
            lambda: self.authority.authorize(
                authorization="Bearer account-session-token-123456",
                body=duplicate,
            ),
        )
        self.error(
            "mutation_authority_request_shape_invalid",
            400,
            lambda: self.authorize(extra=True),
        )
        self.error(
            "mutation_authority_request_invalid",
            400,
            lambda: self.authorize(deadline_epoch_seconds=True),
        )

    def test_identity_failure_and_malformed_principal_are_sanitized(self) -> None:
        self.identity.failure = RuntimeError("sensitive provider text")
        self.error("mutation_authority_unauthorized", 401, self.authorize)
        self.identity.failure = None
        self.identity.principal = MutationPrincipal(
            **{**self.principal.__dict__, "subject": "bad subject"}
        )
        self.error("mutation_authority_unauthorized", 401, self.authorize)

    def test_policy_drift_on_reopen_requires_explicit_migration(self) -> None:
        self.authority.close()
        self.addCleanup(lambda: None)
        with self.assertRaises(MutationIngressError) as raised:
            MutationLeaseAuthority(
                self.path,
                identity=self.identity,
                clock=lambda: self.now,
                maximum_lease_seconds=30,
            )
        self.assertEqual(
            raised.exception.code,
            "mutation_authority_policy_migration_required",
        )

    def test_expired_or_revoked_principal_cannot_issue(self) -> None:
        self.identity.principal = MutationPrincipal(
            **{**self.principal.__dict__, "expires_at": self.now}
        )
        self.error("mutation_authority_unauthorized", 401, self.authorize)
        self.identity.principal = MutationPrincipal(
            **{**self.principal.__dict__, "scopes": ("mutation.read",)}
        )
        self.error("mutation_authority_scope_denied", 403, self.authorize)


if __name__ == "__main__":
    unittest.main()
