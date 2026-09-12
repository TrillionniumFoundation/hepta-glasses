from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.qualification.model_capacity import CapacityObservationError, read_snapshot

# Schema fixture copied from model_gateway/production.py and durable_state.py.
# Real SQLite is used; this is not a live tenant, gateway admission or provider test.
SCHEMA = (
    "CREATE TABLE hepta_component_schema(component TEXT PRIMARY KEY,version INTEGER NOT NULL)",
    "CREATE TABLE model_policy(id INTEGER PRIMARY KEY,policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
    "CREATE TABLE requests(subject TEXT,idempotency_key TEXT,fingerprint TEXT,session_id TEXT,day INTEGER,state TEXT,expires_at INTEGER,request_key TEXT,claim TEXT,claim_until INTEGER,readbacks INTEGER,answer_digest TEXT,provider_request_id TEXT,provider_receipt_id TEXT)",
    "CREATE TABLE revoked_sessions(subject TEXT,session_id TEXT)",
    "CREATE TABLE model_cancellations(subject TEXT,idempotency_key TEXT)",
    "CREATE TABLE model_events(sequence INTEGER PRIMARY KEY,event TEXT,request_key TEXT,observed_at INTEGER)",
)


class ModelCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'model.db'
        self.db = sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute('PRAGMA journal_mode=WAL')
        for statement in SCHEMA:
            self.db.execute(statement)
        self.db.execute("INSERT INTO hepta_component_schema VALUES('model_gateway',2)")
        self.policy = dict(provider='fixture-provider',daily_requests=1000,question_chars=8000,entries=100,readbacks=3,workers=4)
        self.db.execute('INSERT INTO model_policy VALUES(1,?,100,0)',(json.dumps(self.policy).encode(),))

    def add(self,count: int,state: str='committed',readbacks: int=0) -> None:
        self.db.executemany('INSERT INTO requests(subject,idempotency_key,state,readbacks) VALUES(?,?,?,?)',
                            [('private-subject','private-key-'+str(i),state,readbacks) for i in range(count)])

    def test_empty_valid_database_has_no_authority(self) -> None:
        result=read_snapshot(self.path)
        self.assertEqual(result['requests']['used'],0)
        self.assertFalse(result['operator_attention_required'])
        self.assertFalse(result['admission_authority'])
        self.assertFalse(result['release_authority'])

    def test_warning_critical_and_exhaustion_thresholds(self) -> None:
        for target,level in ((79,'normal'),(80,'warning'),(95,'critical'),(100,'exhausted'),(101,'exhausted')):
            with self.subTest(target=target):
                current=self.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
                self.add(target-current)
                report=read_snapshot(self.path)
                self.assertEqual(report['requests']['level'],level)
                self.assertEqual(report['requests']['remaining'],max(0,100-target))

    def test_denial_budget_combines_both_tombstone_tables(self) -> None:
        self.db.executemany('INSERT INTO revoked_sessions VALUES(?,?)',[('s',str(i)) for i in range(40)])
        self.db.executemany('INSERT INTO model_cancellations VALUES(?,?)',[('s',str(i)) for i in range(40)])
        self.assertEqual(read_snapshot(self.path)['denials']['level'],'warning')

    def test_unresolved_exhaustion_is_not_remote_cancellation(self) -> None:
        self.add(2,'prepared',3);self.add(1,'indeterminate',3);self.add(1,'committed',3)
        report=read_snapshot(self.path)
        self.assertEqual(report['unresolved_readback_exhausted'],3)
        self.assertTrue(report['operator_attention_required'])
        self.assertNotIn('remote_cancellation_confirmed',report)

    def test_snapshot_never_contains_identity_or_provider_values(self) -> None:
        self.add(2)
        raw=json.dumps(read_snapshot(self.path))
        for forbidden in ('private-subject','private-key','fixture-provider','model.db'):
            self.assertNotIn(forbidden,raw)

    def test_observation_does_not_change_rows_or_policy(self) -> None:
        self.add(2,'indeterminate',2)
        before='\n'.join(self.db.iterdump())
        read_snapshot(self.path)
        self.assertEqual('\n'.join(self.db.iterdump()),before)

    def test_uncommitted_concurrent_writer_is_not_reported(self) -> None:
        self.add(1)
        self.db.execute('BEGIN IMMEDIATE');self.add(1)
        try:
            self.assertEqual(read_snapshot(self.path)['requests']['used'],1)
        finally:
            self.db.rollback()

    def test_missing_file_is_not_created(self) -> None:
        missing=Path(self.directory.name)/'missing.db'
        with self.assertRaises(CapacityObservationError):read_snapshot(missing)
        self.assertFalse(missing.exists())

    def test_missing_authority_table_is_not_empty_capacity(self) -> None:
        self.db.execute('DROP TABLE revoked_sessions')
        with self.assertRaisesRegex(CapacityObservationError,'schema_invalid'):read_snapshot(self.path)

    def test_wrong_schema_version_fails(self) -> None:
        self.db.execute('UPDATE hepta_component_schema SET version=3')
        with self.assertRaisesRegex(CapacityObservationError,'schema_invalid'):read_snapshot(self.path)

    def test_missing_policy_fails(self) -> None:
        self.db.execute('DELETE FROM model_policy')
        with self.assertRaisesRegex(CapacityObservationError,'policy_invalid'):read_snapshot(self.path)

    def test_policy_duplicates_and_noninteger_limit_fail(self) -> None:
        for raw in (b'{"entries":100,"entries":200}',json.dumps({**self.policy,'entries':True}).encode()):
            self.db.execute('UPDATE model_policy SET policy=?',(raw,))
            with self.assertRaises(CapacityObservationError):read_snapshot(self.path)

    def test_suspension_is_reported_without_reset(self) -> None:
        self.db.execute('UPDATE model_policy SET suspended=1')
        self.assertTrue(read_snapshot(self.path)['suspended'])
        self.assertEqual(self.db.execute('SELECT suspended FROM model_policy').fetchone()[0],1)

    def test_invalid_state_and_readback_fail(self) -> None:
        self.add(1,'unrecognized',0)
        with self.assertRaisesRegex(CapacityObservationError,'state_invalid'):read_snapshot(self.path)
        self.db.execute("UPDATE requests SET state='prepared',readbacks=4")
        with self.assertRaisesRegex(CapacityObservationError,'state_invalid'):read_snapshot(self.path)

    def test_linked_path_and_invalid_budgets_fail(self) -> None:
        link=Path(self.directory.name)/'alias.db';link.symlink_to(self.path)
        with self.assertRaises(CapacityObservationError):read_snapshot(link)
        for budget in (0,-1,True,6,float('nan'),float('inf')):
            with self.subTest(budget=budget),self.assertRaises(CapacityObservationError):
                read_snapshot(self.path,timeout_seconds=budget)

    def test_budget_expiry_is_not_success(self) -> None:
        with patch('services.qualification.model_capacity.time.monotonic',side_effect=[0.0]+[10.0]*100):
            with self.assertRaises(CapacityObservationError):read_snapshot(self.path)

    def test_cli_failure_does_not_echo_private_path(self) -> None:
        root=Path(__file__).resolve().parents[2]
        result=subprocess.run([sys.executable,'-m','services.qualification.model_capacity','--database',
                               str(Path(self.directory.name)/'private-operator-value.db')],
                              cwd=root,text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,1)
        self.assertNotIn('private-operator-value',result.stderr+result.stdout)
        self.assertFalse(json.loads(result.stderr)['release_authority'])


class ModelCapacitySourceIntegrationTests(unittest.TestCase):
    def test_observer_reads_the_real_gateway_schema_without_provider_work(self) -> None:
        # Full-repository CI additionally checks the real constructor, not only
        # the local schema fixture used by the isolated regression tests.
        from services.model_gateway.production import ProductionModelGateway

        class InertProvider:
            def generate(self, **kwargs):
                raise AssertionError("capacity observation must not generate")

            def reconcile(self, **kwargs):
                raise AssertionError("capacity observation must not reconcile")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source-model.db'
            gateway = ProductionModelGateway(
                str(path), provider=InertProvider(), provider_binding='capacity-test',
                clock=lambda: 100, maximum_entries=100,
            )
            try:
                result = read_snapshot(path)
                self.assertEqual(result['requests']['limit'],100)
                self.assertEqual(result['requests']['used'],0)
                self.assertFalse(result['admission_authority'])
            finally:
                gateway.storage.close()


if __name__ == '__main__':
    unittest.main()
