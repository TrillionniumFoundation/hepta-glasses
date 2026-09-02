from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
G10_REVISION = "2026-09-02-g10-quorum-1"
G10_GAPS = (
    "HG-0076",
    "HG-0077",
    "HG-0078",
    "HG-0079",
    "HG-0080",
    "HG-0081",
)
G10_MODULES = ("authority-quorum-review-integrity",)


def load_object(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{relative} must contain an object")
    return value


class G10MetadataCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_object("docs/G10_STATE.json")
        self.modules = load_object("docs/G10_MODULES.json")
        self.gaps = load_object("docs/G10_GAP_LEDGER.json")
        self.g9_state = load_object("docs/G9_STATE.json")
        self.g9_gaps = load_object("docs/G9_GAP_LEDGER.json")
        self.contract = load_object(
            "contracts/external-evidence-envelope-v1.json"
        )

    def test_revision_and_inherited_gap_set_are_synchronized(self) -> None:
        self.assertEqual(self.state["plan_revision"], G10_REVISION)
        self.assertEqual(self.modules["plan_revision"], G10_REVISION)
        self.assertEqual(self.gaps["plan_revision"], G10_REVISION)
        self.assertEqual(self.contract["contract_revision"], G10_REVISION)
        self.assertEqual(
            self.contract["extends_contract_revision"],
            self.g9_state["plan_revision"],
        )
        self.assertEqual(
            self.state["extends_plan_revision"],
            self.g9_state["plan_revision"],
        )
        expected = set(self.contract["allowed_gap_ids"])
        self.assertEqual(
            set(self.state["authority_owned"]["gap_ids"]),
            expected,
        )
        self.assertEqual(
            set(self.gaps["inherited_authority_owned_gap_ids"]),
            expected,
        )

    def test_source_gaps_are_closed_with_existing_evidence(self) -> None:
        self.assertEqual(
            self.gaps["source_summary"]["repository_actionable_open"],
            0,
        )
        self.assertEqual(
            self.gaps["source_summary"]["closed_source"],
            len(G10_GAPS),
        )
        entries = self.gaps["gaps"]
        self.assertEqual(tuple(item["id"] for item in entries), G10_GAPS)
        self.assertEqual(
            tuple(self.state["repository_actionable"]["closed_source"]),
            G10_GAPS,
        )
        for gap in entries:
            with self.subTest(gap=gap["id"]):
                self.assertEqual(gap["status"], "CLOSED_SOURCE")
                self.assertTrue(gap["close_criteria"].strip())
                for relative in gap["evidence"]:
                    self.assertTrue((ROOT / relative).is_file(), relative)

    def test_module_has_source_doc_test_contract_coverage(self) -> None:
        entries = self.modules["modules"]
        self.assertEqual(tuple(item["id"] for item in entries), G10_MODULES)
        for module in entries:
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

    def test_complete_validator_is_installed_for_every_package_caller(
        self,
    ) -> None:
        package_init = (
            ROOT / "tools/external_evidence/__init__.py"
        ).read_text(encoding="utf-8")
        policy = (
            ROOT / "tools/external_evidence/complete_closure.py"
        ).read_text(encoding="utf-8")
        seat_policy = (
            ROOT / "tools/external_evidence/authority_seat_policy.py"
        ).read_text(encoding="utf-8")
        admission = (
            ROOT / "tools/external_evidence/repository_admission.py"
        ).read_text(encoding="utf-8")
        runtime_policy = (
            ROOT / "tools/external_evidence/runtime_policy.py"
        ).read_text(encoding="utf-8")
        semantic_binding = (
            ROOT / "tools/external_evidence/semantic_binding.py"
        ).read_text(encoding="utf-8")
        wrapper = (
            ROOT / "tools/validate_external_evidence.py"
        ).read_text(encoding="utf-8")
        cli = (ROOT / "tools/external_evidence/cli.py").read_text(
            encoding="utf-8"
        )
        repository_test = (
            ROOT / "services/qualification/test_external_evidence_repository.py"
        ).read_text(encoding="utf-8")
        repository_admission_test = (
            ROOT
            / "services/qualification/test_external_evidence_repository_admission.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_install_runtime_policy", package_init)
        self.assertIn("_install_semantic_binding", package_init)
        self.assertIn("_install_global_authority_seat_policy", package_init)
        self.assertIn("missing_issuer_authority_classes", policy)
        self.assertIn("issuer_claim_scopes", policy)
        self.assertIn("review_set_integrity", policy)
        self.assertIn(
            "one key cannot satisfy multiple authority seats",
            policy,
        )
        self.assertIn("spans authority classes", seat_policy)
        self.assertIn("one pinned key cannot occupy different", seat_policy)
        self.assertIn("_open_absolute_directory_nofollow", admission)
        self.assertIn("name no longer identifies the opened file", admission)
        self.assertIn("committed evidence directory changed", admission)
        self.assertIn(
            "caller-supplied validation time is prohibited",
            runtime_policy,
        )
        self.assertIn(
            "custom OpenSSL executable selection is prohibited",
            runtime_policy,
        )
        self.assertNotIn("--openssl-binary", cli)
        self.assertIn("contract_sha256", semantic_binding)
        self.assertIn("canonical_digest(contract)", semantic_binding)
        self.assertIn("review_set_digest", wrapper)
        self.assertIn("acceptance_context_digest", wrapper)
        self.assertIn("base.rglob", repository_test)
        self.assertIn("os.O_NOFOLLOW", repository_test)
        self.assertIn("acceptance.get(\"state\") == \"accepted\"", repository_test)
        self.assertIn("discover_accepted_envelopes", repository_admission_test)
        self.assertIn("directory_replacement_between_stat_and_open", repository_admission_test)

    def test_contract_policy_and_claim_partition_are_exact(self) -> None:
        profile = self.contract["complete_closure_profile"]
        self.assertEqual(
            profile["policy_id"],
            "hepta-external-complete-closure-v1",
        )
        self.assertEqual(profile["policy_revision"], G10_REVISION)
        self.assertEqual(
            profile["issuer_authority_mode"],
            "all_named_classes",
        )
        self.assertEqual(
            profile["issuer_claim_mode"],
            "exact_class_scoped_claims",
        )
        scopes = self.contract["required_claims_by_authority_class"]
        for gap_id in self.contract["allowed_gap_ids"]:
            self.assertEqual(
                set(scopes[gap_id]),
                set(self.contract["authority_classes"][gap_id]),
            )
            flattened = [
                claim
                for authority_class in self.contract["authority_classes"][gap_id]
                for claim in scopes[gap_id][authority_class]
            ]
            self.assertEqual(len(flattened), len(set(flattened)))
            self.assertEqual(
                set(flattened),
                set(self.contract["required_claims"][gap_id]),
            )

    def test_docs_index_registers_g10_machine_truth(self) -> None:
        index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for name in (
            "G10_STATE.json",
            "G10_MODULES.json",
            "G10_GAP_LEDGER.json",
            "G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md",
            "G10_AUTHORITY_SEAT_AND_REPOSITORY_ADMISSION_HARDENING.md",
            "G10_TRUSTED_VERIFIER_AND_CONTRACT_BINDING.md",
            "ADR-0008-authority-quorum-and-review-set-integrity.md",
            "ADR-0009-trusted-verifier-and-contract-content-binding.md",
        ):
            self.assertIn(name, index)

    def test_g10_does_not_promote_external_rows(self) -> None:
        self.assertEqual(self.state["repository_actionable"]["open"], 0)
        self.assertEqual(
            self.state["authority_owned"]["inherited_blocked_count"],
            len(self.contract["allowed_gap_ids"]),
        )
        self.assertIn("cannot manufacture", self.state["claim_ceiling"])
        self.assertIn("one key ID", self.state["authority_owned"]["closure_rule"])
        self.assertIn("descriptor-anchored", self.state["claim_ceiling"])
        g9_external = set(
            self.g9_gaps["inherited_authority_owned_gap_ids"]
        )
        self.assertEqual(
            set(self.gaps["inherited_authority_owned_gap_ids"]),
            g9_external,
        )


if __name__ == "__main__":
    unittest.main()
