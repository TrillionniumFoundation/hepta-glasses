from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.external_evidence import (
    EvidenceError,
    canonical_review_statement,
    canonical_submission_statement,
    evidence_set_digest,
)
from tools.external_evidence import core

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/external-evidence-envelope-v1.json"


class ExternalEvidenceContractBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.revision = self.contract["contract_revision"]
        self.bundle = {
            "contract_id": self.contract["contract_id"],
            "trust_registry": {
                "registry_id": "fixture-registry",
                "sha256": "a" * 64,
            },
            "candidate": {
                "repository": "TrillionniumFoundation/hepta-glasses",
                "source_commit": "1" * 40,
                "source_tree": "2" * 40,
                "contracts_revision": "2026-09-01-g8",
                "collected_at": "2026-09-02T00:00:00Z",
            },
            "submissions": [],
        }
        self.submission = {
            "gap_id": "HG-0017",
            "evidence_level": "ADMIN",
            "issuer": {
                "identity": "repository-admin",
                "organization": "TrillionniumFoundation",
                "authority_class": "repository_administrator",
                "key_id": "repository-admin-key",
            },
            "environment": {"branch": "main"},
            "subjects": ["main"],
            "claims": {"seven_checks_required": True},
            "artifacts": [],
            "result": "pass",
            "limitations": [],
            "attestation": {"signed_at": "2026-09-02T00:10:00Z"},
        }
        self.reviewer = {
            "identity": "governance-reviewer",
            "organization": "independent-governance",
            "authority_class": "repository_governance_reviewer",
            "key_id": "governance-reviewer-key",
            "decision": "approve",
            "reviewed_gap_ids": ["HG-0017"],
            "review_uri": "artifact://reviews/governance.json",
            "review_sha256": "b" * 64,
            "signed_at": "2026-09-02T00:20:00Z",
            "statement_digest": "0" * 64,
            "signature_uri": "artifact://signatures/governance.sig",
            "signature_sha256": "0" * 64,
        }

    def _write_contract(self, value: dict[str, object]) -> Path:
        temporary = tempfile.NamedTemporaryFile(
            prefix="hepta-contract-binding-",
            suffix=".json",
            delete=False,
        )
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        with temporary:
            temporary.write(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        return Path(temporary.name)

    def test_same_revision_semantic_drift_changes_every_signature_preimage(self) -> None:
        original_submission = canonical_submission_statement(
            self.bundle,
            self.submission,
            contract_revision=self.revision,
        )
        original_review = canonical_review_statement(
            self.bundle,
            self.reviewer,
            contract_revision=self.revision,
        )
        original_set = evidence_set_digest(self.bundle)

        changed_contract = json.loads(json.dumps(self.contract))
        changed_contract["closure_rule"] = (
            str(changed_contract["closure_rule"]) + " unauthorized semantic drift"
        )
        changed_path = self._write_contract(changed_contract)
        with mock.patch.object(core, "CONTRACT_PATH", changed_path):
            changed_submission = canonical_submission_statement(
                self.bundle,
                self.submission,
                contract_revision=self.revision,
            )
            changed_review = canonical_review_statement(
                self.bundle,
                self.reviewer,
                contract_revision=self.revision,
            )
            changed_set = evidence_set_digest(self.bundle)

        self.assertNotEqual(original_submission, changed_submission)
        self.assertNotEqual(original_review, changed_review)
        self.assertNotEqual(original_set, changed_set)
        self.assertNotEqual(
            hashlib.sha256(original_submission).hexdigest(),
            hashlib.sha256(changed_submission).hexdigest(),
        )

    def test_revision_label_cannot_disagree_with_current_contract_bytes(self) -> None:
        changed_contract = json.loads(json.dumps(self.contract))
        changed_contract["contract_revision"] = "same-label-bypass-attempt"
        changed_path = self._write_contract(changed_contract)
        with mock.patch.object(core, "CONTRACT_PATH", changed_path):
            with self.assertRaisesRegex(
                EvidenceError,
                "contract revision differs from the current contract bytes",
            ):
                canonical_submission_statement(
                    self.bundle,
                    self.submission,
                    contract_revision=self.revision,
                )


if __name__ == "__main__":
    unittest.main()
