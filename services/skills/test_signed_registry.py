"""Actual Ed25519/SQLite/package tests; ephemeral fixture keys are not authority."""
from __future__ import annotations

import dataclasses
import io
import json
import os
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.skills.signed_package import (
    PREFIX, PublisherKey, SignedSkillError, canonical, inspect_package, parse_manifest,
    sealed_inputs, sha256,
)
from services.skills.signed_registry import InstallConsent, SignedSkillRegistry


def archive(files=None, *, compression=zipfile.ZIP_STORED, mode=None):
    files = files or {"main.py": b"# inert fixture, never executed\n"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as handle:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path)
            info.compress_type = compression
            if mode is not None:
                info.create_system = 3
                info.external_attr = mode << 16
            handle.writestr(info, data)
    return buffer.getvalue()


class SignedRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Private fixture bytes stay in process memory and anonymous descriptors.
        cls.private = subprocess.run(["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER"],
            capture_output=True, check=True, timeout=5).stdout
        cls.public = subprocess.run(["/usr/bin/openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=cls.private, capture_output=True, check=True, timeout=5).stdout

    @classmethod
    def tearDownClass(cls):
        cls.private = b""  # no claim of reliable Python memory zeroization

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "registry.sqlite")
        self.now = 1000
        self.keys = {"publisher-v1": PublisherKey("publisher", self.public, 900, 2000)}
        self.registry = self.open()
        self.package = archive()
        self.body = self.manifest()

    def open(self, **changes):
        config = dict(subject="user", keys=self.keys, allowed_capabilities=frozenset({"display.text", "memory.read"}),
                      allowed_domains=frozenset({"service.example"}), clock=lambda: self.now)
        config.update(changes)
        registry = SignedSkillRegistry(self.path, **config)
        self.addCleanup(registry.close)
        return registry

    def manifest(self, **changes):
        files = {"main.py": b"# inert fixture, never executed\n"}
        body = dict(schema_version=1, skill_id="clock", version="1.0.0", publisher="publisher", key_id="publisher-v1",
                    entrypoint="main.py", capabilities=["display.text"], data_classes=["public"], network_domains=[],
                    risk_tier="R1", timeout_ms=1000, issued_at=1000, expires_at=1500,
                    package_sha256=sha256(self.package), files=[{"path": p, "size": len(b), "sha256": sha256(b)} for p, b in files.items()],
                    dependencies=[])
        body.update(changes)
        return body

    def signature(self, document, *, prefix=PREFIX):
        with sealed_inputs((self.private, prefix + document)) as descriptors:
            result = subprocess.run(["/usr/bin/openssl", "pkeyutl", "-sign", "-keyform", "DER", "-inkey",
                f"/proc/self/fd/{descriptors[0]}", "-rawin", "-in", f"/proc/self/fd/{descriptors[1]}"],
                pass_fds=descriptors, capture_output=True, check=True, timeout=5)
        return result.stdout

    def install(self, body=None, *, registry=None, package=None, consent=None, signature=None):
        raw = canonical(body or self.body)
        return (registry or self.registry).install(raw, signature=signature or self.signature(raw),
            package=package or self.package, consent=consent or InstallConsent("user", sha256(raw), 1400))

    def error(self, code, action):
        with self.assertRaises(SignedSkillError) as result:
            action()
        self.assertEqual(result.exception.code, code)

    def count(self, table):
        with self.registry.storage.transaction() as db:
            return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_real_signature_roundtrip_reopen_and_immutable_files(self):
        checked = self.install()
        reopened = self.open().resolve("clock", package=self.package)
        self.assertEqual(checked, reopened)
        value = checked.manifest
        value["capabilities"].append("shell")
        self.assertEqual(checked.manifest["capabilities"], ["display.text"])
        self.assertIsInstance(checked.files, tuple)
        self.assertEqual(self.registry.verify_local_audit()["events"], 1)

    def test_no_private_signer_or_package_payload_in_database(self):
        self.install()
        for path in Path(self.temp.name).glob("registry.sqlite*"):
            data = path.read_bytes()
            self.assertNotIn(self.private, data)
            self.assertNotIn(b"# inert fixture, never executed", data)

    def test_duplicate_install_is_idempotent(self):
        first = self.install()
        self.assertEqual(first, self.install(registry=self.open()))
        self.assertEqual(self.registry.verify_local_audit()["events"], 1)

    def test_modified_document_invalidates_signature(self):
        old = self.signature(canonical(self.body))
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, timeout_ms=10), signature=old))

    def test_unrelated_signature_domain_is_rejected(self):
        self.error("skill_package_verification_failed", lambda: self.install(
            signature=self.signature(canonical(self.body), prefix=b"OTHER-PROTOCOL\n")))

    def test_no_hmac_or_unsigned_fallback(self):
        for sig in (b"x" * 32, b"0" * 64):
            with self.subTest(length=len(sig)):
                with self.assertRaises(SignedSkillError):
                    self.install(signature=sig)
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_publisher_bound_to_specific_public_key(self):
        self.error("skill_publisher_key_mismatch", lambda: self.install(dict(self.body, publisher="other")))
        self.error("skill_publisher_key_mismatch", lambda: self.install(dict(self.body, key_id="unknown")))

    def test_key_alias_rejected(self):
        self.error("skill_public_key_alias", lambda: self.open(keys={**self.keys, "alias": self.keys["publisher-v1"]}))

    def test_pinned_key_identity_cannot_change_on_restart(self):
        changed = {"publisher-v1": dataclasses.replace(self.keys["publisher-v1"], publisher="other")}
        self.error("skill_public_key_binding_changed", lambda: self.open(keys=changed))

    def test_pinned_key_validity_cannot_silently_change(self):
        changed = {"publisher-v1": dataclasses.replace(self.keys["publisher-v1"], not_after=2100)}
        self.error("skill_public_key_binding_changed", lambda: self.open(keys=changed))

    def test_invalid_key_algorithm_shape_rejected(self):
        with self.assertRaises(SignedSkillError):
            PublisherKey("publisher", b"wrong" * 9, 900, 2000)
        with self.assertRaises(SignedSkillError):
            PublisherKey("publisher", self.public, True, 2000)

    def test_manifest_cannot_outlive_key(self):
        self.error("skill_manifest_outlives_key", lambda: self.install(dict(self.body, expires_at=2001)))

    def test_future_and_expired_manifests_rejected(self):
        self.error("skill_signer_or_manifest_expired", lambda: self.install(dict(self.body, issued_at=1001)))
        self.error("skill_signer_or_manifest_expired", lambda: self.install(dict(self.body, issued_at=900, expires_at=1000)))

    def test_exact_manifest_consent_required(self):
        self.error("skill_exact_consent_required", lambda: self.install(consent=InstallConsent("user", "a" * 64, 1400)))
        self.error("skill_exact_consent_required", lambda: self.install(consent=InstallConsent("other", sha256(canonical(self.body)), 1400)))

    def test_expired_consent_does_not_admit(self):
        self.error("skill_consent_expired", lambda: self.install(consent=InstallConsent("user", sha256(canonical(self.body)), 1000)))
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_capability_and_network_policy_enforced(self):
        self.error("skill_capability_not_allowed", lambda: self.install(dict(self.body, capabilities=["shell"])))
        self.error("skill_network_domain_not_allowed", lambda: self.install(dict(self.body, network_domains=["other.example"])))

    def test_r4_unknown_risk_and_boolean_timeout_rejected(self):
        for changes in ({"risk_tier": "R4"}, {"risk_tier": "unknown"}, {"timeout_ms": True}, {"schema_version": True}):
            with self.subTest(changes=changes), self.assertRaises(SignedSkillError):
                self.install(dict(self.body, **changes))

    def test_duplicate_unknown_and_noncanonical_json_rejected(self):
        raw = canonical(self.body)
        for altered in (raw + b" ", b'{"schema_version":1,' + raw[1:], canonical(dict(self.body, extra=True))):
            with self.assertRaises(SignedSkillError):
                parse_manifest(altered)

    def test_bounded_sorted_unique_manifest_collections(self):
        for changes in ({"capabilities": ["memory.read", "display.text"]}, {"data_classes": ["public", "public"]},
                        {"files": []}, {"dependencies": [{}] * 33}, {"network_domains": ["*.example"]}):
            with self.subTest(changes=changes), self.assertRaises(SignedSkillError):
                parse_manifest(canonical(dict(self.body, **changes)))

    def test_secret_data_classes_forbidden(self):
        for cls in ("raw_audio", "credential", "secret"):
            self.error("skill_data_class_invalid", lambda: self.install(dict(self.body, data_classes=[cls])))

    def test_changed_package_and_file_hash_rejected(self):
        self.error("skill_package_verification_failed", lambda: self.install(package=self.package + b"changed"))
        files = [dict(self.body["files"][0], sha256="a" * 64)]
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, files=files)))

    def test_traversal_windows_and_alias_paths_rejected(self):
        for path in ("../main.py", "/main.py", "a\\main.py", "C:main.py", "nul.py", "con", "a//b", "a/./b", "main.py."):
            with self.subTest(path=path), self.assertRaises(SignedSkillError):
                parse_manifest(canonical(dict(self.body, entrypoint=path)))

    def test_case_and_file_directory_conflicts_rejected(self):
        row = self.body["files"][0]
        for extra in (dict(row, path="MAIN.py"), dict(row, path="main.py/child")):
            files = sorted([row, extra], key=lambda v: v["path"])
            with self.assertRaises(SignedSkillError):
                parse_manifest(canonical(dict(self.body, files=files)))

    def test_symlink_zip_member_rejected(self):
        raw = archive(mode=stat.S_IFLNK | 0o777)
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_compressed_archives_rejected(self):
        raw = archive(compression=zipfile.ZIP_DEFLATED)
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_extra_archive_member_rejected(self):
        raw = archive({"main.py": b"# inert fixture, never executed\n", "hidden.py": b"inert"})
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_archive_comment_or_trailer_rejected(self):
        buffer = io.BytesIO(self.package)
        with zipfile.ZipFile(buffer, "a") as z:
            z.comment = b"comment"
        for raw in (buffer.getvalue(), self.package + b"trailer"):
            self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_directory_entry_and_duplicate_members_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("folder/", b"")
        raw = buffer.getvalue()
        with self.assertRaises(SignedSkillError):
            inspect_package(dict(self.body, package_sha256=sha256(raw)), raw)

    def test_central_directory_entry_limit_before_parsing(self):
        raw = bytearray(self.package)
        struct.pack_into("<HH", raw, len(raw) - 14, 129, 129)
        raw = bytes(raw)
        self.error("skill_archive_layout_invalid", lambda: inspect_package(dict(self.body, package_sha256=sha256(raw)), raw))

    def test_upgrade_downgrade_and_same_version_replacement(self):
        self.install()
        self.error("skill_version_manifest_conflict", lambda: self.install(dict(self.body, timeout_ms=10)))
        self.install(dict(self.body, version="2.0.0"))
        self.error("skill_version_downgrade_forbidden", self.install)

    def test_same_version_does_not_refresh_consent(self):
        until = InstallConsent("user", sha256(canonical(self.body)), 1001)
        self.install(consent=until)
        self.now = 1001
        self.error("skill_reconsent_requires_new_version", self.install)

    def test_subject_scope_policy_cannot_change(self):
        self.error("skill_registry_policy_migration_required", lambda: self.open(subject="another"))
        self.error("skill_registry_policy_migration_required", lambda: self.open(allowed_domains=frozenset()))

    def test_revoke_unknown_skill_before_install_survives_restart(self):
        self.registry.revoke("skill", "clock")
        self.error("skill_revoked", lambda: self.install(registry=self.open()))

    def test_key_publisher_and_package_revocations(self):
        for kind, target in (("key", "publisher-v1"), ("publisher", "publisher"), ("package", sha256(self.package))):
            with self.subTest(kind=kind):
                other_path = str(Path(self.temp.name) / (kind + ".sqlite"))
                r = SignedSkillRegistry(other_path, subject="user", keys=self.keys, allowed_capabilities=frozenset({"display.text"}),
                                        allowed_domains=frozenset(), clock=lambda: self.now)
                try:
                    self.install(registry=r)
                    r.revoke(kind, target)
                    self.error("skill_revoked", lambda: r.resolve("clock", package=self.package))
                finally:
                    r.close()

    def test_revocation_idempotent_and_works_with_broken_clock(self):
        self.install()
        self.now = True
        self.registry.revoke("skill", "clock")
        self.registry.revoke("skill", "clock")
        self.assertEqual(self.registry.verify_local_audit()["events"], 2)
        self.now = 1000
        self.error("skill_revoked", lambda: self.registry.resolve("clock", package=self.package))

    def test_local_audit_never_claims_external_transparency(self):
        self.install()
        result = self.registry.verify_local_audit()
        self.assertFalse(result["external_witness_verified"])
        with self.registry.storage.transaction() as db:
            db.execute("UPDATE signed_skill_events SET target='tampered'")
        self.error("skill_local_audit_invalid", self.registry.verify_local_audit)

    def test_atomic_install_audit_failure_rolls_back(self):
        with self.registry.storage.transaction() as db:
            db.execute("CREATE TRIGGER stop_insert BEFORE INSERT ON signed_skill_installed BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.install()
        self.assertEqual(self.registry.verify_local_audit()["events"], 0)
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_revocation_during_verification_blocks_install(self):
        other = self.open()
        original = self.registry._verify
        def revoke(*args):
            result = original(*args)
            other.revoke("key", "publisher-v1")
            return result
        with patch.object(self.registry, "_verify", side_effect=revoke):
            self.error("skill_revoked", self.install)
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_revocation_during_resolve_blocks_return(self):
        self.install()
        other = self.open()
        original = self.registry._verify
        def revoke(*args):
            result = original(*args)
            other.revoke("skill", "clock")
            return result
        with patch.object(self.registry, "_verify", side_effect=revoke):
            self.error("skill_revoked", lambda: self.registry.resolve("clock", package=self.package))

    def test_replacement_during_resolve_blocks_old_result(self):
        self.install()
        other = self.open()
        original = self.registry._verify
        def replace(*args):
            result = original(*args)
            self.install(dict(self.body, version="2.0.0"), registry=other)
            return result
        with patch.object(self.registry, "_verify", side_effect=replace):
            self.error("skill_admission_changed", lambda: self.registry.resolve("clock", package=self.package))

    def test_expiry_between_verification_and_transaction_denies(self):
        original = self.registry._verify
        def late(*args):
            result = original(*args)
            self.now = 1500
            return result
        with patch.object(self.registry, "_verify", side_effect=late):
            with self.assertRaises(SignedSkillError):
                self.install()
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_expiry_at_final_transaction_check_rolls_back(self):
        original = self.registry._event
        def late(*args):
            result = original(*args)
            self.now = 1400
            return result
        with patch.object(self.registry, "_event", side_effect=late):
            self.error("skill_admission_expired", self.install)
        self.assertEqual(self.count("signed_skill_installed"), 0)
        self.assertEqual(self.registry.verify_local_audit()["events"], 0)

    def test_cross_connection_wait_does_not_refresh_consent(self):
        other = self.open()
        verified = threading.Event()
        errors = []
        original = self.registry._verify
        def observe(*args):
            result = original(*args)
            verified.set()
            return result
        def worker():
            try:
                self.install()
            except Exception as error:
                errors.append(error)
        with patch.object(self.registry, "_verify", side_effect=observe):
            with other.storage.transaction():
                thread = threading.Thread(target=worker)
                thread.start()
                self.assertTrue(verified.wait(2))
                self.now = 1400
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], SignedSkillError)
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_missing_dependency_is_denied(self):
        body = dict(self.body, dependencies=[{"skill_id": "dep", "version": "1.0.0", "manifest_sha256": "a" * 64}])
        self.error("skill_dependency_unavailable", lambda: self.install(body))

    def test_exact_dependency_and_transitive_revocation(self):
        dep = dict(self.body, skill_id="dep")
        self.install(dep)
        parent = dict(self.body, dependencies=[{"skill_id": "dep", "version": "1.0.0", "manifest_sha256": sha256(canonical(dep))}])
        self.install(parent)
        self.registry.resolve("clock", package=self.package)
        self.open().revoke("skill", "dep")
        self.error("skill_revoked", lambda: self.registry.resolve("clock", package=self.package))

    def test_dependency_upgrade_invalidates_old_binding(self):
        dep = dict(self.body, skill_id="dep")
        self.install(dep)
        parent = dict(self.body, dependencies=[{"skill_id": "dep", "version": "1.0.0", "manifest_sha256": sha256(canonical(dep))}])
        self.install(parent)
        self.install(dict(dep, version="2.0.0"))
        self.error("skill_dependency_unavailable", lambda: self.registry.resolve("clock", package=self.package))

    def test_dependency_cannot_outlive_consent(self):
        dep = dict(self.body, skill_id="dep")
        self.install(dep, consent=InstallConsent("user", sha256(canonical(dep)), 1001))
        parent = dict(self.body, dependencies=[{"skill_id": "dep", "version": "1.0.0", "manifest_sha256": sha256(canonical(dep))}])
        self.install(parent)
        self.now = 1001
        self.error("skill_dependency_unavailable", lambda: self.registry.resolve("clock", package=self.package))

    def test_self_dependency_rejected(self):
        body = dict(self.body, dependencies=[{"skill_id": "clock", "version": "1.0.0", "manifest_sha256": "a" * 64}])
        self.error("skill_dependency_invalid", lambda: self.install(body))

    def test_capacity_never_removes_old_revocations(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = SignedSkillRegistry(str(Path(tmp) / "small.sqlite"), subject="user", keys=self.keys,
                allowed_capabilities=frozenset({"display.text"}), allowed_domains=frozenset(), clock=lambda: self.now, maximum_entries=1)
            try:
                self.install(registry=r)
                self.error("skill_installation_capacity_exhausted", lambda: self.install(dict(self.body, version="2.0.0"), registry=r))
                r.revoke("skill", "unknown")
                self.assertEqual(r.revoke("skill", "clock")["scope"], "registry")
                self.error("skill_registry_suspended", lambda: r.resolve("clock", package=self.package))
                self.assertEqual(r.verify_local_audit()["events"], 3)
            finally:
                r.close()

    def test_schema_drift_fails_closed(self):
        with self.registry.storage.transaction() as db:
            db.execute("UPDATE hepta_component_schema SET version=2 WHERE component='signed_skills'")
        with self.assertRaisesRegex(ValueError, "migration_required"):
            self.open()
        with self.registry.storage.transaction() as db:
            db.execute("DELETE FROM hepta_component_schema WHERE component='signed_skills'")
        self.error("skill_unmarked_schema_rejected", self.open)

    def test_clock_rollback_detected_after_reopen(self):
        self.install()
        other = self.open()
        self.now = 999
        self.error("skill_clock_rollback", lambda: other.resolve("clock", package=self.package))

    def test_verifier_ignores_environment_program_injection(self):
        document = canonical(self.body)
        signature = self.signature(document)
        with patch.dict(os.environ, {"PATH": "/nonexistent", "OPENSSL_CONF": "/nonexistent/evil"}):
            self.install(signature=signature)

    def test_verifier_inputs_use_sealed_anonymous_descriptors(self):
        document = canonical(self.body)
        signature = self.signature(document)
        original = subprocess.run
        def inspect(command, **kwargs):
            if "-verify" in command:
                import fcntl
                self.assertEqual(command[0], "/usr/bin/openssl")
                self.assertEqual(len(kwargs["pass_fds"]), 3)
                for fd in kwargs["pass_fds"]:
                    self.assertTrue(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & fcntl.F_SEAL_WRITE)
                self.assertNotIn("LD_PRELOAD", kwargs["env"])
            return original(command, **kwargs)
        with patch.object(subprocess, "run", side_effect=inspect):
            self.install(signature=signature)


    def test_actual_process_exit_retains_revocation(self):
        self.install()
        script = """
import json,sys,os
from services.skills.signed_package import PublisherKey
from services.skills.signed_registry import SignedSkillRegistry
x=json.loads(sys.stdin.buffer.read())
r=SignedSkillRegistry(sys.argv[1],subject='user',keys={'publisher-v1':PublisherKey('publisher',bytes.fromhex(x['public']),900,2000)},allowed_capabilities=frozenset({'display.text','memory.read'}),allowed_domains=frozenset({'service.example'}),clock=lambda:1000)
r.revoke('publisher','publisher')
os._exit(23)
"""
        run = subprocess.run([sys.executable, "-c", script, self.path],
            input=json.dumps({"public": self.public.hex()}).encode(), capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 23, run.stderr.decode())
        self.error("skill_revoked", lambda: self.open().resolve("clock", package=self.package))

    def test_actual_process_exit_rolls_back_prepared_install(self):
        document = canonical(self.body)
        script = """
import json,sys,os
from services.skills.signed_package import PublisherKey,sha256
from services.skills.signed_registry import SignedSkillRegistry,InstallConsent
x=json.loads(sys.stdin.buffer.read())
r=SignedSkillRegistry(sys.argv[1],subject='user',keys={'publisher-v1':PublisherKey('publisher',bytes.fromhex(x['public']),900,2000)},allowed_capabilities=frozenset({'display.text','memory.read'}),allowed_domains=frozenset({'service.example'}),clock=lambda:1000)
original=r._event
def stop(*args):
    original(*args)
    os._exit(24)
r._event=stop
document=bytes.fromhex(x['document'])
r.install(document,signature=bytes.fromhex(x['signature']),package=bytes.fromhex(x['package']),consent=InstallConsent('user',sha256(document),1400))
"""
        run = subprocess.run([sys.executable, "-c", script, self.path], input=json.dumps({
            "public": self.public.hex(), "document": document.hex(), "signature": self.signature(document).hex(),
            "package": self.package.hex()}).encode(), capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 24, run.stderr.decode())
        self.assertEqual(self.count("signed_skill_installed"), 0)
        self.assertEqual(self.open().verify_local_audit()["events"], 0)

    def test_worker_saturation_or_timeout_cannot_commit_admission(self):
        from services.control_plane.bounded_calls import CallOutcome
        for state in ("not_started", "timeout", "error"):
            with patch.object(self.registry._calls, "run", return_value=CallOutcome(state)):
                self.error("skill_package_verification_failed", self.install)
        self.assertEqual(self.count("signed_skill_installed"), 0)

    def test_missing_file_entrypoint_and_oversized_document_rejected(self):
        self.error("skill_file_inventory_invalid", lambda: parse_manifest(canonical(dict(self.body, entrypoint="other.py"))))
        self.error("skill_manifest_size_invalid", lambda: parse_manifest(b"x" * 32769))
        self.error("skill_manifest_array_invalid", lambda: parse_manifest(canonical(dict(self.body, files=self.body["files"] * 129))))

    def test_archive_crc_corruption_rejected_with_correct_whole_package_hash(self):
        corrupted = bytearray(self.package)
        corrupted[30 + len("main.py")] ^= 1
        raw = bytes(corrupted)
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_duplicate_local_archive_names_rejected(self):
        import warnings
        buffer = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(buffer, "w") as z:
                z.writestr("main.py", b"first")
                z.writestr("main.py", b"second")
        raw = buffer.getvalue()
        self.error("skill_package_verification_failed", lambda: self.install(dict(self.body, package_sha256=sha256(raw)), package=raw))

    def test_publisher_cannot_take_over_installed_skill(self):
        self.install()
        private = subprocess.run(["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER"],
            capture_output=True, check=True, timeout=5).stdout
        public = subprocess.run(["/usr/bin/openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
            input=private, capture_output=True, check=True, timeout=5).stdout
        other = self.open(keys={**self.keys, "new-key": PublisherKey("other", public, 900, 2000)})
        changed = dict(self.body, publisher="other", key_id="new-key", version="2.0.0")
        with patch.object(self, "private", private):
            signature = self.signature(canonical(changed))
        self.error("skill_publisher_replacement_forbidden", lambda: self.install(changed, registry=other, signature=signature))


if __name__ == "__main__":
    unittest.main()
