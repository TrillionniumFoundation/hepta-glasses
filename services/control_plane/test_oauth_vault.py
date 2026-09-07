from __future__ import annotations

import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path

from services.control_plane.oauth_vault import (
    DurableOAuthVault,
    OAuthTokenSet,
    OAuthVaultError,
)


class Cipher:
    def __init__(self) -> None:
        self.keys = {"subject-a": {"key-a": b"k" * 32}}
        self.current = {"subject-a": "key-a"}

    def current_key_id(self, *, subject: str) -> str:
        return self.current[subject]

    def encrypt(self, *, subject: str, key_id: str,
                plaintext: bytes, aad: bytes) -> bytes:
        key = self.keys[subject][key_id]
        stream = hashlib.sha256(key + aad).digest()
        body = bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(plaintext))
        return hmac.new(key, aad + body, hashlib.sha256).digest() + body

    def decrypt(self, *, subject: str, key_id: str,
                ciphertext: bytes, aad: bytes) -> bytes:
        key = self.keys[subject][key_id]
        tag, body = ciphertext[:32], ciphertext[32:]
        if not hmac.compare_digest(tag, hmac.new(
                key, aad + body, hashlib.sha256).digest()):
            raise ValueError("integrity")
        stream = hashlib.sha256(key + aad).digest()
        return bytes(value ^ stream[index % len(stream)]
                     for index, value in enumerate(body))


class Provider:
    provider_id = "google"

    def __init__(self, clock) -> None:
        self.clock = clock
        self.exchange_calls = []
        self.refresh_calls = []
        self.revoke_calls = []
        self.failure = None
        self.refresh_token = "refresh-token-value-000000000000"

    def exchange_code(self, **kwargs) -> OAuthTokenSet:
        self.exchange_calls.append(dict(kwargs))
        if self.failure:
            raise self.failure
        return OAuthTokenSet(
            account_id="calendar-account@example.com",
            scopes=tuple(kwargs["requested_scopes"]),
            refresh_token=self.refresh_token,
            access_token="access-token-value-0000000000000",
            access_expires_at=self.clock() + 300,
            provider_receipt_id="exchange-receipt-1",
        )

    def refresh_access(self, **kwargs) -> OAuthTokenSet:
        self.refresh_calls.append(dict(kwargs))
        if self.failure:
            raise self.failure
        # Keeping the exact refresh token is a valid provider outcome.  The
        # vault still rebinds it under a fresh generation before release.
        return OAuthTokenSet(
            account_id="calendar-account@example.com",
            scopes=tuple(kwargs["requested_scopes"]),
            refresh_token=kwargs["refresh_token"],
            access_token="rotated-access-token-000000000000",
            access_expires_at=self.clock() + 200,
            provider_receipt_id="refresh-receipt-1",
        )

    def revoke_refresh(self, **kwargs) -> str:
        self.revoke_calls.append(dict(kwargs))
        if self.failure:
            raise self.failure
        return "provider-revoke-receipt-1"


class OAuthVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "oauth.sqlite")
        self.now = 100
        self.provider = Provider(lambda: self.now)
        self.cipher = Cipher()
        self.vault = DurableOAuthVault(
            self.path,
            cipher=self.cipher,
            providers=(self.provider,),
            clock=lambda: self.now,
        )
        self.addCleanup(lambda: self.vault.close())
        self.verifier = "v" * 64
        self.scopes = (
            "urn:hepta:test:calendar-owned",
        )

    def begin(self) -> str:
        return self.vault.begin_authorization(
            subject="subject-a",
            account_hint="calendar-account@example.com",
            provider="google",
            redirect_uri="https://accounts.example.test/oauth/callback",
            scopes=self.scopes,
            code_challenge=self.vault.pkce_challenge(self.verifier),
            expires_at=200,
        )

    def complete(self) -> str:
        return self.vault.complete_authorization(
            state=self.begin(),
            code_verifier=self.verifier,
            authorization_code="authorization-code-000000000000",
        )

    def assert_code(self, code: str, callback) -> None:
        with self.assertRaises(OAuthVaultError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_state_is_single_use_and_exact_pkce_bound(self) -> None:
        state = self.begin()
        self.assert_code(
            "oauth_pkce_mismatch",
            lambda: self.vault.complete_authorization(
                state=state,
                code_verifier="x" * 64,
                authorization_code="authorization-code-000000000000",
            ),
        )
        credential = self.vault.complete_authorization(
            state=state,
            code_verifier=self.verifier,
            authorization_code="authorization-code-000000000000",
        )
        self.assertTrue(credential)
        self.assert_code(
            "oauth_state_replayed_or_unknown",
            lambda: self.vault.complete_authorization(
                state=state,
                code_verifier=self.verifier,
                authorization_code="authorization-code-000000000000",
            ),
        )
        self.assertEqual(len(self.provider.exchange_calls), 1)

    def test_exchange_failure_is_persistently_indeterminate(self) -> None:
        state = self.begin()
        self.provider.failure = RuntimeError("provider detail")
        self.assert_code(
            "oauth_exchange_indeterminate",
            lambda: self.vault.complete_authorization(
                state=state,
                code_verifier=self.verifier,
                authorization_code="authorization-code-000000000000",
            ),
        )
        self.provider.failure = None
        self.assert_code(
            "oauth_state_replayed_or_unknown",
            lambda: self.vault.complete_authorization(
                state=state,
                code_verifier=self.verifier,
                authorization_code="authorization-code-000000000000",
            ),
        )
        state_value = self.vault.db.execute(
            "SELECT state FROM oauth_states"
        ).fetchone()[0]
        self.assertEqual(state_value, "indeterminate")

    def test_grant_revalidates_before_and_after_provider_io(self) -> None:
        credential = self.complete()
        calls = []
        grant = self.vault.grant_access(
            subject="subject-a",
            account_id="calendar-account@example.com",
            provider="google",
            scopes=self.scopes,
            authorize=lambda: calls.append("checked"),
        )
        self.assertEqual(grant.credential_id, credential)
        self.assertEqual(grant.access_token, "rotated-access-token-000000000000")
        self.assertEqual(calls, ["checked", "checked"])
        self.assertEqual(len(self.provider.refresh_calls), 1)

    def test_local_revoke_precedes_remote_cleanup(self) -> None:
        self.complete()
        self.vault.revoke(
            subject="subject-a",
            account_id="calendar-account@example.com",
            provider="google",
        )
        self.assert_code(
            "oauth_credential_unavailable",
            lambda: self.vault.grant_access(
                subject="subject-a",
                account_id="calendar-account@example.com",
                provider="google",
                scopes=self.scopes,
                authorize=lambda: None,
            ),
        )
        pending = self.vault.pending_revocations()
        self.assertEqual(len(pending), 1)
        receipt = self.vault.deliver_revocation(sequence=pending[0].sequence)
        self.assertEqual(receipt, "provider-revoke-receipt-1")
        self.assertEqual(self.vault.pending_revocations(), [])
        self.assertEqual(len(self.provider.revoke_calls), 1)

    def test_remote_revoke_failure_remains_pending(self) -> None:
        self.complete()
        self.vault.revoke(
            subject="subject-a",
            account_id="calendar-account@example.com",
            provider="google",
        )
        event = self.vault.pending_revocations()[0]
        self.provider.failure = RuntimeError("provider detail")
        self.assert_code(
            "oauth_remote_revoke_indeterminate",
            lambda: self.vault.deliver_revocation(sequence=event.sequence),
        )
        self.assertEqual(len(self.vault.pending_revocations()), 1)
        attempts = self.vault.db.execute(
            "SELECT attempts FROM oauth_revoke_outbox WHERE sequence=?",
            (event.sequence,),
        ).fetchone()[0]
        self.assertEqual(attempts, 1)

    def test_restart_preserves_credential_and_revoke_outbox(self) -> None:
        self.complete()
        self.vault.revoke(
            subject="subject-a",
            account_id="calendar-account@example.com",
            provider="google",
        )
        self.vault.close()
        self.vault = DurableOAuthVault(
            self.path,
            cipher=self.cipher,
            providers=(self.provider,),
            clock=lambda: self.now,
        )
        self.assertEqual(len(self.vault.pending_revocations()), 1)
        self.vault.deliver_revocation(
            sequence=self.vault.pending_revocations()[0].sequence
        )
        self.assertEqual(self.vault.pending_revocations(), [])

    def test_no_code_access_or_refresh_token_plaintext_is_persisted(self) -> None:
        state = self.begin()
        code = "authorization-code-plain-sentinel"
        self.vault.complete_authorization(
            state=state,
            code_verifier=self.verifier,
            authorization_code=code,
        )
        self.vault.checkpoint()
        raw = Path(self.path).read_bytes()
        for secret in (
            state,
            self.verifier,
            code,
            self.provider.refresh_token,
            "access-token-value-0000000000000",
        ):
            self.assertNotIn(secret.encode("utf-8"), raw)

    def test_expiry_account_and_scope_bindings_fail_closed(self) -> None:
        state = self.begin()
        self.now = 200
        self.assert_code(
            "oauth_state_expired",
            lambda: self.vault.complete_authorization(
                state=state,
                code_verifier=self.verifier,
                authorization_code="authorization-code-000000000000",
            ),
        )
        self.now = 100
        self.complete()
        self.assert_code(
            "oauth_credential_unavailable",
            lambda: self.vault.grant_access(
                subject="subject-other",
                account_id="calendar-account@example.com",
                provider="google",
                scopes=self.scopes,
                authorize=lambda: None,
            ),
        )
        self.assert_code(
            "oauth_scope_denied",
            lambda: self.vault.grant_access(
                subject="subject-a",
                account_id="calendar-account@example.com",
                provider="google",
                scopes=("scope-not-granted",),
                authorize=lambda: None,
            ),
        )


if __name__ == "__main__":
    unittest.main()
