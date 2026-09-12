"""Real-SQLite operational regressions; no live provider or production keys."""
from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.qualification.model_capacity import CapacityObservationError, read_snapshot

SCHEMA = (
    "CREATE TABLE hepta_component_schema(component TEXT PRIMARY KEY,version INTEGER NOT NULL)",
    "CREATE TABLE model_policy(id INTEGER PRIMARY KEY,policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
    "CREATE TABLE requests(subject TEXT,idempotency_key TEXT,fingerprint TEXT,session_id TEXT,day INTEGER,state TEXT,expires_at INTEGER,request_key TEXT,claim TEXT,claim_until INTEGER,readbacks INTEGER,answer_digest TEXT,provider_request_id TEXT,provider_receipt_id TEXT)",
    "CREATE TABLE revoked_sessions(subject TEXT,session_id TEXT)",
    "CREATE TABLE model_cancellations(subject TEXT,idempotency_key TEXT)",
    "CREATE TABLE model_events(sequence INTEGER PRIMARY KEY,event TEXT,request_key TEXT,observed_at INTEGER)",
)


class SQLiteFixture:

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'private-database.db'
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        for sql in SCHEMA:
            self.db.execute(sql)
        self.policy = dict(provider='private-provider', daily_requests=1000,
                           question_chars=8000, entries=100, readbacks=3, workers=4)
        self.raw = json.dumps(self.policy).encode('utf-8')
        self.db.execute("INSERT INTO hepta_component_schema VALUES('model_gateway',2)")
        self.db.execute('INSERT INTO model_policy VALUES(1,?,100,0)', (self.raw,))

class StorageTypeTests(SQLiteFixture, unittest.TestCase):
    def test_non_utf8_policy_is_not_healthy_capacity(self):
        for encoding in ('utf-16', 'utf-32', 'utf-8-sig'):
            with self.subTest(encoding=encoding):
                self.db.execute('UPDATE model_policy SET policy=?',
                                (json.dumps(self.policy).encode(encoding),))
                with self.assertRaises(CapacityObservationError):
                    read_snapshot(self.path)

    def test_real_version_is_not_integer_version(self):
        self.db.execute('DROP TABLE hepta_component_schema')
        self.db.execute('CREATE TABLE hepta_component_schema(component TEXT,version REAL)')
        self.db.execute("INSERT INTO hepta_component_schema VALUES('model_gateway',2.0)")
        with self.assertRaisesRegex(CapacityObservationError, 'schema_invalid'):
            read_snapshot(self.path)

    def test_real_suspension_is_not_valid_control_state(self):
        self.db.execute('DROP TABLE model_policy')
        self.db.execute('CREATE TABLE model_policy(id INTEGER,policy BLOB,last_time INTEGER,suspended REAL)')
        self.db.execute('INSERT INTO model_policy VALUES(1,?,100,0.0)', (self.raw,))
        with self.assertRaisesRegex(CapacityObservationError, 'policy_invalid'):
            read_snapshot(self.path)

    def test_real_singleton_id_is_not_valid_control_state(self):
        self.db.execute('DROP TABLE model_policy')
        self.db.execute('CREATE TABLE model_policy(id REAL,policy BLOB,last_time INTEGER,suspended INTEGER)')
        self.db.execute('INSERT INTO model_policy VALUES(1.0,?,100,0)', (self.raw,))
        with self.assertRaisesRegex(CapacityObservationError, 'policy_invalid'):
            read_snapshot(self.path)

    def test_valid_integer_storage_remains_read_only(self):
        before = '\n'.join(self.db.iterdump())
        result = read_snapshot(self.path)
        self.assertFalse(result['operator_attention_required'])
        self.assertEqual('\n'.join(self.db.iterdump()), before)


class MetricTests(SQLiteFixture, unittest.TestCase):
    def invoke(self, path=None):
        from services.qualification.model_metrics import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(['--database', str(self.path if path is None else path)])
        return status, out.getvalue(), err.getvalue()

    def test_module_cli_observes_existing_database(self):
        result = subprocess.run(
            [sys.executable, '-m', 'services.qualification.model_metrics',
             '--database', str(self.path)],
            cwd=Path(__file__).resolve().parents[2],
            text=True, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('hepta_model_observation_success 1\n', result.stdout)
        self.assertIn('hepta_model_requests_used 0\n', result.stdout)

    def test_normal_metrics_are_fixed_unique_integer_gauges(self):
        status, text, error = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(error, '')
        lines = text.splitlines()
        self.assertEqual(len(lines), 34)
        names = []
        for declaration, sample in zip(lines[::2], lines[1::2]):
            name, value = sample.split()
            names.append(name)
            self.assertEqual(declaration, f'# TYPE {name} gauge')
            self.assertGreaterEqual(int(value), 0)
        self.assertEqual(len(set(names)), 17)
        for private in ('private-provider', 'private-database', str(self.path.parent)):
            self.assertNotIn(private, text)

    def test_attention_is_successful_observation_not_release_permission(self):
        self.db.execute('UPDATE model_policy SET suspended=1')
        status, text, error = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn('hepta_model_observation_success 1\n', text)
        self.assertIn('hepta_model_suspended 1\n', text)
        self.assertIn('hepta_model_operator_attention_required 1\n', text)
        self.assertEqual(error, '')

    def test_missing_database_only_emits_failure_not_healthy_zeroes(self):
        path = self.path.parent / 'missing-private-file.db'
        status, text, error = self.invoke(path)
        self.assertEqual(status, 1)
        self.assertEqual(text, '# TYPE hepta_model_observation_success gauge\nhepta_model_observation_success 0\n')
        self.assertNotIn('missing-private-file', text + error)
        self.assertFalse(json.loads(error)['release_authority'])
        self.assertFalse(path.exists())

    def test_argument_errors_are_not_attention_and_do_not_echo_values(self):
        from services.qualification.model_metrics import main
        for args in ([], ['--database', str(self.path), '--timeout-seconds', 'private-value'],
                     ['--database', str(self.path), '--private-invalid-argument']):
            with self.subTest(args_count=len(args)):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    status = main(args)
                self.assertEqual(status, 1)
                self.assertEqual(out.getvalue(), '# TYPE hepta_model_observation_success gauge\nhepta_model_observation_success 0\n')
                self.assertEqual(json.loads(err.getvalue())['code'], 'model_metrics_arguments_invalid')
                self.assertNotIn('private-', err.getvalue())

    def test_malformed_schema_has_no_capacity_samples(self):
        self.db.execute('DROP TABLE model_cancellations')
        status, text, error = self.invoke()
        self.assertEqual(status, 1)
        self.assertNotIn('hepta_model_requests_', text)
        self.assertIn('schema_invalid', error)

    def test_collection_reads_one_snapshot_without_modifying_storage(self):
        from services.qualification import model_metrics
        before = '\n'.join(self.db.iterdump())
        with patch.object(model_metrics, 'read_snapshot', wraps=read_snapshot) as observer:
            model_metrics.collect(self.path)
            observer.assert_called_once_with(self.path, timeout_seconds=2.0)
        self.assertEqual('\n'.join(self.db.iterdump()), before)

    def test_warning_and_exhausted_readback_are_visible(self):
        self.db.executemany(
            "INSERT INTO requests(state,readbacks) VALUES('indeterminate',3)",
            [()] * 80,
        )
        status, text, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn('hepta_model_requests_utilization_basis_points 8000\n', text)
        self.assertIn('hepta_model_unresolved_readback_exhausted 80\n', text)

    def test_independent_uncommitted_writer_is_not_exported(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("INSERT INTO requests(state,readbacks) VALUES('prepared',0)")
            _, text, _ = self.invoke()
            self.assertIn('hepta_model_requests_used 0\n', text)
        finally:
            self.db.rollback()


if __name__ == '__main__':
    unittest.main()
