"""Real SQLite enrollment boundaries. Inert broker results are not attestation."""
from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.durable_identity import DurableIdentityError, DurableIdentityStore
from services.control_plane.identity_authority import DurableIdentityAuthority


class Broker:
    def __init__(self, clock):
        self.clock = clock
        self.changes = {}
        self.verdict = None
        self.calls = 0

    def verify_attestation(self, challenge, proof, **kwargs):
        self.calls += 1
        self.verdict = dict(
            subject=challenge.subject, device_id=challenge.device_id,
            platform=challenge.platform, application_id=challenge.application_id,
            signer_digest=challenge.signer_digest,
            nonce_sha256=hashlib.sha256(challenge.nonce.encode()).hexdigest(),
            proof_sha256=hashlib.sha256(proof).hexdigest(), verified=True,
            verified_at=self.clock(), expires_at=1001, receipt_id='inert-verdict-receipt',
        )
        self.verdict.update(self.changes)
        return self.verdict


class EnrollmentFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'identity.sqlite')
        self.now = 1000
        self.store = self.open()
        self.store.admit_subject('subject')
        self.challenge = self.new_challenge()
        self.proof = b'inert-platform-proof-no-authority'
        self.broker = Broker(lambda: self.now)
        # Enrollment does not call the token signer or public-key verifier.
        self.authority = DurableIdentityAuthority(
            self.store, broker=self.broker, verifier=None, active_key_id='unused')

    def open(self):
        s = DurableIdentityStore(self.path, issuer='fixture', allowed_scopes=['display'], clock=lambda: self.now)
        self.addCleanup(s.close)
        return s

    def new_challenge(self):
        return self.store.challenge(subject='subject', device_id='device', platform='android',
                                    application_id='app', signer_digest='a' * 64)

    def enroll(self):
        return self.authority.enroll(self.challenge, self.proof)

    def direct(self, **changes):
        arguments = dict(challenge=self.challenge, proof_digest=hashlib.sha256(self.proof).hexdigest(),
                         verification_receipt='inert-verdict-receipt', verified_at=1000,
                         verification_expires_at=1001)
        arguments.update(changes)
        return self.store.accept_attestation(**arguments)

    def error(self, code, action):
        with self.assertRaises(DurableIdentityError) as result:
            action()
        self.assertEqual(result.exception.code, code)

    def unadmitted(self):
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM identity_devices').fetchone()[0], 0)
        digest = hashlib.sha256(self.challenge.nonce.encode()).hexdigest()
        self.assertEqual(self.store.db.execute('SELECT state FROM identity_challenges WHERE digest=?',
                                               (digest,)).fetchone()[0], 'issued')

    def trigger(self, clause, callback):
        self.store.db.create_function('test_enrollment_clock', 0, lambda: (callback(), 0)[1])
        self.store.db.execute('CREATE TRIGGER enrollment_boundary ' + clause +
                             ' BEGIN SELECT test_enrollment_clock(); END')

    def test_original_broker_expiry_counterexample_is_rejected(self):
        with patch.object(self.store, '_clock', side_effect=[1000, 1002]):
            self.error('identity_attestation_freshness_invalid', self.enroll)
        self.unadmitted()
        self.assertEqual(self.broker.calls, 1)

    def test_valid_broker_window_is_accepted(self):
        self.assertEqual(self.enroll()['state'], 'active')
        self.assertEqual(self.store.db.execute('SELECT registered_at FROM identity_devices').fetchone()[0], 1000)

    def test_exact_expiry_is_rejected_in_final_store_even_when_challenge_valid(self):
        self.now = 1001
        self.error('identity_attestation_freshness_invalid', self.direct)
        self.unadmitted()

    def test_120_second_verdict_age_is_inclusive_and_121_is_rejected(self):
        self.error('identity_attestation_freshness_invalid', lambda: self.direct(verified_at=879))
        self.unadmitted()
        self.assertEqual(self.direct(verified_at=880)['state'], 'active')

    def test_future_verdict_time_is_not_accepted(self):
        self.error('identity_attestation_freshness_invalid', lambda: self.direct(verified_at=1001))
        self.unadmitted()

    def test_broker_verdict_cannot_outlive_the_exact_challenge(self):
        self.error('identity_attestation_freshness_invalid',
                   lambda: self.direct(verification_expires_at=self.challenge.expires_at + 1))
        self.broker.changes['expires_at'] = self.challenge.expires_at + 1
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.unadmitted()

    def test_verdict_times_require_real_integer_timestamps(self):
        for name in ('verified_at', 'verification_expires_at'):
            for value in (True, False, '1000', 1000.0, float('nan'), -1, None):
                with self.subTest(name=name, value=value):
                    self.error('identity_attestation_freshness_invalid', lambda: self.direct(**{name: value}))
        self.unadmitted()

    def test_receipt_only_and_partial_time_arguments_are_no_longer_accepted(self):
        args = dict(challenge=self.challenge, proof_digest='b' * 64, verification_receipt='inert')
        for extra in ({}, {'verified_at': 1000}, {'verification_expires_at': 1001}):
            with self.subTest(extra=extra), self.assertRaises(TypeError):
                self.store.accept_attestation(**args, **extra)
        self.unadmitted()

    def test_expiry_during_insert_rolls_back_device_and_challenge(self):
        self.trigger('AFTER INSERT ON identity_devices', lambda: setattr(self, 'now', 1001))
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.unadmitted()

    def test_expiry_during_challenge_consumption_rolls_back_both_writes(self):
        self.trigger("AFTER UPDATE ON identity_challenges WHEN NEW.state='consumed'",
                     lambda: setattr(self, 'now', 1001))
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.unadmitted()

    def test_second_connection_cannot_see_tentative_expired_device(self):
        other = self.open()
        observed = []
        def observe():
            observed.append((other.db.execute('SELECT COUNT(*) FROM identity_devices').fetchone()[0],
                             other.db.execute('SELECT state FROM identity_challenges').fetchone()[0]))
            self.now = 1001
        self.trigger("AFTER UPDATE ON identity_challenges WHEN NEW.state='consumed'", observe)
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.assertEqual(observed, [(0, 'issued')])
        self.unadmitted()

    def test_age_limit_is_rechecked_after_local_writes(self):
        self.broker.changes.update(verified_at=880, expires_at=1120)
        self.trigger('AFTER INSERT ON identity_devices', lambda: setattr(self, 'now', 1001))
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.unadmitted()

    def test_clock_rollback_during_transaction_is_not_admitted(self):
        self.broker.changes.update(verified_at=900, expires_at=1120)
        self.trigger('AFTER INSERT ON identity_devices', lambda: setattr(self, 'now', 999))
        self.error('identity_attestation_clock_rollback', self.enroll)
        self.unadmitted()

    def test_invalid_clock_at_final_check_rolls_back(self):
        self.trigger('AFTER INSERT ON identity_devices', lambda: setattr(self, 'now', True))
        self.error('identity_clock_invalid', self.enroll)
        self.unadmitted()

    def test_existing_device_reenrollment_does_not_consume_expired_verdict(self):
        self.enroll()
        old_device = tuple(self.store.db.execute('SELECT * FROM identity_devices').fetchone())
        self.challenge = self.new_challenge()
        self.trigger("AFTER UPDATE ON identity_challenges WHEN NEW.state='consumed'",
                     lambda: setattr(self, 'now', 1001))
        self.error('identity_attestation_freshness_invalid', self.enroll)
        self.assertEqual(tuple(self.store.db.execute('SELECT * FROM identity_devices').fetchone()), old_device)
        digest = hashlib.sha256(self.challenge.nonce.encode()).hexdigest()
        self.assertEqual(self.store.db.execute('SELECT state FROM identity_challenges WHERE digest=?',
                                               (digest,)).fetchone()[0], 'issued')

    def test_lock_wait_uses_new_time_without_consuming_challenge(self):
        other = self.open()
        entered = threading.Event()
        failures = []
        original = self.store.accept_attestation
        def call_store(**kwargs):
            entered.set()
            return original(**kwargs)
        def worker():
            try:
                self.enroll()
            except BaseException as error:
                failures.append(error)
        with patch.object(self.store, 'accept_attestation', side_effect=call_store):
            with other._storage.transaction():
                thread = threading.Thread(target=worker)
                thread.start()
                self.assertTrue(entered.wait(2))
                self.now = 1002
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual([str(error) for error in failures], ['identity_attestation_freshness_invalid'])
        self.unadmitted()

    def test_original_verdict_not_renewed_by_mutating_broker_dictionary(self):
        def mutable_clock():
            self.broker.verdict['expires_at'] = 1120
            return 1000
        with patch.object(self.store, '_clock', side_effect=mutable_clock), patch.object(
                self.store, 'accept_attestation', wraps=self.store.accept_attestation) as accept:
            self.enroll()
        self.assertEqual(accept.call_args.kwargs['verification_expires_at'], 1001)
        self.assertEqual(accept.call_args.kwargs['verified_at'], 1000)

    def test_new_genuine_fixture_verdict_can_succeed_after_rejected_attempt(self):
        self.now = 1001
        self.error('identity_attestation_freshness_invalid', self.direct)
        self.unadmitted()
        self.broker.changes.update(verified_at=1001, expires_at=1010)
        self.assertEqual(self.enroll()['state'], 'active')

    def test_broker_binding_and_verified_boolean_are_still_required(self):
        for change in ({'subject': 'other'}, {'proof_sha256': 'c' * 64}, {'verified': 1}):
            self.broker.changes = change
            self.error('identity_attestation_verdict_invalid', self.enroll)
        self.unadmitted()

    def test_cross_connection_revocation_still_wins_before_final_enrollment(self):
        other = self.open()
        original = self.store.accept_attestation
        def deny(**kwargs):
            other.revoke('device', 'device')
            return original(**kwargs)
        with patch.object(self.store, 'accept_attestation', side_effect=deny):
            with self.assertRaises(DurableIdentityError):
                self.enroll()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM identity_devices').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM identity_revocations').fetchone()[0], 1)

    def test_sqlite_write_failure_remains_unadmitted_and_releases_lock(self):
        self.store.db.execute("CREATE TRIGGER fail_consume BEFORE UPDATE ON identity_challenges "
                              "BEGIN SELECT RAISE(ABORT,'inert-fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.enroll()
        self.unadmitted()
        with self.open()._storage.transaction():
            pass

    def test_reopen_preserves_rejection_and_success_without_schema_migration(self):
        before = self.store.db.execute("SELECT version FROM hepta_component_schema WHERE component='identity'").fetchone()[0]
        with patch.object(self.store, '_clock', side_effect=[1000, 1002]):
            self.error('identity_attestation_freshness_invalid', self.enroll)
        self.store = self.open()
        self.unadmitted()
        self.assertEqual(self.direct()['state'], 'active')
        self.assertEqual(self.open().db.execute('SELECT COUNT(*) FROM identity_devices').fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT version FROM hepta_component_schema WHERE component='identity'").fetchone()[0], before)

    def test_no_raw_proof_nonce_receipt_or_broker_payload_is_persisted(self):
        self.enroll()
        for file in Path(self.tmp.name).glob('identity.sqlite*'):
            raw = file.read_bytes()
            for marker in (self.proof, self.challenge.nonce.encode(), b'inert-verdict-receipt'):
                self.assertNotIn(marker, raw)

    def test_actual_process_exit_after_expired_check_retains_rollback(self):
        script = '''
import os,sys
from services.control_plane.durable_identity import DurableIdentityStore,DurableIdentityError
now=[1000]
s=DurableIdentityStore(sys.argv[1],issuer='fixture',allowed_scopes=['display'],clock=lambda:now[0])
s.admit_subject('subject')
c=s.challenge(subject='subject',device_id='device',platform='android',application_id='app',signer_digest='a'*64)
s.db.create_function('tick',0,lambda:(now.__setitem__(0,1001),0)[1])
s.db.execute("CREATE TRIGGER late AFTER INSERT ON identity_devices BEGIN SELECT tick(); END")
try:
 s.accept_attestation(challenge=c,proof_digest='b'*64,verification_receipt='inert',verified_at=1000,verification_expires_at=1001)
except DurableIdentityError as e:
 assert e.code=='identity_attestation_freshness_invalid'
 os._exit(43)
os._exit(44)
'''
        path = str(Path(self.tmp.name) / 'crash.sqlite')
        run = subprocess.run([sys.executable, '-c', script, path], capture_output=True, timeout=8)
        self.assertEqual(run.returncode, 43, run.stderr.decode())
        reopened = DurableIdentityStore(path, issuer='fixture', allowed_scopes=['display'], clock=lambda:1002)
        try:
            self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM identity_devices').fetchone()[0], 0)
            self.assertEqual(reopened.db.execute('SELECT state FROM identity_challenges').fetchone()[0], 'issued')
        finally:
            reopened.close()


if __name__ == '__main__':
    unittest.main()
