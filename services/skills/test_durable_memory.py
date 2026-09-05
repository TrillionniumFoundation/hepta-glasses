import hashlib, hmac, tempfile, threading, unittest
from pathlib import Path
from services.skills.durable_memory import DurableMemoryConsent, DurableMemoryError, DurableMemoryStore

class Cipher:
    def __init__(self): self.keys={'u':{'k1':b'a'*32}}; self.current={'u':'k1'}
    def current_key_id(self,*,subject): return self.current[subject]
    def _stream(self,key,aad,n):
        out=b'';i=0
        while len(out)<n: out+=hashlib.sha256(key+aad+i.to_bytes(4,'big')).digest();i+=1
        return out[:n]
    def encrypt(self,*,subject,key_id,plaintext,aad):
        key=self.keys[subject][key_id]; stream=self._stream(key,aad,len(plaintext)); body=bytes(a^b for a,b in zip(plaintext,stream)); return hmac.new(key,aad+body,hashlib.sha256).digest()+body
    def decrypt(self,*,subject,key_id,ciphertext,aad):
        key=self.keys[subject][key_id]; tag,body=ciphertext[:32],ciphertext[32:]
        if not hmac.compare_digest(tag,hmac.new(key,aad+body,hashlib.sha256).digest()): raise ValueError('tag')
        stream=self._stream(key,aad,len(body)); return bytes(a^b for a,b in zip(body,stream))

class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.path=self.t.name+'/m.db';self.now=100;self.c=Cipher();self.s=self.open();self.s.grant_consent(DurableMemoryConsent('u','p',frozenset({'personal','sensitive'}),1000))
    def open(self):
        s=DurableMemoryStore(self.path,cipher=self.c,clock=lambda:self.now);self.addCleanup(s.close);return s
    def test_ciphertext_persists_without_plaintext_and_survives_restart(self):
        self.s.remember(subject='u',purpose='p',data_class='personal',value='PRIVATE-FIXTURE-STRING',ttl_seconds=50);self.s.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.assertNotIn(b'PRIVATE-FIXTURE-STRING',Path(self.path).read_bytes());self.assertEqual(self.open().export(subject='u')[0]['value'],'PRIVATE-FIXTURE-STRING')
    def test_ciphertext_is_bound_to_metadata_and_tamper_fails(self):
        r=self.s.remember(subject='u',purpose='p',data_class='personal',value='v',ttl_seconds=50);self.s.db.execute("UPDATE memory_records SET purpose='other' WHERE memory_id=?",(r.memory_id,))
        with self.assertRaisesRegex(DurableMemoryError,'decrypt_failed'):self.s.export(subject='u')
    def test_key_rotation_reencrypts_without_plaintext_loss(self):
        r=self.s.remember(subject='u',purpose='p',data_class='personal',value='rotate',ttl_seconds=50);self.c.keys['u']['k2']=b'b'*32;self.c.current['u']='k2';self.assertEqual(self.s.rotate_subject_key(subject='u'),1);self.assertEqual(self.open().export(subject='u')[0]['value'],'rotate');self.assertEqual(self.s.db.execute('SELECT key_id FROM memory_records WHERE memory_id=?',(r.memory_id,)).fetchone()[0],'k2')
    def test_missing_key_fails_closed_and_does_not_insert(self):
        self.c.current['u']='missing'
        with self.assertRaisesRegex(DurableMemoryError,'encrypt_failed'):self.s.remember(subject='u',purpose='p',data_class='personal',value='x',ttl_seconds=50)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM memory_records').fetchone()[0],0)
    def test_consent_narrowing_deletes_and_emits_tombstone(self):
        r=self.s.remember(subject='u',purpose='p',data_class='sensitive',value='x',ttl_seconds=50);self.s.grant_consent(DurableMemoryConsent('u','p',frozenset({'personal'}),1000));self.assertEqual(self.s.export(subject='u'),[]);page=self.s.pending_deletions();self.assertEqual(page[0]['memory_id'],r.memory_id);self.assertEqual(page[0]['reason'],'consent_narrowed')
    def test_deletion_inventory_is_restart_safe_and_paginated(self):
        for i in range(5):self.s.remember(subject='u',purpose='p',data_class='personal',value=str(i),ttl_seconds=50)
        self.assertEqual(self.s.delete_all(subject='u'),5);a=self.open().pending_deletions(limit=2);b=self.open().pending_deletions(after_seq=a[-1]['seq'],limit=2);c=self.open().pending_deletions(after_seq=b[-1]['seq'],limit=2);self.assertEqual(len(a+b+c),5);self.s.acknowledge_deletion(event_id=a[0]['event_id']);self.assertNotIn(a[0]['event_id'],[x['event_id'] for x in self.s.pending_deletions()])
    def test_expiry_purge_deletes_and_reconsent_does_not_resurrect(self):
        self.s.remember(subject='u',purpose='p',data_class='personal',value='x',ttl_seconds=1);self.now=102;self.assertEqual(self.s.export(subject='u'),[]);self.s.grant_consent(DurableMemoryConsent('u','p',frozenset({'personal'}),1000));self.assertEqual(self.s.export(subject='u'),[]);self.assertEqual(self.s.pending_deletions()[0]['reason'],'expired')
    def test_shorter_consent_reencrypts_aad_and_caps_expiry(self):
        self.s.remember(subject='u',purpose='p',data_class='personal',value='x',ttl_seconds=500);self.s.grant_consent(DurableMemoryConsent('u','p',frozenset({'personal'}),120));row=self.s.export(subject='u')[0];self.assertEqual(row['expires_at'],120);self.assertEqual(row['value'],'x')
    def test_concurrent_delete_and_write_are_serialized(self):
        errors=[]
        def write():
            try:self.s.remember(subject='u',purpose='p',data_class='personal',value='x',ttl_seconds=50)
            except DurableMemoryError as e:errors.append(e.code)
        threads=[threading.Thread(target=write) for _ in range(10)]
        for t in threads:t.start()
        self.s.revoke_purpose(subject='u',purpose='p')
        for t in threads:t.join()
        self.assertEqual(self.s.export(subject='u'),[]);self.assertTrue(all(e=='durable_memory_consent_missing' for e in errors))
    def test_cross_subject_delete_does_not_create_false_tombstone(self):
        r=self.s.remember(subject='u',purpose='p',data_class='personal',value='x',ttl_seconds=50);self.assertFalse(self.s.delete(subject='other',memory_id=r.memory_id));self.assertEqual(self.s.pending_deletions(),[])
    def test_storage_policy_does_not_claim_external_deletion_or_backup(self):
        p=self.s.storage_policy();self.assertFalse(p['plaintext_values_persisted']);self.assertTrue(p['external_backup_exclusion_required']);self.assertTrue(p['deletion_ack_is_external_fact'])

if __name__=='__main__':unittest.main()
