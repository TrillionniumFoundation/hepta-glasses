"""Local fixture only: execute actual unmodified baseline repository code."""
import json, tempfile
from services.control_plane.durable_realtime import DurableRealtimeStore, RealtimeActivation
class Provider:
    def __init__(self, binding): self.binding_id=binding; self.revoked=[]
    def activate(self, **kw): return RealtimeActivation('same-remote-id', 'same-receipt')
    def reconcile_activation(self, **kw): return RealtimeActivation('same-remote-id', 'same-receipt')
    def revoke(self, *, provider_session_id, timeout_seconds): self.revoked.append(provider_session_id)
result={}
with tempfile.TemporaryDirectory() as tmp:
    a,b=Provider('tenant-a'),Provider('tenant-b')
    s=DurableRealtimeStore(tmp+'/a.db',provider=a,clock=lambda:1000)
    t=s.issue_ticket(subject='subject-a',session_id='local-a');s.activate(ticket=t,subject='subject-a',session_id='local-a');s.close()
    s=DurableRealtimeStore(tmp+'/a.db',provider=b,clock=lambda:1000);s.revoke('local-a')
    result['reopen_wrong_tenant']={'original_provider':a.binding_id,'reopened_provider':b.binding_id,'wrong_provider_revoke_calls':b.revoked,'pending_after_wrong_cleanup':s.pending_recovery()};s.close()
with tempfile.TemporaryDirectory() as tmp:
    p=Provider('tenant-a');s=DurableRealtimeStore(tmp+'/b.db',provider=p,clock=lambda:1000)
    states={}
    for name in ['a','b']:
        t=s.issue_ticket(subject='subject-'+name,session_id=name)
        states[name]=s.activate(ticket=t,subject='subject-'+name,session_id=name)['state']
    s.revoke('a');result['duplicate_remote_owner']={'initial_states':states,'remote_revoke_calls':p.revoked,'other_local_session_still_authorized':s.require_generation('b',1)['state']};s.close()
print(json.dumps(result,indent=2))
