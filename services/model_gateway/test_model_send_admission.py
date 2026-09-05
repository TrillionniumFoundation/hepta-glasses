"""Real SQLite and production transport composition; no live credentials/network."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.model_gateway.production import ProductionModelGateway, ModelExecutionError, canonical
from services.model_gateway.responses_provider import ResponsesProvider
from services.model_gateway.test_responses_provider import Connection, Response, document


class MutableProvider:
    """Host adapter with mutable configuration to probe accidental drift."""
    def __init__(self, delegate):
        self.binding_id = delegate.binding_id
        self.delegate = delegate

    def generate(self, **kwargs):
        raise AssertionError('checked path must be selected')

    def generate_authorized(self, **kwargs):
        return self.delegate.generate_authorized(**kwargs)

    def reconcile(self, **kwargs):
        return self.delegate.reconcile(**kwargs)


class ModelSendAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'model.db')
        self.now = 1000
        self.credential_hook = lambda: None
        self.credential_calls = 0
        self.token = os.urandom(24).hex()
        self.transport = ResponsesProvider('fixture-model-2026-09-01', 'fixture-project', self.credential)
        self.provider = MutableProvider(self.transport)
        self.gateway = self.open()
        self.conn = Connection(Response(canonical(document())))

    def credential(self):
        self.credential_calls += 1
        self.credential_hook()
        return self.token

    def open(self):
        gateway = ProductionModelGateway(self.path, provider=self.provider,
            provider_binding=self.transport.binding_id, clock=lambda: self.now)
        self.addCleanup(gateway.close)
        return gateway

    def execute(self, **changes):
        args = dict(subject='user', session_id='session', idempotency_key='key',
            question='inert prompt must not be sent after denial', context={'private':'inert-context'},
            expires_at=1100, timeout_seconds=1)
        args.update(changes)
        with patch('services.model_gateway.responses_provider.http.client.HTTPSConnection', return_value=self.conn):
            return self.gateway.execute(**args)

    def deny_request(self):
        self.open().cancel(subject='user', idempotency_key='key')

    def deny_session(self):
        self.open().revoke_session('session', subject='user')

    def check_blocked(self, state='cancelled'):
        with self.assertRaises(ModelExecutionError): self.execute()
        self.assertEqual(self.conn.requests, [])
        self.assertTrue(self.conn.closed)
        self.assertEqual(self.gateway.status(subject='user', idempotency_key='key').state, state)

    def test_success_uses_checked_transport_and_sends_once(self):
        answer, receipt = self.execute()
        self.assertEqual((answer, receipt.state), ('inert answer', 'committed'))
        self.assertEqual(len(self.conn.requests), 1)
        self.assertEqual(self.credential_calls, 1)

    def test_cancel_during_credential_resolution_prevents_post(self):
        self.credential_hook = self.deny_request
        self.check_blocked()

    def test_session_revoke_during_credential_resolution_prevents_post(self):
        self.credential_hook = self.deny_session
        self.check_blocked()

    def test_expiry_during_credential_resolution_prevents_post(self):
        self.credential_hook = lambda: setattr(self, 'now', 1100)
        self.check_blocked('indeterminate')

    def test_cancel_during_tls_preparation_prevents_post(self):
        self.conn.connect = self.deny_request
        self.check_blocked()

    def test_session_revoke_during_tls_preparation_prevents_post(self):
        self.conn.connect = self.deny_session
        self.check_blocked()

    def test_expiry_during_tls_preparation_prevents_post(self):
        self.conn.connect = lambda: setattr(self, 'now', 1100)
        self.check_blocked('indeterminate')

    def test_bad_clock_during_tls_prevents_post_without_private_error(self):
        self.conn.connect = lambda: setattr(self, 'now', True)
        self.check_blocked('indeterminate')
        for p in Path(self.tmp.name).glob('model.db*'):
            self.assertNotIn(self.token.encode(), p.read_bytes())

    def test_final_authorization_transaction_expiry_prevents_post(self):
        def expire_at_exit():
            times = iter([1000, 1100])
            self.gateway.clock = lambda: next(times)
        self.conn.connect = expire_at_exit
        self.check_blocked('indeterminate')

    def test_replaced_claim_after_tls_is_not_authorization(self):
        def replace_claim():
            with self.open().storage.transaction() as db:
                db.execute("UPDATE requests SET claim='replacement'")
        self.conn.connect = replace_claim
        self.check_blocked('prepared')

    def test_global_suspension_during_preparation_prevents_post(self):
        def suspend():
            with self.open().storage.transaction() as db:
                db.execute('UPDATE model_policy SET suspended=1')
        self.credential_hook = suspend
        self.check_blocked('indeterminate')

    def test_original_caller_budget_is_not_refreshed_after_tls(self):
        ticks = [0.0]
        self.conn.connect = lambda: ticks.__setitem__(0, 2.0)
        with patch('services.model_gateway.production.time.monotonic', side_effect=lambda: ticks[0]):
            self.check_blocked('indeterminate')

    def test_real_cross_connection_revoke_while_tls_waits(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        self.addCleanup(release.set)
        def connect():
            entered.set()
            if not release.wait(3): raise TimeoutError('fixture')
        self.conn.connect = connect
        def request():
            try: self.execute(timeout_seconds=2)
            except BaseException as error: errors.append(error)
        thread = threading.Thread(target=request)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.deny_session()
        release.set()
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ModelExecutionError)
        self.assertEqual(self.conn.requests, [])
        self.assertTrue(self.conn.closed)

    def test_preexisting_denial_never_fetches_credential(self):
        self.deny_request()
        with self.assertRaises(ModelExecutionError): self.execute()
        self.assertEqual(self.credential_calls, 0)
        self.assertEqual(self.conn.requests, [])

    def test_already_sent_request_is_not_falsely_retracted(self):
        original = self.conn.request
        def sent(*args, **kwargs):
            original(*args, **kwargs)
            self.deny_request()
        self.conn.request = sent
        with self.assertRaises(ModelExecutionError): self.execute()
        self.assertEqual(len(self.conn.requests), 1)
        status = self.gateway.status(subject='user', idempotency_key='key')
        self.assertEqual(status.state, 'cancelled')
        self.assertFalse(status.remote_cancellation_confirmed)

    def test_denied_send_never_refunds_reservation_or_reposts(self):
        self.credential_hook = self.deny_request
        self.check_blocked()
        for _ in range(3):
            with self.assertRaises(ModelExecutionError): self.execute()
        self.assertEqual(len(self.conn.requests), 0)
        self.assertEqual(self.credential_calls, 1)
        self.assertEqual(self.gateway.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 1)

    def test_expired_send_remains_unknown_and_does_not_renew_request(self):
        self.credential_hook = lambda: setattr(self, 'now', 1100)
        self.check_blocked('indeterminate')
        with self.assertRaises(ModelExecutionError): self.execute(expires_at=1200)
        row = self.gateway.db.execute('SELECT expires_at FROM requests').fetchone()
        self.assertEqual(row[0], 1100)
        self.assertEqual(self.credential_calls, 1)
        self.assertEqual(self.conn.requests, [])

    def test_provider_configuration_is_readonly_at_public_api(self):
        for attr, value in [('provider', object()), ('provider_binding', 'another')]:
            with self.assertRaises(AttributeError): setattr(self.gateway, attr, value)

    def test_provider_binding_drift_prevents_reservation(self):
        self.provider.binding_id = 'changed'
        with self.assertRaisesRegex(ModelExecutionError, 'configuration_binding_mismatch'):
            self.execute()
        self.assertEqual(self.credential_calls, 0)
        self.assertEqual(self.gateway.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0], 0)

    def test_provider_binding_drift_during_tls_prevents_post(self):
        self.conn.connect = lambda: setattr(self.provider, 'binding_id', 'changed')
        self.check_blocked('indeterminate')

    def test_provider_binding_drift_after_post_cannot_commit_success(self):
        self.conn.response.on_read = lambda: setattr(self.provider, 'binding_id', 'changed')
        with self.assertRaisesRegex(ModelExecutionError, 'configuration_binding_mismatch'): self.execute()
        self.assertEqual(len(self.conn.requests), 1)
        self.assertEqual(self.gateway.status(subject='user', idempotency_key='key').state, 'indeterminate')

    def test_configuration_drift_at_final_write_rolls_back_success(self):
        original = self.gateway._event
        def drift(db, event, key, now):
            original(db, event, key, now)
            if event == 'committed': self.provider.binding_id = 'changed'
        with patch.object(self.gateway, '_event', side_effect=drift):
            with self.assertRaisesRegex(ModelExecutionError, 'configuration_binding_mismatch'): self.execute()
        self.assertEqual(self.gateway.status(subject='user', idempotency_key='key').state, 'indeterminate')
        self.assertEqual(self.gateway.db.execute("SELECT COUNT(*) FROM model_events WHERE event='committed'").fetchone()[0], 0)

    def test_malformed_authorized_hook_is_rejected_at_construction(self):
        self.provider.generate_authorized = False
        with self.assertRaisesRegex(ModelExecutionError, 'configuration_invalid'): self.open()

    def test_authorized_transport_requires_real_callable(self):
        for callback in (None, False, 'approve'):
            with self.assertRaisesRegex(ModelExecutionError, 'authorizer_required'):
                self.transport.generate_authorized(question='q', context={}, request_key='f'*64,
                    timeout_seconds=1, authorize=callback)
        self.assertEqual(self.credential_calls, 0)

    def test_failed_presend_db_check_closes_connection_and_keeps_unknown(self):
        original = self.gateway._authority
        calls = [0]
        def storage_fault(*args):
            calls[0] += 1
            if calls[0] == 3: raise sqlite3.OperationalError('private-fixture-storage-marker')
            return original(*args)
        with patch.object(self.gateway, '_authority', side_effect=storage_fault):
            self.check_blocked('indeterminate')
        for p in Path(self.tmp.name).glob('model.db*'):
            self.assertNotIn(b'private-fixture-storage-marker', p.read_bytes())

    def test_private_payload_never_enters_metadata_when_send_is_denied(self):
        self.conn.connect = self.deny_request
        self.check_blocked()
        for p in Path(self.tmp.name).glob('model.db*'):
            for marker in (self.token.encode(), b'inert prompt must not be sent', b'inert-context'):
                self.assertNotIn(marker, p.read_bytes())

    def test_reopen_retains_denial_and_v2_storage(self):
        self.conn.connect = self.deny_request
        self.check_blocked()
        reopened = self.open()
        self.assertEqual(reopened.status(subject='user', idempotency_key='key').state, 'cancelled')
        self.assertEqual(reopened.db.execute("SELECT version FROM hepta_component_schema WHERE component='model_gateway'").fetchone()[0], 2)


    def socket_transport(self, *, cancel=False):
        # Real HTTP serializer/parser over a local socketpair; deliberately not
        # a live TLS or provider test. No payload logging or external network.
        import http.client
        import socket
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        owner = self
        class LocalConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = client
                if cancel:
                    owner.deny_request()
                else:
                    body = canonical(document())
                    server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + b"Content-Length: " + str(len(body)).encode()
                        + b"\r\nx-request-id: req_fixture\r\nConnection: close\r\n\r\n" + body)
        self.conn = LocalConnection('fixture.invalid')
        server.settimeout(1)
        return server

    def test_real_http_emits_no_bytes_after_cancel_in_connect(self):
        server = self.socket_transport(cancel=True)
        with self.assertRaises(ModelExecutionError): self.execute()
        self.assertEqual(server.recv(131072), b'')
        self.assertEqual(self.gateway.status(subject='user', idempotency_key='key').state, 'cancelled')

    def test_real_http_success_emits_one_post_and_parses_answer(self):
        server = self.socket_transport()
        answer, receipt = self.execute()
        raw = server.recv(131072)
        self.assertTrue(raw.startswith(b'POST /v1/responses HTTP/1.1\r\n'))
        self.assertEqual(raw.count(b'POST /v1/responses'), 1)
        self.assertIn(b'inert prompt must not be sent', raw)
        self.assertEqual((answer, receipt.state), ('inert answer', 'committed'))


if __name__ == '__main__':
    unittest.main()
