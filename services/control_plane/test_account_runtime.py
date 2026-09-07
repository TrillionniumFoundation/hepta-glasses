from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.control_plane.account_runtime import (
    AccountRuntimeError,
    DurableAccountRuntime,
)
from services.control_plane.authenticated_principals import (
    AuthenticatedPrincipalAdapter,
)
from services.control_plane.mutation_authority import (
    DEFAULT_AUDIENCE as MUTATION_AUDIENCE,
    REQUIRED_SCOPE as MUTATION_SCOPE,
)
from services.model_gateway.model_ingress import (
    DEFAULT_AUDIENCE as MODEL_AUDIENCE,
    REQUIRED_SCOPE as MODEL_SCOPE,
)
from services.model_gateway.speech_ingress import (
    DEFAULT_AUDIENCE as SPEECH_AUDIENCE,
    REQUIRED_SCOPE as SPEECH_SCOPE,
)


POLICY = "a" * 64


class DurableAccountRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "accounts.sqlite")
        self.now = 100
        self.store = DurableAccountRuntime(self.path, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.store.register_subject(subject="subject-a", device_id="phone-a")
        self.session = self.store.open_session(
            subject="subject-a",
            device_id="phone-a",
            session_id="session-a",
            expires_at=1_000,
        )
        self.store.bind_pair(
            session_id="session-a",
            pair_identity="g1-left-right-a",
            expires_at=900,
        )

    def token(self, *, audience: str, scope: str, expires_at: int = 300) -> str:
        return self.store.issue_access(
            session_id="session-a",
            audience=audience,
            scopes=(scope,),
            policy_hash=POLICY,
            expires_at=expires_at,
            user_present=True,
            biometric_verified=True,
        )

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(AccountRuntimeError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_rotation_does_not_shorten_session_lifetime(self) -> None:
        first = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE, expires_at=200)
        claims = self.store.verify_access(
            bearer_token=first,
            audience=MODEL_AUDIENCE,
            required_scope=MODEL_SCOPE,
        )
        self.assertEqual(claims.expires_at, 200)
        second = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE, expires_at=400)
        self.assert_code(
            "account_access_denied",
            lambda: self.store.verify_access(
                bearer_token=first,
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            ),
        )
        self.assertEqual(
            self.store.verify_access(
                bearer_token=second,
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            ).expires_at,
            400,
        )
        row = self.store.db.execute(
            "SELECT expires_at,state FROM account_sessions WHERE session_id='session-a'"
        ).fetchone()
        self.assertEqual((row["expires_at"], row["state"]), (1_000, "active"))

    def test_one_authority_drives_model_speech_and_mutation_principals(self) -> None:
        adapter = AuthenticatedPrincipalAdapter(
            access=self.store,
            pairs=self.store,
            clock=lambda: self.now,
        )
        model = adapter.verify(
            bearer_token=self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE),
            audience=MODEL_AUDIENCE,
            required_scope=MODEL_SCOPE,
        )
        speech = adapter.verify(
            bearer_token=self.token(audience=SPEECH_AUDIENCE, scope=SPEECH_SCOPE),
            audience=SPEECH_AUDIENCE,
            required_scope=SPEECH_SCOPE,
        )
        mutation = adapter.verify(
            bearer_token=self.token(
                audience=MUTATION_AUDIENCE, scope=MUTATION_SCOPE
            ),
            audience=MUTATION_AUDIENCE,
            required_scope=MUTATION_SCOPE,
        )
        self.assertEqual(model.subject, "subject-a")
        self.assertEqual(speech.pair_identity, "g1-left-right-a")
        self.assertEqual(mutation.device_id, "g1-left-right-a")
        self.assertTrue(mutation.user_present)
        self.assertTrue(mutation.biometric_verified)

    def test_session_revoke_is_immediate_and_fans_out(self) -> None:
        token = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE)
        self.store.revoke_session(session_id="session-a", reason="logout")
        self.assert_code(
            "account_access_denied",
            lambda: self.store.verify_access(
                bearer_token=token,
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            ),
        )
        self.assert_code(
            "account_session_revoked",
            lambda: self.store.resolve_pair(
                subject="subject-a",
                device_id="phone-a",
                session_id="session-a",
            ),
        )
        events = self.store.pending_revocations()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reason, "logout")
        self.store.acknowledge_revocation(sequence=events[0].sequence)
        self.assertEqual(self.store.pending_revocations(), [])

    def test_lost_device_replacement_revokes_every_old_session(self) -> None:
        other = self.store.open_session(
            subject="subject-a",
            device_id="phone-a",
            session_id="session-b",
            expires_at=1_000,
        )
        token_a = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE)
        token_b = self.store.issue_access(
            session_id=other.session_id,
            audience=MODEL_AUDIENCE,
            scopes=(MODEL_SCOPE,),
            policy_hash=POLICY,
            expires_at=300,
        )
        self.store.replace_lost_device(
            subject="subject-a",
            old_device_id="phone-a",
            new_device_id="phone-b",
        )
        for token in (token_a, token_b):
            self.assert_code(
                "account_access_denied",
                lambda token=token: self.store.verify_access(
                    bearer_token=token,
                    audience=MODEL_AUDIENCE,
                    required_scope=MODEL_SCOPE,
                ),
            )
        self.assertEqual(len(self.store.pending_revocations()), 2)
        replacement = self.store.open_session(
            subject="subject-a",
            device_id="phone-b",
            session_id="session-c",
            expires_at=1_000,
        )
        self.assertEqual(replacement.device_id, "phone-b")

    def test_restart_preserves_token_pair_and_revocation_state(self) -> None:
        token = self.token(audience=SPEECH_AUDIENCE, scope=SPEECH_SCOPE)
        self.store.close()
        self.store = DurableAccountRuntime(self.path, clock=lambda: self.now)
        claims = self.store.verify_access(
            bearer_token=token,
            audience=SPEECH_AUDIENCE,
            required_scope=SPEECH_SCOPE,
        )
        pair = self.store.resolve_pair(
            subject=claims.subject,
            device_id=claims.device_id,
            session_id=claims.session_id,
        )
        self.assertEqual(pair.pair_identity, "g1-left-right-a")
        self.store.revoke_session(session_id="session-a", reason="remote_revoke")
        self.store.close()
        self.store = DurableAccountRuntime(self.path, clock=lambda: self.now)
        self.assert_code(
            "account_access_denied",
            lambda: self.store.verify_access(
                bearer_token=token,
                audience=SPEECH_AUDIENCE,
                required_scope=SPEECH_SCOPE,
            ),
        )
        self.assertEqual(self.store.pending_revocations()[0].reason, "remote_revoke")

    def test_token_expiry_does_not_expire_session(self) -> None:
        token = self.token(
            audience=MODEL_AUDIENCE,
            scope=MODEL_SCOPE,
            expires_at=101,
        )
        self.now = 101
        self.assert_code(
            "account_access_denied",
            lambda: self.store.verify_access(
                bearer_token=token,
                audience=MODEL_AUDIENCE,
                required_scope=MODEL_SCOPE,
            ),
        )
        row = self.store.db.execute(
            "SELECT state,expires_at FROM account_sessions WHERE session_id='session-a'"
        ).fetchone()
        self.assertEqual((row["state"], row["expires_at"]), ("active", 1_000))

    def test_scope_audience_and_pair_binding_fail_closed(self) -> None:
        token = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE)
        for audience, scope in (
            (SPEECH_AUDIENCE, MODEL_SCOPE),
            (MODEL_AUDIENCE, SPEECH_SCOPE),
        ):
            self.assert_code(
                "account_access_denied",
                lambda audience=audience, scope=scope: self.store.verify_access(
                    bearer_token=token,
                    audience=audience,
                    required_scope=scope,
                ),
            )
        self.assert_code(
            "account_pair_denied",
            lambda: self.store.resolve_pair(
                subject="subject-a",
                device_id="phone-other",
                session_id="session-a",
            ),
        )

    def test_plaintext_bearer_is_not_persisted(self) -> None:
        token = self.token(audience=MODEL_AUDIENCE, scope=MODEL_SCOPE)
        raw = self.store.database_bytes()
        self.assertNotIn(token.encode("utf-8"), raw)
        self.assertIn(self.store._token_digest(token).encode("ascii"), raw)

    def test_complete_authority_table_loss_fails_closed(self) -> None:
        self.store.close()
        connection = __import__("sqlite3").connect(self.path)
        connection.execute("DROP TABLE account_tokens")
        connection.commit()
        connection.close()
        self.assert_code(
            "account_runtime_schema_invalid",
            lambda: DurableAccountRuntime(self.path, clock=lambda: self.now),
        )


if __name__ == "__main__":
    unittest.main()
