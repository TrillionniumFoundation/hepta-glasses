"""Real SQLite continuity tests; fixtures are not production anchors or keys."""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import hashlib, shutil, sqlite3, subprocess, tempfile, unittest

from services.skills.signed_package import PublisherKey, SPKI_PREFIX, SignedSkillError, canonical, sealed_inputs, sha256
from services.skills.signed_registry import SignedSkillRegistry

from services.skills.package_transparency import (
    PREFIX as TRANSPARENCY_PREFIX,
    WITNESS_PREFIX,
    TransparencyCheckpointAnchor,
    TransparencyLogKey,
    TransparencyProof,
    TransparencyVerifier,
    TransparencyWitnessKey,
    TransparencyWitnessProof,
    _verify_consistency,
)
from services.skills.signed_registry_schema import (
    CREATE_STATEMENTS, LEGACY_TABLES, REQUIRED_TABLES, RegistryStateAnchor,
    authority_digest, migrate_signed_skills_v1,
)


class RegistryStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.keys={"publisher-v1":PublisherKey("publisher",SPKI_PREFIX+b"k"*32,900,2000)}
    def path(self,n="registry.sqlite"): return str(Path(self.tmp.name)/n)
    def open(self,p=None,**kw):
        cfg=dict(subject="user",keys=self.keys,allowed_capabilities=frozenset({"display.text"}),allowed_domains=frozenset({"service.example"}),clock=lambda:1000); cfg.update(kw)
        return SignedSkillRegistry(p or self.path(),**cfg)
    def init(self,p=None):
        p=p or self.path(); r=self.open(p); r.close(); return p
    def err(self,code,fn):
        with self.assertRaises(SignedSkillError) as e: fn()
        self.assertEqual(e.exception.code,code)
    def tables(self,p):
        with closing(sqlite3.connect(p)) as db: return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    def checkpoint(self,p=None):
        r=self.open(p)
        try:return r.state_checkpoint()
        finally:r.close()
    def legacy(self,p):
        db=sqlite3.connect(p,isolation_level=None); db.row_factory=sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE hepta_component_schema(component TEXT PRIMARY KEY,version INTEGER NOT NULL)")
        for s in CREATE_STATEMENTS[:-1]: db.execute(s)
        policy=canonical({"subject":"user","capabilities":["display.text"],"domains":["service.example"],"maximum_entries":4096})
        binding=canonical({"publisher":"publisher","not_before":900,"not_after":2000})
        db.execute("INSERT INTO signed_skill_policy VALUES(1,?,?,0)",(policy,1000))
        db.execute("INSERT INTO signed_skill_keys VALUES('publisher-v1',?,?)",(sha256(self.keys["publisher-v1"].public_der),binding))
        db.execute("INSERT INTO hepta_component_schema VALUES('signed_skills',1)")
        return db

    def test_fresh_and_intact_reopen(self):
        p=self.init(); self.assertTrue(REQUIRED_TABLES<=self.tables(p)); r=self.open(p)
        try:self.assertEqual(r.storage.db.execute("SELECT COUNT(*) FROM signed_skill_keys").fetchone()[0],1)
        finally:r.close()

    def test_missing_or_unknown_tables_fail_without_recreation(self):
        for table in sorted(REQUIRED_TABLES):
            with self.subTest(table=table):
                p=self.init(self.path(table+".db"))
                with closing(sqlite3.connect(p)) as db,db: db.execute("DROP TABLE "+table)
                self.err("skill_registry_schema_integrity_invalid",lambda p=p:self.open(p)); self.assertNotIn(table,self.tables(p))
        p=self.path("unmarked.db")
        with closing(sqlite3.connect(p)) as db,db: db.execute("CREATE TABLE signed_skill_legacy(value TEXT)")
        self.err("skill_unmarked_schema_rejected",lambda:self.open(p))
        p=self.init(self.path("extra.db"))
        with closing(sqlite3.connect(p)) as db,db: db.execute("CREATE TABLE signed_skill_extra(value TEXT)")
        self.err("skill_registry_schema_integrity_invalid",lambda:self.open(p))

    def test_marker_and_policy_custody(self):
        p=self.init()
        with closing(sqlite3.connect(p)) as db,db: db.execute("DELETE FROM hepta_component_schema WHERE component='signed_skills'")
        self.err("skill_unmarked_schema_rejected",lambda:self.open(p))
        for n,sql in (("missing","DELETE FROM signed_skill_policy"),("state","UPDATE signed_skill_policy SET suspended=2")):
            p=self.init(self.path(n+".db"))
            with closing(sqlite3.connect(p)) as db,db: db.execute(sql)
            self.err("skill_registry_schema_integrity_invalid",lambda p=p:self.open(p))
        p=self.init(self.path("drift.db")); self.err("skill_registry_policy_migration_required",lambda:self.open(p,allowed_domains=frozenset()))

    def test_constraints_columns_and_sequence_are_required(self):
        p=self.init()
        with closing(sqlite3.connect(p)) as db,db:
            rows=db.execute("SELECT id,fingerprint,binding FROM signed_skill_keys").fetchall(); db.execute("ALTER TABLE signed_skill_keys RENAME TO old")
            db.execute("CREATE TABLE signed_skill_keys(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,binding BLOB NOT NULL)"); db.executemany("INSERT INTO signed_skill_keys VALUES(?,?,?)",rows); db.execute("DROP TABLE old")
        self.err("skill_registry_schema_integrity_invalid",lambda:self.open(p))
        p=self.init(self.path("event.db"))
        with closing(sqlite3.connect(p)) as db,db:
            db.execute("ALTER TABLE signed_skill_events RENAME TO old"); db.execute("CREATE TABLE signed_skill_events(sequence INTEGER PRIMARY KEY,event TEXT NOT NULL,target TEXT NOT NULL,digest TEXT NOT NULL,observed_at INTEGER NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)"); db.execute("DROP TABLE old")
        self.err("skill_registry_schema_integrity_invalid",lambda:self.open(p))
        p=self.init(self.path("column.db"))
        with closing(sqlite3.connect(p)) as db,db: db.execute("ALTER TABLE signed_skill_installed ADD COLUMN extra TEXT")
        self.err("skill_registry_schema_integrity_invalid",lambda:self.open(p))

    def test_unsealed_authority_state_is_rejected_at_reopen(self):
        p=self.init()
        with closing(sqlite3.connect(p)) as db,db: db.execute("UPDATE signed_skill_policy SET last_time=1234,suspended=1")
        self.err("skill_registry_state_integrity_invalid",lambda:self.open(p))

    def test_failed_constructor_releases_lock_and_bad_clock_rolls_back(self):
        p=self.init()
        with closing(sqlite3.connect(p)) as db,db: db.execute("DROP TABLE signed_skill_revocations")
        self.err("skill_registry_schema_integrity_invalid",lambda:self.open(p))
        with closing(sqlite3.connect(p,isolation_level=None,timeout=.1)) as db: db.execute("BEGIN IMMEDIATE"); db.execute("ROLLBACK")
        p=self.path("clock.db"); self.err("skill_clock_invalid",lambda:self.open(p,clock=lambda:True)); self.assertFalse(REQUIRED_TABLES&self.tables(p))

    def test_revision_changes_once_and_noop_does_not_advance(self):
        r=self.open(); a=r.state_checkpoint(); r.revoke("skill","a"); b=r.state_checkpoint(); r.revoke("skill","a"); c=r.state_checkpoint(); r.close()
        self.assertEqual(b.revision,a.revision+1); self.assertNotEqual(a.authority_digest,b.authority_digest); self.assertEqual((b.revision,b.authority_digest),(c.revision,c.authority_digest)); self.assertFalse(c.external_evidence)

    def test_anchor_descendant_rollback_fork_and_missing_instance(self):
        p=self.init(); old=self.checkpoint(p); backup=self.path("old.db"); shutil.copy2(p,backup)
        r=self.open(p); r.revoke("skill","a"); new=r.state_checkpoint(); r.close()
        self.open(p,state_anchor=RegistryStateAnchor(old.instance_id,old.revision,old.authority_digest)).close()
        self.err("skill_registry_state_rollback",lambda:self.open(backup,state_anchor=RegistryStateAnchor(new.instance_id,new.revision,new.authority_digest)))
        with closing(sqlite3.connect(p)) as db,db:
            db.row_factory=sqlite3.Row; db.execute("UPDATE signed_skill_policy SET last_time=1001"); db.execute("UPDATE signed_skill_state SET revision=?,authority_digest=?",(new.revision,authority_digest(db)))
        self.err("skill_registry_state_fork",lambda:self.open(p,state_anchor=RegistryStateAnchor(new.instance_id,new.revision,new.authority_digest)))
        missing=self.path("missing.db"); self.err("skill_registry_state_instance_mismatch",lambda:self.open(missing,state_anchor=RegistryStateAnchor("a"*64,1,"b"*64))); self.assertFalse(Path(missing).exists())

    def test_path_replacement_and_symlink_fail(self):
        p=self.init(); r=self.open(p); Path(p).rename(self.path("detached.db")); sqlite3.connect(p).close()
        try:self.err("skill_registry_database_replaced",lambda:r.revoke("skill","a"))
        finally:r.close()
        target=Path(self.path("target.db")); sqlite3.connect(target).close(); link=Path(self.path("link.db")); link.symlink_to(target)
        self.err("skill_registry_database_identity_invalid",lambda:self.open(str(link)))

    def test_seal_failure_rolls_back_authority(self):
        p=self.init(); r=self.open(p)
        try:
            with r.storage.transaction() as db: db.execute("CREATE TRIGGER stop BEFORE UPDATE ON signed_skill_state WHEN NEW.revision>OLD.revision BEGIN SELECT RAISE(ABORT,'x'); END")
            self.err("skill_registry_storage_integrity_invalid",lambda:r.revoke("skill","a"))
        finally:r.close()
        with closing(sqlite3.connect(p)) as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM signed_skill_revocations").fetchone()[0],0); self.assertEqual(db.execute("SELECT COUNT(*) FROM signed_skill_events").fetchone()[0],0)

    def test_offline_migration_preserves_rows_and_reports_boundary(self):
        p=self.path(); db=self.legacy(p); body=[1,"revoked.skill","legacy","",1000,""]
        db.execute("INSERT INTO signed_skill_events VALUES(?,?,?,?,?,?,?)",(*body,sha256(canonical(body)))); db.execute("INSERT INTO signed_skill_revocations VALUES('skill','legacy')")
        before={t:[tuple(r) for r in db.execute("SELECT * FROM "+t)] for t in LEGACY_TABLES}; db.close(); report=migrate_signed_skills_v1(p)
        with closing(sqlite3.connect(p)) as db: after={t:[tuple(r) for r in db.execute("SELECT * FROM "+t)] for t in LEGACY_TABLES}
        self.assertEqual(before,after); self.assertFalse(report["old_processes_stopped_verified"]); self.assertFalse(report["external_anchor_verified"]); self.open(p).close()

    def test_migration_failure_and_repeated_migration_fail_closed(self):
        p=self.path(); db=self.legacy(p); db.execute("CREATE TRIGGER stop BEFORE INSERT ON hepta_component_schema WHEN NEW.component='signed_skills_state' BEGIN SELECT RAISE(ABORT,'x'); END"); db.close()
        self.err("skill_registry_storage_integrity_invalid",lambda:migrate_signed_skills_v1(p))
        with closing(sqlite3.connect(p)) as db: self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='signed_skill_state'").fetchone())
        p=self.path("done.db"); self.legacy(p).close(); migrate_signed_skills_v1(p); self.err("skill_registry_migration_schema_invalid",lambda:migrate_signed_skills_v1(p))

    def test_open_legacy_writer_detected_after_migration(self):
        p=self.path(); old=self.legacy(p); migrate_signed_skills_v1(p); r=self.open(p)
        try:
            old.execute("BEGIN IMMEDIATE"); old.execute("UPDATE signed_skill_policy SET last_time=1001"); old.execute("COMMIT")
            self.err("skill_registry_state_integrity_invalid",r.state_checkpoint)
        finally:old.close(); r.close()

    def test_legacy_requires_explicit_migration_and_clock_error_is_sanitized(self):
        p=self.path(); self.legacy(p).close(); self.err("skill_registry_state_migration_required",lambda:self.open(p))
        def broken(): raise RuntimeError("private-clock-marker")
        caught=None
        try:self.open(self.path("badclock.db"),clock=broken)
        except SignedSkillError as e:caught=e
        self.assertEqual(caught.code,"skill_clock_invalid"); self.assertIsNone(caught.__cause__); self.assertNotIn("private-clock-marker",repr(caught))


def _leaf(value: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + value).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(size: int) -> int:
    return 1 << ((size - 1).bit_length() - 1)


def _root(values: list[bytes]) -> bytes:
    if len(values) == 1:
        return _leaf(values[0])
    point = _split(len(values))
    return _node(_root(values[:point]), _root(values[point:]))


def _inclusion(values: list[bytes], index: int) -> tuple[bytes, ...]:
    if len(values) == 1:
        return ()
    point = _split(len(values))
    if index < point:
        return _inclusion(values[:point], index) + (_root(values[point:]),)
    return _inclusion(values[point:], index - point) + (_root(values[:point]),)


def _consistency(values: list[bytes], old_size: int) -> tuple[bytes, ...]:
    def subproof(items: list[bytes], size: int, complete: bool) -> tuple[bytes, ...]:
        if size == len(items):
            return () if complete else (_root(items),)
        point = _split(len(items))
        if size <= point:
            return subproof(items[:point], size, complete) + (_root(items[point:]),)
        return subproof(items[point:], size - point, False) + (_root(items[:point]),)
    return subproof(values, old_size, True)


class TransparencyConsistencyWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log_private, cls.log_public = cls.keypair()
        cls.a_private, cls.a_public = cls.keypair()
        cls.a2_private, cls.a2_public = cls.keypair()
        cls.b_private, cls.b_public = cls.keypair()
        cls.other_private, cls.other_public = cls.keypair()

    @staticmethod
    def keypair():
        private = subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER"],
            capture_output=True, check=True, timeout=5,
        ).stdout
        public = subprocess.run(
            ["/usr/bin/openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=private, capture_output=True, check=True, timeout=5,
        ).stdout
        return private, public

    @staticmethod
    def sign(private: bytes, prefix: bytes, document: bytes) -> bytes:
        with sealed_inputs((private, prefix + document)) as descriptors:
            return subprocess.run(
                [
                    "/usr/bin/openssl", "pkeyutl", "-sign", "-keyform", "DER",
                    "-inkey", f"/proc/self/fd/{descriptors[0]}", "-rawin",
                    "-in", f"/proc/self/fd/{descriptors[1]}",
                ],
                pass_fds=descriptors, capture_output=True, check=True, timeout=5,
            ).stdout

    def setUp(self):
        self.now = 1000
        self.values = [f"leaf-{i}".encode() for i in range(9)]
        self.old_size = 3
        self.anchor = TransparencyCheckpointAnchor(
            "package-log", self.old_size, _root(self.values[: self.old_size]).hex()
        )
        self.log_key = TransparencyLogKey("package-log", self.log_public, 900, 1800)
        self.witness_keys = {
            "a-v1": TransparencyWitnessKey("witness-a", self.a_public, 900, 1600),
            "a-v2": TransparencyWitnessKey("witness-a", self.a2_public, 900, 1700),
            "b-v1": TransparencyWitnessKey("witness-b", self.b_public, 900, 1500),
        }

    def verifier(self, **changes):
        values = dict(
            checkpoint_anchor=self.anchor,
            witness_keys=self.witness_keys,
            witness_quorum=2,
        )
        values.update(changes)
        return TransparencyVerifier(
            {"log-v1": self.log_key}, clock=lambda: self.now, **values
        )

    def statement(self, checkpoint: bytes, *, key_id: str, witness_id: str,
                  private: bytes, **changes) -> TransparencyWitnessProof:
        parsed = __import__("json").loads(checkpoint)
        value = {
            "schema_version": 1,
            "witness_id": witness_id,
            "key_id": key_id,
            "log_id": parsed["log_id"],
            "tree_size": parsed["tree_size"],
            "root_sha256": parsed["root_sha256"],
            "checkpoint_sha256": sha256(checkpoint),
            "issued_at": 1000,
            "expires_at": 1200,
        }
        value.update(changes)
        raw = canonical(value)
        return TransparencyWitnessProof(raw, self.sign(private, WITNESS_PREFIX, raw))

    def proof(self, *, values=None, old_size=None, index=5, witnesses=True,
              checkpoint_changes=None):
        values = list(values or self.values)
        old_size = self.old_size if old_size is None else old_size
        checkpoint = {
            "schema_version": 1,
            "log_id": "package-log",
            "key_id": "log-v1",
            "tree_size": len(values),
            "root_sha256": _root(values).hex(),
            "issued_at": 1000,
            "expires_at": 1300,
        }
        if checkpoint_changes:
            checkpoint.update(checkpoint_changes)
        raw = canonical(checkpoint)
        witness_values = ()
        if witnesses:
            witness_values = (
                self.statement(raw, key_id="a-v1", witness_id="witness-a", private=self.a_private),
                self.statement(raw, key_id="b-v1", witness_id="witness-b", private=self.b_private),
            )
        return values[index], TransparencyProof(
            raw,
            self.sign(self.log_private, TRANSPARENCY_PREFIX, raw),
            index,
            _inclusion(values, index),
            _consistency(values, old_size),
            witness_values,
        )

    def error(self, code, callback):
        with self.assertRaises(SignedSkillError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_all_rfc6962_prefix_consistency_proofs(self):
        for new_size in range(2, 24):
            values = [f"item-{i}".encode() for i in range(new_size)]
            for old_size in range(1, new_size + 1):
                with self.subTest(old=old_size, new=new_size):
                    _verify_consistency(
                        old_size,
                        new_size,
                        _root(values[:old_size]),
                        _root(values),
                        _consistency(values, old_size),
                    )

    def test_consistency_and_unique_witness_quorum_verify(self):
        document, proof = self.proof()
        result = self.verifier().verify(document, proof)
        self.assertTrue(result.consistency_verified)
        self.assertEqual(result.witness_ids, ("witness-a", "witness-b"))
        self.assertEqual(result.expires_at, 1200)

    def test_tree_rollback_equal_fork_and_missing_consistency_are_rejected(self):
        smaller = self.values[:2]
        doc, proof = self.proof(values=smaller, old_size=2, index=1)
        self.error(
            "skill_transparency_consistency_proof_invalid",
            lambda: self.verifier().verify(doc, proof),
        )
        equal = self.values[: self.old_size]
        doc, proof = self.proof(values=equal, old_size=self.old_size, index=1)
        bad = TransparencyProof(
            proof.checkpoint,
            proof.signature,
            proof.leaf_index,
            proof.audit_path,
            (b"x" * 32,),
            proof.witnesses,
        )
        self.error(
            "skill_transparency_consistency_proof_invalid",
            lambda: self.verifier().verify(doc, bad),
        )
        doc, proof = self.proof()
        missing = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path,
            (), proof.witnesses,
        )
        self.error(
            "skill_transparency_consistency_proof_invalid",
            lambda: self.verifier().verify(doc, missing),
        )

    def test_corrupted_consistency_path_is_rejected(self):
        document, proof = self.proof()
        bad_path = proof.consistency_path[:-1] + (b"z" * 32,)
        bad = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index,
            proof.audit_path, bad_path, proof.witnesses,
        )
        self.error(
            "skill_transparency_consistency_proof_invalid",
            lambda: self.verifier().verify(document, bad),
        )

    def test_same_witness_identity_never_counts_twice(self):
        document, proof = self.proof(witnesses=False)
        duplicate = (
            self.statement(proof.checkpoint, key_id="a-v1", witness_id="witness-a", private=self.a_private),
            self.statement(proof.checkpoint, key_id="a-v2", witness_id="witness-a", private=self.a2_private),
        )
        candidate = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path,
            proof.consistency_path, duplicate,
        )
        self.error(
            "skill_transparency_witness_duplicate_identity",
            lambda: self.verifier().verify(document, candidate),
        )

    def test_missing_quorum_and_bad_supplied_witness_fail_closed(self):
        document, proof = self.proof(witnesses=False)
        one = (
            self.statement(proof.checkpoint, key_id="a-v1", witness_id="witness-a", private=self.a_private),
        )
        candidate = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path,
            proof.consistency_path, one,
        )
        self.error(
            "skill_transparency_witness_quorum_missing",
            lambda: self.verifier().verify(document, candidate),
        )
        bad = TransparencyWitnessProof(one[0].statement, b"x" * 64)
        candidate = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path,
            proof.consistency_path, (bad, proof.witnesses[0]) if proof.witnesses else (bad,),
        )
        self.error(
            "skill_transparency_witness_signature_invalid",
            lambda: self.verifier(witness_quorum=1).verify(document, candidate),
        )

    def test_witness_binding_signature_domain_and_expiry_are_strict(self):
        document, proof = self.proof(witnesses=False)
        cases = (
            ({"root_sha256": "0" * 64}, "skill_transparency_witness_binding_mismatch"),
            ({"checkpoint_sha256": "0" * 64}, "skill_transparency_witness_binding_mismatch"),
            ({"tree_size": 8}, "skill_transparency_witness_binding_mismatch"),
            ({"log_id": "other-log"}, "skill_transparency_witness_binding_mismatch"),
            ({"expires_at": 1601}, "skill_transparency_witness_outlives_key"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                first = self.statement(
                    proof.checkpoint,
                    key_id="a-v1", witness_id="witness-a",
                    private=self.a_private, **changes,
                )
                candidate = TransparencyProof(
                    proof.checkpoint, proof.signature, proof.leaf_index,
                    proof.audit_path, proof.consistency_path, (first,),
                )
                self.error(code, lambda c=candidate: self.verifier(witness_quorum=1).verify(document, c))
        first = self.statement(
            proof.checkpoint, key_id="a-v1", witness_id="witness-a",
            private=self.other_private,
        )
        candidate = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index,
            proof.audit_path, proof.consistency_path, (first,),
        )
        self.error(
            "skill_transparency_witness_signature_invalid",
            lambda: self.verifier(witness_quorum=1).verify(document, candidate),
        )
        parsed = __import__("json").loads(proof.checkpoint)
        statement = canonical({
            "schema_version": 1, "witness_id": "witness-a", "key_id": "a-v1",
            "log_id": parsed["log_id"], "tree_size": parsed["tree_size"],
            "root_sha256": parsed["root_sha256"],
            "checkpoint_sha256": sha256(proof.checkpoint),
            "issued_at": 1000, "expires_at": 1200,
        })
        wrong_domain = TransparencyWitnessProof(
            statement, self.sign(self.a_private, TRANSPARENCY_PREFIX, statement)
        )
        candidate = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index, proof.audit_path,
            proof.consistency_path, (wrong_domain,),
        )
        self.error(
            "skill_transparency_witness_signature_invalid",
            lambda: self.verifier(witness_quorum=1).verify(document, candidate),
        )

    def test_unconfigured_extra_evidence_is_not_ignored(self):
        base = TransparencyVerifier({"log-v1": self.log_key}, clock=lambda: self.now)
        document, proof = self.proof()
        self.error(
            "skill_transparency_consistency_unconfigured",
            lambda: base.verify(document, proof),
        )
        no_consistency = TransparencyProof(
            proof.checkpoint, proof.signature, proof.leaf_index,
            proof.audit_path, (), proof.witnesses,
        )
        self.error(
            "skill_transparency_witness_unconfigured",
            lambda: base.verify(document, no_consistency),
        )

    def test_legacy_four_field_proof_and_optional_absence_remain_compatible(self):
        document, advanced = self.proof()
        legacy_proof = TransparencyProof(
            advanced.checkpoint, advanced.signature, advanced.leaf_index, advanced.audit_path
        )
        base = TransparencyVerifier({"log-v1": self.log_key}, clock=lambda: self.now)
        result = base.verify(document, legacy_proof)
        self.assertFalse(result.consistency_verified)
        self.assertEqual(result.witness_ids, ())
        optional = TransparencyVerifier(
            {"log-v1": self.log_key}, clock=lambda: self.now, required=False,
            checkpoint_anchor=self.anchor, witness_keys=self.witness_keys, witness_quorum=2,
        )
        self.assertIsNone(optional.verify(document, None))

    def test_legacy_binding_is_stable_and_advanced_policy_is_distinct(self):
        legacy = TransparencyVerifier({"log-v1": self.log_key}, clock=lambda: self.now)
        expected = sha256(canonical({
            "schema_version": 1,
            "required": True,
            "keys": [{
                "key_id": "log-v1",
                "log_id": "package-log",
                "public_key_sha256": sha256(self.log_public),
                "not_before": 900,
                "not_after": 1800,
            }],
        }))
        self.assertEqual(legacy.binding, expected)
        self.assertNotEqual(legacy.binding, self.verifier().binding)

    def test_configuration_and_quorum_shapes_are_immutable_and_bounded(self):
        self.error(
            "skill_transparency_configuration_invalid",
            lambda: TransparencyVerifier(
                {"log-v1": self.log_key}, clock=lambda: self.now, witness_keys=[]
            ),
        )
        for quorum in (True, 0, 3, -1):
            with self.subTest(quorum=quorum):
                self.error(
                    "skill_transparency_witness_quorum_invalid",
                    lambda q=quorum: TransparencyVerifier(
                        {"log-v1": self.log_key}, clock=lambda: self.now,
                        witness_keys=self.witness_keys, witness_quorum=q,
                    ),
                )
        verifier = self.verifier()
        self.error(
            "skill_transparency_configuration_immutable",
            lambda: setattr(verifier, "_witness_quorum", 1),
        )

    def test_registry_persists_advanced_binding_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "registry.db")
            config = dict(
                subject="user",
                keys={"publisher-v1": PublisherKey("publisher", SPKI_PREFIX + b"p" * 32, 900, 2000)},
                allowed_capabilities=frozenset(),
                allowed_domains=frozenset(),
                clock=lambda: self.now,
            )
            first = SignedSkillRegistry(path, transparency_verifier=self.verifier(), **config)
            first.close()
            same = SignedSkillRegistry(path, transparency_verifier=self.verifier(), **config)
            same.close()
            changed = TransparencyVerifier(
                {"log-v1": self.log_key}, clock=lambda: self.now,
                checkpoint_anchor=self.anchor,
                witness_keys=self.witness_keys,
                witness_quorum=1,
            )
            self.error(
                "skill_registry_policy_migration_required",
                lambda: SignedSkillRegistry(path, transparency_verifier=changed, **config),
            )


if __name__ == "__main__": unittest.main()
