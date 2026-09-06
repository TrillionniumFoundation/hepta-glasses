import tempfile, unittest
from services.control_plane.durable_realtime import DurableRealtimeError, DurableRealtimeStore, RealtimeActivation
class Provider:
    def __init__(self): self.calls=0; self.fail=False; self.reconciled=None
    def activate(self,**kw): self.calls+=1; (_ for _ in ()).throw(TimeoutError()) if self.fail else None; return RealtimeActivation("ps","pr")
    def reconcile_activation(self,**kw): return self.reconciled
    def revoke(self,**kw): self.revoked=kw["provider_session_id"]
class Tests(unittest.TestCase):
    def setUp(self): self.t=tempfile.TemporaryDirectory(); self.p=Provider(); self.s=DurableRealtimeStore(self.t.name+"/r.db", provider_binding='fixture-namespace',provider=self.p,clock=lambda:1)
    def tearDown(self): self.s.close(); self.t.cleanup()
    def test_ticket_single_use_and_generation(self):
        ticket=self.s.issue_ticket(subject="u",session_id="s"); row=self.s.activate(ticket=ticket,subject="u",session_id="s")
        with self.assertRaisesRegex(DurableRealtimeError,"replayed"): self.s.activate(ticket=ticket,subject="u",session_id="s")
        row=self.s.interrupt("s",generation=row["generation"]); self.assertEqual(row["generation"],2)
        with self.assertRaisesRegex(DurableRealtimeError,"stale"): self.s.require_generation("s",1)
    def test_indeterminate_reconciles_without_second_activation(self):
        ticket=self.s.issue_ticket(subject="u",session_id="s"); self.p.fail=True
        with self.assertRaisesRegex(DurableRealtimeError,"indeterminate"): self.s.activate(ticket=ticket,subject="u",session_id="s")
        self.p.fail=False; self.p.reconciled=RealtimeActivation("ps","pr"); row=self.s.reconcile("s")
        self.assertEqual(row["state"],"active"); self.assertEqual(self.p.calls,1)
if __name__=="__main__": unittest.main()
