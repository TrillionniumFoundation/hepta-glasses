"""Source custody tests; mocked validation is not signed external evidence."""
from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import external_evidence
from tools.external_evidence import committed_snapshot as admission

PIN = "a" * 64
COMMIT, TREE = "1" * 40, "2" * 40


def accepted() -> dict:
    return {"contract_id": admission.CONTRACT_ID,
            "acceptance": {"state": "accepted"},
            "candidate": {"source_commit": COMMIT, "source_tree": TREE}}


def verdict() -> dict:
    return {"all_authority_owned_gaps_closed": True,
            "missing_gaps": [], "missing_issuer_authority_classes": {},
            "review_set_integrity": {"verified": True},
            "trust_registry": {"external_pin_verified": True}}


class CommittedSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name) / "evidence"
        self.bundle = self.base / "successors" / "opaque.payload"
        self.bundle.parent.mkdir(parents=True)
        self.bundle.write_text(json.dumps(accepted()), encoding="utf-8")
        (self.base / "trust-registry.json").write_text('{"fixture": true}', encoding="utf-8")
        (self.base / "artifacts").mkdir()
        (self.base / "artifacts" / "report.bin").write_bytes(b"fixture-original")
        (self.base / "keys").mkdir()
        (self.base / "keys" / "public.txt").write_text("fixture-public", encoding="utf-8")

    def test_private_copy_retains_exact_all_file_bytes_and_is_read_only(self):
        before = admission.capture_repository(self.base)
        with admission.repository_validation_snapshot(self.base) as snapshot:
            self.assertNotEqual(snapshot.root, self.base)
            self.assertEqual(snapshot.captured.accepted(), ("successors/opaque.payload",))
            self.assertEqual(snapshot.captured.files["artifacts/report.bin"], b"fixture-original")
            self.assertEqual(snapshot.custody_root("successors/opaque.payload"), snapshot.root)
            for name, payload in before.files.items():
                target = snapshot.root / name
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o222, 0)
            with self.assertRaises(TypeError):
                snapshot.captured.files["late"] = b"changed"
            temporary_root = snapshot.root
        self.assertFalse(temporary_root.exists())
        self.assertEqual(admission.capture_repository(self.base).identities, before.identities)

    def test_canonical_gate_passes_exact_pin_candidate_and_strict_options(self):
        def validate(path, **kwargs):
            self.assertNotEqual(path, self.bundle)
            self.assertEqual(path.read_bytes(), self.bundle.read_bytes())
            self.assertTrue(kwargs["require_complete"])
            self.assertTrue(kwargs["require_accepted"])
            self.assertEqual(kwargs["expected_commit"], COMMIT)
            self.assertEqual(kwargs["expected_tree"], TREE)
            self.assertEqual(kwargs["expected_trust_registry_sha256"], PIN)
            self.assertNotIn("now", kwargs)
            self.assertNotIn("openssl_binary", kwargs)
            self.assertEqual(kwargs["artifact_root"].parent, kwargs["trust_registry_path"].parent)
            self.assertNotEqual(kwargs["artifact_root"], self.base / "artifacts")
            return verdict()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=validate, create=True) as verifier:
            report = admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)
        self.assertEqual(verifier.call_count, 1)
        self.assertTrue(report["verified"])
        self.assertEqual(report["packages"][0]["path"], "successors/opaque.payload")

    def test_bundle_registry_artifact_and_key_replacement_at_validation_boundary_rejected(self):
        for relative in ("successors/opaque.payload", "trust-registry.json", "artifacts/report.bin", "keys/public.txt"):
            with self.subTest(relative=relative):
                target = self.base / relative
                original = target.read_bytes()
                def replace_and_validate(path, **kwargs):
                    replacement = target.with_name(target.name + ".next")
                    replacement.write_bytes(original)
                    os.replace(replacement, target)
                    # The validator still sees the original private object/bytes.
                    copied = path.parents[1] / relative
                    self.assertEqual(copied.read_bytes(), original)
                    return verdict()
                with mock.patch.object(external_evidence, "validate_bundle", side_effect=replace_and_validate, create=True):
                    with self.assertRaisesRegex(admission.AdmissionSnapshotError, "post-validation.*identity changed"):
                        admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_changed_bytes_never_enter_validator_via_original_paths(self):
        original = (self.base / "artifacts/report.bin").read_bytes()
        def replace_and_validate(path, **kwargs):
            (self.base / "artifacts/report.bin").write_bytes(b"replacement")
            self.assertEqual((kwargs["artifact_root"] / "report.bin").read_bytes(), original)
            return verdict()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=replace_and_validate, create=True):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "post-validation"):
                admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_entire_custody_directory_replacement_rejected_even_same_bytes(self):
        def replace_and_validate(path, **kwargs):
            retired = self.base.with_name("retired")
            self.base.rename(retired)
            shutil.copytree(retired, self.base)
            return verdict()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=replace_and_validate, create=True):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "post-validation"):
                admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_added_accepted_package_during_validation_is_not_silently_omitted(self):
        def add_package(path, **kwargs):
            (self.base / "late.payload").write_text(json.dumps(accepted()), encoding="utf-8")
            return verdict()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=add_package, create=True):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "post-validation"):
                admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_private_copy_mutation_cannot_return_success(self):
        def mutate_copy(path, **kwargs):
            path.chmod(0o600)
            path.write_text(json.dumps(accepted()), encoding="utf-8")
            return verdict()
        with mock.patch.object(external_evidence, "validate_bundle", side_effect=mutate_copy, create=True):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "private-post-validation"):
                admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_original_mutation_before_context_yield_is_rejected(self):
        original = admission.capture_repository
        changed = False
        def capture(base):
            nonlocal changed
            result = original(base)
            if Path(base) != self.base and not changed:
                changed = True
                self.bundle.write_text(json.dumps(accepted()) + "\n", encoding="utf-8")
            return result
        with mock.patch.object(admission, "capture_repository", side_effect=capture):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "pre-validation"):
                with admission.repository_validation_snapshot(self.base):
                    self.fail("changed source reached validation")

    def test_pin_required_before_authority_validation(self):
        for pin in (None, "", "a" * 63, "A" * 64, 0):
            with self.subTest(pin=pin):
                with mock.patch.object(external_evidence, "validate_bundle", create=True) as verifier:
                    with self.assertRaisesRegex(admission.AdmissionSnapshotError, "out-of-band"):
                        admission.validate_committed_packages(self.base, expected_trust_registry_sha256=pin)
                    verifier.assert_not_called()

    def test_missing_registry_or_artifact_directory_fails_closed(self):
        (self.base / "trust-registry.json").unlink()
        with self.assertRaisesRegex(admission.AdmissionSnapshotError, "trust registry"):
            admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)
        (self.base / "trust-registry.json").write_text("{}", encoding="utf-8")
        shutil.rmtree(self.base / "artifacts")
        with self.assertRaisesRegex(admission.AdmissionSnapshotError, "artifact directory"):
            admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_missing_or_incomplete_validator_verdict_not_accepted(self):
        for result in ({}, {**verdict(), "all_authority_owned_gaps_closed": False},
                       {**verdict(), "missing_gaps": ["HG-0010"]},
                       {**verdict(), "trust_registry": {"external_pin_verified": False}}):
            with self.subTest(result=result):
                with mock.patch.object(external_evidence, "validate_bundle", return_value=result, create=True):
                    with self.assertRaisesRegex(admission.AdmissionSnapshotError, "complete acceptance"):
                        admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)

    def test_linked_root_parent_and_leaf_fail_closed(self):
        alias = self.base.with_name("alias")
        alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(admission.AdmissionSnapshotError):
            admission.capture_repository(alias)
        with self.assertRaises(admission.AdmissionSnapshotError):
            admission.capture_repository(alias / "successors")
        (self.base / "linked").symlink_to(self.bundle)
        with self.assertRaisesRegex(admission.AdmissionSnapshotError, "links"):
            admission.capture_repository(self.base)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_file_to_fifo_race_cannot_block_or_be_accepted(self):
        original = admission._regular_bytes
        changed = False
        def raced(parent, name, initial):
            nonlocal changed
            if name == "report.bin" and not changed:
                target = self.base / "artifacts" / name
                target.unlink()
                os.mkfifo(target)
                changed = True
            return original(parent, name, initial)
        with mock.patch.object(admission, "_regular_bytes", side_effect=raced):
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "changed before"):
                admission.capture_repository(self.base)
        self.assertTrue(changed)

    def test_resource_bounds_fail_closed(self):
        for key, limit in (("MAX_FILE_BYTES", 1), ("MAX_TOTAL_BYTES", 1),
                           ("MAX_ENTRIES", 1), ("MAX_DEPTH", 0)):
            with self.subTest(bound=key), mock.patch.object(admission, key, limit):
                with self.assertRaises(admission.AdmissionSnapshotError):
                    admission.capture_repository(self.base)

    def test_no_accepted_package_needs_no_pin_or_verifier(self):
        self.bundle.unlink()
        with mock.patch.object(external_evidence, "validate_bundle", create=True) as verifier:
            report = admission.validate_committed_packages(self.base, expected_trust_registry_sha256=None)
        verifier.assert_not_called()
        self.assertEqual(report["packages"], [])
        self.assertTrue(report["verified"])

    def test_duplicate_keys_and_nonfinite_json_do_not_become_accepted(self):
        for payload in ('{"contract_id":"' + admission.CONTRACT_ID + '","acceptance":{"state":"accepted"},"acceptance":{}}',
                        '{"contract_id":"' + admission.CONTRACT_ID + '","acceptance":{"state":"accepted"},"n":NaN}'):
            self.bundle.write_text(payload, encoding="utf-8")
            self.assertEqual(admission.capture_repository(self.base).accepted(), ())

    def test_empty_or_malformed_candidate_rejected(self):
        for candidate in (None, {}, {"source_commit": "1", "source_tree": TREE}):
            document = accepted()
            document["candidate"] = candidate
            self.bundle.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(admission.AdmissionSnapshotError, "candidate"):
                admission.validate_committed_packages(self.base, expected_trust_registry_sha256=PIN)


if __name__ == "__main__":
    unittest.main()
