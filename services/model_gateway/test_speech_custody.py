from __future__ import annotations
import tempfile, threading, unittest
from pathlib import Path
from unittest import mock
from services.model_gateway.speech import *

class Broker:
    binding_id='fixture'
    def __init__(self):
        self.enter=threading.Event(); self.release=threading.Event(); self.block=False
        self.revokes=[]; self.mints=0; self.ticket_expiry=None
    def mint_ticket(self,**kw):
        self.mints+=1; self.enter.set()
        if self.block: self.release.wait(2)
        exp=kw['expires_at'] if self.ticket_expiry is None else self.ticket_expiry
        return ProviderSpeechTicket('https://speech.example','secret-token','fixture','ticket-'+str(self.mints),exp,kw['maximum_audio_bytes'])
    def revoke_session(self,*,session_id,timeout_seconds): self.revokes.append(session_id)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.now=1000; self.b=Broker(); self.path=str(Path(self.tmp.name)/'s.db')
        self.g=ProductionSpeechGateway(self.path,broker=self.b,provider_binding='fixture',clock=lambda:self.now,daily_limit=2)
        self.addCleanup(self.g.close)
    def bootstrap(self,session='s'): return self.g.bootstrap(subject='u',session_id=session,generation=1,pair_identity='pair',locale='en-US')
    def error(self,code,fn):
        with self.assertRaises(SpeechGatewayError) as e: fn()
        self.assertEqual(e.exception.code,code)

    def test_revoke_race_never_issues_or_consumes_late_ticket(self):
        self.b.block=True; out=[]; errors=[]
        def run():
            try: out.append(self.bootstrap())
            except Exception as e: errors.append(e)
        t=threading.Thread(target=run); t.start(); self.assertTrue(self.b.enter.wait(1))
        self.g.revoke_session('s'); self.b.release.set(); t.join(2); self.assertFalse(t.is_alive())
        self.assertEqual(out,[]); self.assertEqual(errors[0].code,'speech_session_revoked')
        self.assertEqual(self.g.db.execute('select state from bootstraps').fetchone()[0],'revoked')
        self.assertEqual(self.b.revokes,['s','s'])

    def test_consume_rechecks_revocation(self):
        boot=self.bootstrap(); self.g.revoke_session('s')
        self.error('speech_session_revoked',lambda:self.g.consume(boot.bootstrap_id,session_id='s',generation=1,pair_identity='pair'))
        self.assertEqual(self.g.db.execute('select state from bootstraps').fetchone()[0],'revoked')

    def test_generated_bootstrap_id_is_always_in_identifier_domain(self):
        with mock.patch('services.model_gateway.speech.secrets.token_urlsafe',return_value='_leading-token'):
            boot=self.bootstrap()
        self.assertEqual(boot.bootstrap_id,'b-_leading-token')
        self.g.consume(boot.bootstrap_id,session_id='s',generation=1,pair_identity='pair')
        self.assertEqual(self.g.db.execute('select state from bootstraps').fetchone()[0],'consumed')

    def test_host_clock_controls_expiry_and_caller_now_is_removed(self):
        boot=self.bootstrap(); self.now=boot.expires_at
        self.error('speech_bootstrap_expired',lambda:self.g.consume(boot.bootstrap_id,session_id='s',generation=1,pair_identity='pair'))
        with self.assertRaises(TypeError): self.g.bootstrap(subject='u',session_id='x',generation=1,pair_identity='pair',locale='en',now=0)
        with self.assertRaises(TypeError): self.g.consume(boot.bootstrap_id,session_id='s',generation=1,pair_identity='pair',now=0)

    def test_invalid_clock_and_provider_ticket_fail_closed(self):
        self.now=True; self.error('speech_clock_invalid',lambda:self.bootstrap())
        self.now=1000; self.b.ticket_expiry=999
        self.error('speech_provider_ticket_invalid',lambda:self.bootstrap())
        self.assertEqual(self.g.pending_recovery(),('s',))

    def test_provider_binding_drift_rejected(self):
        self.b.binding_id='other'
        self.error('speech_provider_binding_mismatch',lambda:self.bootstrap())

    def test_concurrent_quota_reservation_is_atomic(self):
        self.b.block=True; results=[]
        def run(s):
            try: results.append(self.bootstrap(s))
            except SpeechGatewayError as e: results.append(e.code)
        ts=[threading.Thread(target=run,args=(f's{i}',)) for i in range(3)]
        for t in ts:t.start()
        self.assertTrue(self.b.enter.wait(1)); self.b.release.set()
        for t in ts:t.join(2)
        self.assertEqual(sum(isinstance(x,SpeechBootstrap) for x in results),2)
        self.assertEqual(results.count('speech_quota_exhausted'),1)
        self.assertEqual(self.g.db.execute('select count(*) from bootstraps').fetchone()[0],2)

    def test_indeterminate_mint_blocks_duplicate_and_is_recoverable(self):
        class F(Broker):
            def mint_ticket(self,**kw): raise TimeoutError('fixture')
        f=F(); g=ProductionSpeechGateway(str(Path(self.tmp.name)/'f.db'),broker=f,provider_binding='fixture',clock=lambda:1000)
        self.addCleanup(g.close)
        with self.assertRaises(TimeoutError): g.bootstrap(subject='u',session_id='s',generation=1,pair_identity='pair',locale='en')
        self.assertEqual(g.pending_recovery(),('s',))
        with self.assertRaises(SpeechGatewayError) as e:g.bootstrap(subject='u',session_id='s',generation=1,pair_identity='pair',locale='en')
        self.assertEqual(e.exception.code,'speech_bootstrap_recovery_required')
        self.assertEqual(f.mints,0)

if __name__=='__main__': unittest.main()
