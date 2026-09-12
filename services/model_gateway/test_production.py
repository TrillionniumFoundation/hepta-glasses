"""Regression of the existing execution contract, with explicit v2 host inputs."""
import tempfile
import unittest

from services.model_gateway.production import ModelExecutionError, ProductionModelGateway, ProviderResult


class Provider:
    def __init__(self):
        self.calls = 0
        self.reconciled = False
        self.fail = False

    def generate(self, **kw):
        self.calls += 1
        if self.fail:
            raise TimeoutError()
        return ProviderResult("answer", "req1", "receipt1", kw["request_key"])

    def reconcile(self, **kw):
        return ProviderResult("recovered", "req1", "receipt1", kw["request_key"]) if self.reconciled else None


class Tests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.p = Provider()
        self.g = ProductionModelGateway(self.t.name + "/m.db", provider=self.p,
            provider_binding="fixture", clock=lambda: 1, daily_request_limit=2)

    def tearDown(self):
        self.g.close()
        self.t.cleanup()

    def execute(self, **kwargs):
        args = dict(subject="u", session_id="s", idempotency_key="k", question="hello", context={}, expires_at=100)
        args.update(kwargs)
        return self.g.execute(**args)

    def test_success_persists_metadata_only(self):
        answer, receipt = self.execute()
        self.assertEqual(answer, "answer")
        self.assertEqual(receipt.state, "committed")
        self.assertEqual(self.p.calls, 1)
        columns = {x[1] for x in self.g.db.execute("PRAGMA table_info(requests)")}
        self.assertNotIn("question", columns)
        self.assertNotIn("answer", columns)

    def test_post_dispatch_failure_never_replays(self):
        self.p.fail = True
        with self.assertRaisesRegex(ModelExecutionError, "indeterminate"):
            self.execute()
        self.p.fail = False
        self.p.reconciled = True
        answer, _ = self.execute()
        self.assertEqual(answer, "recovered")
        self.assertEqual(self.p.calls, 1)

    def test_argument_drift_and_quota(self):
        self.execute(idempotency_key="k1", question="a")
        with self.assertRaisesRegex(ModelExecutionError, "conflict"):
            self.execute(idempotency_key="k1", question="b")
        self.execute(idempotency_key="k2", question="a")
        with self.assertRaisesRegex(ModelExecutionError, "quota"):
            self.execute(idempotency_key="k3", question="a")


if __name__ == "__main__":
    unittest.main()
