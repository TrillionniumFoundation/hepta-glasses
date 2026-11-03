"""Use the real baseline implementation, then the candidate, without network."""
from pathlib import Path
import json, os, sqlite3, subprocess, sys, tempfile
from contextlib import closing
from services.control_plane.realtime_provider_binding import migrate_realtime_v3
from services.control_plane.durable_realtime import DurableRealtimeStore
base=Path(__file__).resolve().parents[1]/'baseline'
old_script='''
import sys
from services.control_plane.durable_realtime import DurableRealtimeStore,DurableRealtimeError,RealtimeActivation
class P:
 def activate(self,**kw):
  if kw['session_id']=='unresolved':raise TimeoutError('fixture')
  return RealtimeActivation('remote-active','receipt-active')
 def reconcile_activation(self,**kw):return None
 def revoke(self,**kw):raise TimeoutError('fixture')
s=DurableRealtimeStore(sys.argv[1],provider=P(),clock=lambda:1000)
for sid in ['unresolved','active']:
 t=s.issue_ticket(subject='fixture-user',session_id=sid)
 try:s.activate(ticket=t,subject='fixture-user',session_id=sid)
 except DurableRealtimeError:pass
try:s.reconcile('unresolved')
except DurableRealtimeError:pass
try:s.revoke('active')
except DurableRealtimeError:pass
s.close()
'''
old_open='''
import sys
from services.control_plane.durable_realtime import DurableRealtimeStore
try:DurableRealtimeStore(sys.argv[1],provider=object(),clock=lambda:1000)
except ValueError as e:
 assert str(e)=='realtime_schema_migration_required'
 print(str(e))
else:raise AssertionError('old code accepted migrated v4')
'''
def snapshot(path):
 with closing(sqlite3.connect(path)) as db:
  names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('hepta_component_schema','sqlite_sequence')")]
  return {n:db.execute('SELECT * FROM '+n).fetchall() for n in names}
with tempfile.TemporaryDirectory() as tmp:
 path=tmp+'/actual-v3.sqlite'
 env=dict(os.environ,PYTHONPATH=str(base))
 create=subprocess.run([sys.executable,'-c',old_script,path],cwd=base,env=env,capture_output=True,text=True,timeout=10)
 assert create.returncode==0,create.stderr
 before=snapshot(path)
 report=migrate_realtime_v3(path,provider_binding='fixture-original-tenant')
 after=snapshot(path)
 assert all(before[n]==after[n] for n in before)
 old=subprocess.run([sys.executable,'-c',old_open,path],cwd=base,env=env,capture_output=True,text=True,timeout=10)
 assert old.returncode==0,old.stderr
 s=DurableRealtimeStore(path,provider=object(),provider_binding='fixture-original-tenant',clock=lambda:1000)
 state=s.recovery_status('unresolved')
 assert state['lookup']['used']==1
 s.close()
 print(json.dumps({'real_baseline_created_v3':True,'every_legacy_row_equal':True,
 'legacy_row_counts':{n:len(rows) for n,rows in before.items()},'old_constructor_error':old.stdout.strip(),
 'lookup_attempts_preserved':state['lookup']['used'],'migration':report},indent=2))
