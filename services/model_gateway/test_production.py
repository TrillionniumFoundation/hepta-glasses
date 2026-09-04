import tempfile, unittest
from services.model_gateway.production import ModelExecutionError, ProductionModelGateway, ProviderResult
class Provider:
    def __init__(self): self.calls=0; self.reconciled=None; self.fail=False
    def generate(self,**kw):
        self.calls+=1
        if self.fail: raise TimeoutError()
        return ProviderResult("answer","req1","receipt1")
    def reconcile(self,**kw): return self.reconciled
    def revoke_session(self,**kw): pass
class Tests(unittest.TestCase):
    def setUp(self): self.t=tempfile.TemporaryDirectory(); self.p=Provider(); self.g=ProductionModelGateway(self.t.name+"/m.db",provider=self.p,daily_request_limit=2)
    def tearDown(self): self.g.close(); self.t.cleanup()
    def test_success_persists_metadata_only(self):
        answer,r=self.g.execute(subject="u",session_id="s",idempotency_key="k",question="hello",context={},now=1)
        self.assertEqual(answer,"answer"); self.assertEqual(r.state,"committed"); self.assertEqual(self.p.calls,1)
        columns=self.g.db.execute("PRAGMA table_info(requests)").fetchall(); self.assertNotIn("question",{x[1] for x in columns}); self.assertNotIn("answer",{x[1] for x in columns})
    def test_post_dispatch_failure_never_replays(self):
        self.p.fail=True
        with self.assertRaisesRegex(ModelExecutionError,"indeterminate"): self.g.execute(subject="u",session_id="s",idempotency_key="k",question="hello",context={},now=1)
        self.p.fail=False; self.p.reconciled=ProviderResult("recovered","req1","receipt1")
        answer,_=self.g.execute(subject="u",session_id="s",idempotency_key="k",question="hello",context={},now=2)
        self.assertEqual(answer,"recovered"); self.assertEqual(self.p.calls,1)
    def test_argument_drift_and_quota(self):
        self.g.execute(subject="u",session_id="s",idempotency_key="k1",question="a",context={},now=1)
        with self.assertRaisesRegex(ModelExecutionError,"conflict"): self.g.execute(subject="u",session_id="s",idempotency_key="k1",question="b",context={},now=1)
        self.g.execute(subject="u",session_id="s",idempotency_key="k2",question="a",context={},now=1)
        with self.assertRaisesRegex(ModelExecutionError,"quota"): self.g.execute(subject="u",session_id="s",idempotency_key="k3",question="a",context={},now=1)
if __name__=="__main__": unittest.main()
