"""Real SQLite continuity tests; fixtures are not production anchors or keys."""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import shutil, sqlite3, tempfile, unittest

from services.skills.signed_package import PublisherKey, SPKI_PREFIX, SignedSkillError, canonical, sha256
from services.skills.signed_registry import SignedSkillRegistry
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


if __name__ == "__main__": unittest.main()
