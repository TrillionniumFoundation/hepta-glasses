from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
G9_REVISION = "2026-09-02-g9-authenticated-1"
G9_GAPS = ("HG-0073", "HG-0074", "HG-0075")
G9_MODULES = ("external-evidence-authentication", "latest-head-ci-custody")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def load_object(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain an object")
    return value


class G9MetadataCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_object("docs/G9_STATE.json")
        self.modules = load_object("docs/G9_MODULES.json")
        self.gaps = load_object("docs/G9_GAP_LEDGER.json")
        self.contract = load_object("contracts/external-evidence-envelope-v1.json")
        self.g8_ledger = load_object("docs/GAP_LEDGER.yaml")

    def test_revision_and_authority_owned_gap_set_are_synchronized(self) -> None:
        self.assertEqual(self.state["plan_revision"], G9_REVISION)
        self.assertEqual(self.modules["plan_revision"], G9_REVISION)
        self.assertEqual(self.gaps["plan_revision"], G9_REVISION)
        self.assertEqual(self.contract["contract_revision"], G9_REVISION)

        expected = set(self.contract["allowed_gap_ids"])
        self.assertEqual(set(self.state["authority_owned"]["gap_ids"]), expected)
        self.assertEqual(set(self.gaps["inherited_authority_owned_gap_ids"]), expected)

        by_id = {item["id"]: item for item in self.g8_ledger["gaps"]}
        self.assertTrue(expected.issubset(by_id))
        for gap_id in expected:
            self.assertIn(
                by_id[gap_id]["status"],
                {"BLOCKED_EXTERNAL", "BLOCKED_ADMIN_SETTING", "BLOCKED_UPSTREAM"},
            )

    def test_g9_source_gaps_are_closed_with_existing_evidence(self) -> None:
        self.assertEqual(self.gaps["source_summary"]["repository_actionable_open"], 0)
        self.assertEqual(self.gaps["source_summary"]["closed_source"], len(G9_GAPS))
        entries = self.gaps["gaps"]
        self.assertEqual(tuple(item["id"] for item in entries), G9_GAPS)
        self.assertEqual(
            tuple(self.state["repository_actionable"]["closed_source"]),
            G9_GAPS,
        )
        for gap in entries:
            with self.subTest(gap=gap["id"]):
                self.assertEqual(gap["status"], "CLOSED_SOURCE")
                self.assertTrue(gap["close_criteria"].strip())
                for relative in gap["evidence"]:
                    self.assertTrue((ROOT / relative).is_file(), relative)

    def test_g9_modules_have_source_doc_test_contract_coverage(self) -> None:
        entries = self.modules["modules"]
        self.assertEqual(tuple(item["id"] for item in entries), G9_MODULES)
        for module in entries:
            with self.subTest(module=module["id"]):
                for field in (
                    "source_roots",
                    "documentation",
                    "tests",
                    "contracts",
                    "external_gates",
                ):
                    self.assertTrue(module[field], f"{module['id']}.{field}")
                for relative in module["source_roots"]:
                    self.assertTrue((ROOT / relative).exists(), relative)
                for field in ("documentation", "tests", "contracts"):
                    for relative in module[field]:
                        self.assertTrue((ROOT / relative).is_file(), relative)

    def test_filesystem_custody_gap_is_registered_end_to_end(self) -> None:
        gaps = {item["id"]: item for item in self.gaps["gaps"]}
        custody = gaps["HG-0075"]
        required_evidence = {
            "tools/external_evidence/snapshot_io.py",
            "tools/external_evidence/signing_io.py",
            "tools/external_evidence/signing.py",
            "tools/sign_external_evidence.py",
            "services/qualification/test_external_evidence_snapshot.py",
            "services/qualification/test_external_evidence_scoped_snapshot.py",
            "services/qualification/test_external_evidence_filesystem_hardening.py",
            "services/qualification/test_external_evidence_signing.py",
            "services/qualification/test_external_evidence_signer_custody.py",
            "docs/adr/ADR-0006-external-evidence-filesystem-custody.md",
            "docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md",
            "docs/development/G9_FILESYSTEM_CUSTODY_HARDENING.md",
            "evidence/external/README.md",
        }
        self.assertTrue(required_evidence.issubset(set(custody["evidence"])))
        self.assertIn("normalized lexical absolute path", custody["close_criteria"])
        self.assertIn("exclusive-create", custody["close_criteria"])
        self.assertIn("ordinary-directory replacement", custody["close_criteria"])
        self.assertIn("aggregate-bounded", custody["close_criteria"])
        self.assertIn("in-place authority-bundle mutation is rejected", custody["close_criteria"])

        modules = {item["id"]: item for item in self.modules["modules"]}
        evidence_module = modules["external-evidence-authentication"]
        for source in (
            "tools/external_evidence/snapshot_io.py",
            "tools/external_evidence/signing_io.py",
            "tools/external_evidence/signing.py",
        ):
            self.assertIn(source, evidence_module["source_roots"])
        for document in (
            "docs/adr/ADR-0006-external-evidence-filesystem-custody.md",
            "docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md",
            "docs/development/G9_FILESYSTEM_CUSTODY_HARDENING.md",
        ):
            self.assertIn(document, evidence_module["documentation"])
        for test in (
            "services/qualification/test_external_evidence_snapshot.py",
            "services/qualification/test_external_evidence_scoped_snapshot.py",
            "services/qualification/test_external_evidence_filesystem_hardening.py",
            "services/qualification/test_external_evidence_signing.py",
            "services/qualification/test_external_evidence_signer_custody.py",
        ):
            self.assertIn(test, evidence_module["tests"])

        profile = self.state["repository_actionable"]["filesystem_custody_profile"]
        self.assertTrue(profile["canonical_scoped_uris"])
        self.assertTrue(profile["ancestor_and_file_object_identity_bound"])
        self.assertEqual(profile["aggregate_snapshot_limit_bytes"], 512 * 1024 * 1024)
        self.assertTrue(profile["public_key_spki_uses_pinned_bytes"])
        self.assertTrue(profile["private_key_type_check_and_sign_use_one_snapshot"])
        self.assertFalse(profile["in_place_authority_bundle_update_supported"])
        self.assertTrue(profile["immutable_bundle_successor_required"])
        self.assertEqual(
            profile["normative_adr"],
            "docs/adr/ADR-0007-evidence-object-identity-and-bounded-custody.md",
        )

    def test_docs_index_registers_g9_machine_truth(self) -> None:
        index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for name in (
            "G9_STATE.json",
            "G9_MODULES.json",
            "G9_GAP_LEDGER.json",
            "G9_FILESYSTEM_CUSTODY_HARDENING.md",
            "ADR-0004-external-evidence-authentication.md",
            "ADR-0005-latest-head-ci-concurrency.md",
            "ADR-0006-external-evidence-filesystem-custody.md",
            "ADR-0007-evidence-object-identity-and-bounded-custody.md",
        ):
            self.assertIn(name, index)

    def test_g9_custody_contains_no_private_key_material(self) -> None:
        roots = [
            ROOT / "contracts" / "external-evidence-envelope-v1.json",
            ROOT / "schemas" / "external-evidence-envelope.schema.json",
            ROOT / "schemas" / "external-authority-trust-registry.schema.json",
            ROOT / "tools" / "external_evidence",
            ROOT / "tools" / "validate_external_evidence.py",
            ROOT / "tools" / "sign_external_evidence.py",
            ROOT / "evidence" / "external",
            ROOT / "evidence" / "templates" / "external-evidence-bundle.template.json",
            ROOT / "evidence" / "templates" / "external-authority-trust-registry.template.json",
        ]
        files: list[Path] = []
        for root in roots:
            files.extend(root.rglob("*") if root.is_dir() else [root])
        for path in files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(PRIVATE_KEY_PATTERN.search(text), str(path))

    def test_claim_ceiling_remains_external(self) -> None:
        self.assertEqual(self.state["repository_actionable"]["open"], 0)
        self.assertEqual(
            self.state["authority_owned"]["inherited_blocked_count"],
            len(self.contract["allowed_gap_ids"]),
        )
        self.assertIn("E5-E7", self.state["claim_ceiling"])
        self.assertIn("externally pinned", self.state["authority_owned"]["closure_rule"])
        self.assertIn(
            "exact source SHA verified inside every job",
            self.state["source_authority"]["workflow_concurrency_rule"],
        )


if __name__ == "__main__":
    unittest.main()
