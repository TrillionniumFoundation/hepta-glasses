"""Local identity invariants; never platform-attestation or live KMS evidence."""
import dataclasses
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from services.control_plane.durable_identity import (
    DurableIdentityError, DurableIdentityStore, EnrollmentChallenge,
)


class Clock:
    now = 1000
    def __call__(self):
        return self.now


class DurableIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "identity.db")
        self.clock = Clock()
        self.stores = []
        self.store = self.open()
        self.store.admit_subject("subject")

    def open(self, **kwargs):
        config = dict(issuer="hepta", allowed_scopes=("display", "memory"), clock=self.clock)
        config.update(kwargs)
        store = DurableIdentityStore(self.path, **config)
        self.stores.append(store)
        return store

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.tmp.cleanup()

    def challenge(self, **kwargs):
        config = dict(subject="subject", device_id="device", platform="android",
                      application_id="app", signer_digest="a" * 64)
        config.update(kwargs)
        return self.store.challenge(**config)

    def enroll(self):
        return self.store.accept_attestation(challenge=self.challenge(),
                                            proof_digest="b" * 64, verification_receipt="fixture-verified")

    def session(self, **kwargs):
        self.enroll()
        config = dict(subject="subject", device_id="device", audience="mobile",
                      scopes=["display", "memory"])
        config.update(kwargs)
        return self.store.create_session(**config)

    def prepared(self):
        return self.store.prepare_token(subject="subject", device_id="device",
                                        session_id=self.session(), audience="mobile",
                                        scopes=["display"], key_id="kid")

    def active(self):
        claims = self.prepared()
        self.store.commit_token(claims, signer_receipt="fixture-signer")
        return claims

    def verify(self, claims, store=None):
        return (store or self.store).require_token(claims, audience="mobile", required_scopes=["display"])

    def test_roundtrip_across_connections_and_restart(self):
        claims = self.active()
        self.assertEqual(self.verify(claims, self.open()), claims)

    def test_no_raw_nonce_or_bearer_is_persisted(self):
        challenge = self.challenge()
        dump = "\n".join(self.store.db.iterdump())
        self.assertNotIn(challenge.nonce, dump)
        self.assertIn(hashlib.sha256(challenge.nonce.encode()).hexdigest(), dump)
        self.assertNotIn("PRIVATE KEY", dump)

    def test_unknown_subject_cannot_enroll(self):
        with self.assertRaisesRegex(DurableIdentityError, "subject_unavailable"):
            self.challenge(subject="unknown")

    def test_subject_revocation_blocks_readmission_and_enrollment(self):
        challenge = self.challenge()
        self.open().revoke("subject", "subject")
        with self.assertRaises(DurableIdentityError):
            self.store.admit_subject("subject")
        with self.assertRaises(DurableIdentityError):
            self.store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")

    def test_unknown_device_revoked_during_attestation_cannot_be_created(self):
        challenge = self.challenge()
        self.open().revoke("device", "device")
        with self.assertRaisesRegex(DurableIdentityError, "revoked|spent"):
            self.store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM identity_devices").fetchone()[0], 0)

    def test_challenge_replay_is_rejected(self):
        challenge = self.challenge()
        self.store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")
        with self.assertRaisesRegex(DurableIdentityError, "spent"):
            self.open().accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")

    def test_challenge_exact_fields_are_bound(self):
        challenge = self.challenge()
        for field, value in (("device_id", "other"), ("application_id", "other"),
                             ("platform", "ios"), ("signer_digest", "c" * 64), ("expires_at", 9999)):
            with self.subTest(field=field):
                changed = dataclasses.replace(challenge, **{field: value})
                with self.assertRaises(DurableIdentityError):
                    self.store.accept_attestation(challenge=changed, proof_digest="b" * 64,
                                                  verification_receipt="fixture")
        self.store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")

    def test_challenge_expired_at_exact_boundary(self):
        challenge = self.challenge(ttl_seconds=10)
        self.clock.now += 10
        with self.assertRaisesRegex(DurableIdentityError, "expired"):
            self.store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")

    def test_concurrent_challenge_consumption_only_one_wins(self):
        challenge = self.challenge()
        second = self.open()
        start = threading.Barrier(3)
        results = []
        def consume(store):
            start.wait()
            try:
                store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")
                results.append("ok")
            except DurableIdentityError:
                results.append("denied")
        workers = [threading.Thread(target=consume, args=(s,)) for s in (self.store, second)]
        for w in workers: w.start()
        start.wait()
        for w in workers:
            w.join(3)
            self.assertFalse(w.is_alive())
        self.assertEqual(sorted(results), ["denied", "ok"])

    def test_subject_collision_does_not_change_device_owner(self):
        self.enroll()
        self.store.admit_subject("other")
        with self.assertRaisesRegex(DurableIdentityError, "conflict"):
            self.challenge(subject="other")
        self.assertEqual(self.store.db.execute("SELECT subject FROM identity_devices").fetchone()[0], "subject")

    def test_changed_proof_requires_recovery(self):
        self.enroll()
        challenge = self.challenge()
        with self.assertRaisesRegex(DurableIdentityError, "recovery_required"):
            self.store.accept_attestation(challenge=challenge, proof_digest="c" * 64, verification_receipt="fixture")

    def test_session_scope_admission_is_allowlisted(self):
        self.enroll()
        with self.assertRaisesRegex(DurableIdentityError, "scope_not_allowed"):
            self.store.create_session(subject="subject", device_id="device", audience="mobile", scopes=["shell"])

    def test_scope_and_audience_cannot_expand_at_issue(self):
        session = self.session(scopes=["display"])
        for scopes, audience in ((["memory"], "mobile"), (["display"], "other")):
            with self.subTest(scopes=scopes, audience=audience):
                with self.assertRaisesRegex(DurableIdentityError, "escalation"):
                    self.store.prepare_token(subject="subject", device_id="device", session_id=session,
                                             audience=audience, scopes=scopes, key_id="kid")

    def test_token_cannot_outlive_session(self):
        session = self.session(ttl_seconds=10)
        with self.assertRaisesRegex(DurableIdentityError, "outlives"):
            self.store.prepare_token(subject="subject", device_id="device", session_id=session,
                                     audience="mobile", scopes=["display"], key_id="kid", ttl_seconds=11)

    def test_prepared_token_has_no_authority(self):
        with self.assertRaisesRegex(DurableIdentityError, "not_active"):
            self.verify(self.prepared())

    def test_revocation_before_commit_blocks_each_authority_dimension(self):
        for kind, field in (("subject", "sub"), ("device", "device_id"), ("session", "session_id"), ("token", "jti")):
            with self.subTest(kind=kind):
                # Isolate terminal tombstones between dimensions.
                path = str(Path(self.tmp.name) / (kind + ".db"))
                store = DurableIdentityStore(path, issuer="hepta", allowed_scopes=["display"], clock=self.clock)
                try:
                    store.admit_subject("s")
                    challenge = store.challenge(subject="s", device_id="d", platform="ios",
                                                application_id="app", signer_digest="a" * 64)
                    store.accept_attestation(challenge=challenge, proof_digest="b" * 64, verification_receipt="fixture")
                    session = store.create_session(subject="s", device_id="d", audience="a", scopes=["display"])
                    claims = store.prepare_token(subject="s", device_id="d", session_id=session, audience="a",
                                                 scopes=["display"], key_id="kid")
                    store.revoke(kind, claims[field])
                    with self.assertRaises(DurableIdentityError):
                        store.commit_token(claims, signer_receipt="late")
                    store.abandon_token(claims["jti"])
                    self.assertEqual(store.db.execute("SELECT state FROM identity_tokens").fetchone()[0], "revoked")
                finally:
                    store.close()

    def test_active_token_rejected_after_cross_connection_revoke(self):
        claims = self.active()
        self.open().revoke("session", claims["session_id"])
        with self.assertRaises(DurableIdentityError):
            self.verify(claims)

    def test_claims_tampering_rejected_even_with_valid_shape(self):
        claims = self.active()
        for field, value in (("jti", "forged"), ("kid", "unknown"), ("sub", "other"),
                             ("device_id", "other"), ("iat", 1001), ("exp", 1500),
                             ("iss", "other"), ("scope", ["memory"])):
            with self.subTest(field=field):
                with self.assertRaises(DurableIdentityError):
                    self.verify({**claims, field: value})

    def test_expired_token_not_valid_at_boundary(self):
        claims = self.active()
        self.clock.now = claims["exp"]
        with self.assertRaisesRegex(DurableIdentityError, "time_or_issuer"):
            self.verify(claims)

    def test_boolean_timestamps_and_scope_strings_rejected(self):
        claims = self.active()
        for field, value in (("iat", True), ("exp", True), ("scope", "display"),
                             ("scope", ["display", "display"]), ("scope", [])):
            with self.subTest(field=field, value=value):
                with self.assertRaises(DurableIdentityError):
                    self.verify({**claims, field: value})

    def test_scope_required_at_every_verification(self):
        claims = self.active()
        with self.assertRaises(DurableIdentityError):
            self.store.require_token(claims, audience="mobile", required_scopes=[])
        with self.assertRaisesRegex(DurableIdentityError, "insufficient"):
            self.store.require_token(claims, audience="mobile", required_scopes=["memory"])

    def test_response_does_not_alias_caller_claims(self):
        claims = self.active()
        verified = self.verify(claims)
        verified["scope"].append("other")
        self.assertEqual(self.verify(claims)["scope"], ["display"])

    def test_unresolved_signing_survives_reopen_but_never_activates(self):
        claims = self.prepared()
        second = self.open()
        self.assertEqual(second.pending_tokens(), [claims["jti"]])
        second.abandon_token(claims["jti"])
        self.assertEqual(self.store.pending_tokens(), [claims["jti"]])
        with self.assertRaisesRegex(DurableIdentityError, "not_prepared"):
            self.store.commit_token(claims, signer_receipt="late")

    def test_terminal_commit_storage_failure_rolls_back(self):
        claims = self.prepared()
        self.store.db.execute("CREATE TRIGGER fail_token BEFORE UPDATE ON identity_tokens "
                              "WHEN NEW.state='active' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.commit_token(claims, signer_receipt="fixture")
        self.assertEqual(self.store.pending_tokens(), [claims["jti"]])
        with self.assertRaises(DurableIdentityError):
            self.verify(claims)

    def test_idempotent_revocations_and_bounded_event_cursor(self):
        first = self.store.revoke("device", "a")
        self.assertEqual(first, self.open().revoke("device", "a"))
        second = self.store.revoke("device", "b")
        self.assertGreater(second, first)
        self.assertEqual([e["id"] for e in self.store.events_after(first)], ["b"])
        self.assertEqual(len(self.store.events_after(0, limit=1)), 1)
        for value in (True, -1, 2**64):
            with self.assertRaises(DurableIdentityError):
                self.store.events_after(value)

    def test_capacity_does_not_disable_revocation(self):
        limited = self.open(maximum_rows=1)
        with self.assertRaisesRegex(DurableIdentityError, "capacity"):
            limited.admit_subject("other")
        limited.revoke("subject", "subject")
        with self.assertRaises(DurableIdentityError):
            self.challenge()

    def test_token_id_collision_does_not_replace_authority(self):
        claims = self.active()
        with mock.patch("services.control_plane.durable_identity.secrets.token_urlsafe", return_value=claims["jti"]):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.prepare_token(subject="subject", device_id="device", session_id=claims["session_id"],
                                         audience="mobile", scopes=["display"], key_id="kid")
        self.assertEqual(self.verify(claims), claims)

    def test_expired_challenge_does_not_consume_valid_enrollment(self):
        old = self.challenge(ttl_seconds=1)
        fresh = self.challenge(ttl_seconds=60)
        self.clock.now += 1
        with self.assertRaises(DurableIdentityError):
            self.store.accept_attestation(challenge=old, proof_digest="b" * 64, verification_receipt="fixture")
        self.store.accept_attestation(challenge=fresh, proof_digest="b" * 64, verification_receipt="fixture")

    def test_identity_policy_cannot_silently_change(self):
        for config in ({"issuer": "other"}, {"allowed_scopes": ["display"]}, {"maximum_token_ttl": 600}):
            with self.subTest(config=config):
                with self.assertRaisesRegex(DurableIdentityError, "policy_migration"):
                    self.open(**config)

    def test_future_schema_fails_closed(self):
        self.store.db.execute("UPDATE hepta_component_schema SET version=9 WHERE component='identity'")
        with self.assertRaisesRegex(ValueError, "schema_migration_required"):
            self.open()

    def test_invalid_clock_and_input_fail_before_admission(self):
        self.clock.now = True
        with self.assertRaisesRegex(DurableIdentityError, "clock_invalid"):
            self.challenge()
        self.clock.now = 1000
        for value in ("", " s", "x\n", "x" * 257, True):
            with self.assertRaises(DurableIdentityError):
                self.challenge(subject=value)

    def test_process_exit_preserves_prepared_not_active(self):
        script = '''
import os,sys
from services.control_plane.durable_identity import DurableIdentityStore
s=DurableIdentityStore(sys.argv[1],issuer="test",allowed_scopes=["display"],clock=lambda:1000)
s.admit_subject("u")
c=s.challenge(subject="u",device_id="d",platform="ios",application_id="app",signer_digest="a"*64)
s.accept_attestation(challenge=c,proof_digest="b"*64,verification_receipt="fixture")
r=s.create_session(subject="u",device_id="d",audience="a",scopes=["display"])
s.prepare_token(subject="u",device_id="d",session_id=r,audience="a",scopes=["display"],key_id="k")
os._exit(73)
'''
        path = str(Path(self.tmp.name) / "crash.db")
        run = subprocess.run([sys.executable, "-c", script, path], capture_output=True, timeout=5)
        self.assertEqual(run.returncode, 73, run.stderr.decode())
        reopened = DurableIdentityStore(path, issuer="test", allowed_scopes=["display"], clock=self.clock)
        try:
            self.assertEqual(len(reopened.pending_tokens()), 1)
            self.assertEqual(reopened.db.execute("SELECT state FROM identity_tokens").fetchone()[0], "preparing")
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
