"""Object-identity regressions for Signed Registry SQLite custody.

The races are local deterministic pathname substitutions. They are not a hostile
kernel, remote anchor, or proof that every legacy process was stopped.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from services.skills.signed_package import (
    PublisherKey, SPKI_PREFIX, SignedSkillError, canonical, sha256,
)
from services.skills.signed_registry import SignedSkillRegistry
from services.skills.signed_registry_schema import (
    CREATE_STATEMENTS, migrate_signed_skills_v1,
)
from services.skills import signed_registry_schema as storage_module


class SignedRegistryObjectBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "registry.sqlite"
        self.keys = {
            "publisher-v1": PublisherKey(
                "publisher", SPKI_PREFIX + b"o" * 32, 900, 2000
            )
        }

    def open(self, path: Path | None = None) -> SignedSkillRegistry:
        return SignedSkillRegistry(
            str(path or self.path),
            subject="user",
            keys=self.keys,
            allowed_capabilities=frozenset({"display.text"}),
            allowed_domains=frozenset(),
            clock=lambda: 1000,
        )

    def error(self, code: str, callback) -> None:
        with self.assertRaises(SignedSkillError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def legacy(self, path: Path) -> None:
        db = sqlite3.connect(path, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE hepta_component_schema("
            "component TEXT PRIMARY KEY,version INTEGER NOT NULL)"
        )
        for statement in CREATE_STATEMENTS[:-1]:
            db.execute(statement)
        policy = canonical({
            "subject": "user",
            "capabilities": ["display.text"],
            "domains": [],
            "maximum_entries": 4096,
        })
        binding = canonical({
            "publisher": "publisher", "not_before": 900, "not_after": 2000,
        })
        db.execute("INSERT INTO signed_skill_policy VALUES(1,?,?,0)", (policy, 1000))
        db.execute(
            "INSERT INTO signed_skill_keys VALUES('publisher-v1',?,?)",
            (sha256(self.keys["publisher-v1"].public_der), binding),
        )
        db.execute("INSERT INTO hepta_component_schema VALUES('signed_skills',1)")
        db.close()

    def test_constructor_rejects_path_replacement_after_connect_before_identity_check(self) -> None:
        registry = self.open()
        before = registry.state_checkpoint()
        registry.close()
        detached = Path(self.tmp.name) / "detached.sqlite"
        real_connect = storage_module.sqlite3.connect

        def replace_after_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            self.path.rename(detached)
            real_connect(self.path).close()
            return connection

        with mock.patch.object(
            storage_module.sqlite3, "connect", side_effect=replace_after_connect
        ):
            self.error("skill_registry_database_replaced", self.open)

        with closing(sqlite3.connect(self.path)) as replacement:
            self.assertEqual(
                replacement.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'signed_skill_%'"
                ).fetchone()[0],
                0,
            )
        original = self.open(detached)
        try:
            after = original.state_checkpoint()
        finally:
            original.close()
        self.assertEqual(
            (before.instance_id, before.revision, before.authority_digest),
            (after.instance_id, after.revision, after.authority_digest),
        )

    def test_migration_rejects_path_aba_between_connect_and_first_transaction(self) -> None:
        self.legacy(self.path)
        alternate = Path(self.tmp.name) / "alternate.sqlite"
        sqlite3.connect(alternate).close()
        detached = Path(self.tmp.name) / "legacy-detached.sqlite"
        real_connect = storage_module.sqlite3.connect

        def aba_after_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            self.path.rename(detached)
            alternate.rename(self.path)
            self.path.rename(alternate)
            detached.rename(self.path)
            return connection

        with mock.patch.object(
            storage_module.sqlite3, "connect", side_effect=aba_after_connect
        ):
            self.error(
                "skill_registry_database_replaced",
                lambda: migrate_signed_skills_v1(str(self.path)),
            )

        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name='signed_skill_state'"
                ).fetchone()
            )
            self.assertIsNone(
                db.execute(
                    "SELECT version FROM hepta_component_schema "
                    "WHERE component='signed_skills_state'"
                ).fetchone()
            )

    def test_parent_symlink_and_hardlink_alias_are_rejected(self) -> None:
        actual = Path(self.tmp.name) / "actual"
        actual.mkdir()
        alias = Path(self.tmp.name) / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        self.error(
            "skill_registry_database_identity_invalid",
            lambda: self.open(alias / "registry.sqlite"),
        )

        registry = self.open()
        registry.close()
        hardlink = Path(self.tmp.name) / "hardlink.sqlite"
        os.link(self.path, hardlink)
        self.error("skill_registry_database_identity_invalid", self.open)

    def test_held_object_and_parent_descriptors_close_with_registry(self) -> None:
        registry = self.open()
        file_fd = registry._database_binding.file_fd
        parent_fd = registry._database_binding.parent_fd
        registry.close()
        for descriptor in (file_fd, parent_fd):
            with self.assertRaises(OSError):
                storage_module.os.fstat(descriptor)


if __name__ == "__main__":
    unittest.main()
