from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/validate_external_evidence.py"
SPEC = importlib.util.spec_from_file_location("validate_external_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
external_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(external_evidence)

FIXED_NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
COMMIT = "1" * 40
TREE = "2" * 40


class ExternalEvidenceValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact_root = self.root / "artifacts"
        self.artifact_root.mkdir()
        self.contract = json.loads(
            (ROOT / "contracts/external-evidence-envelope-v1.json").read_text(
                encoding="utf-8"
            )
        )

    def _artifact(self, gap_id: str, *, synthetic: bool = False) -> dict[str, object]:
        relative = Path(gap_id) / "report.json"
        path = self.artifact_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"gap_id": gap_id, "result": "pass", "fixture": True},
            sort_keys=True,
        ).encode("utf-8")
        path.write_bytes(payload)
        return {
            "artifact_id": f"{gap_id.lower()}-report",
            "uri": f"artifact://{relative.as_posix()}",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "media_type": "application/json",
            "issued_at": "2026-09-01T12:00:00Z",
            "expires_at": None,
            "contains_secrets": False,
            "synthetic": synthetic,
            "signature_uri": None,
            "signature_sha256": None,
        }

    def _submission(self, gap_id: str, *, synthetic: bool = False) -> dict[str, object]:
        authority_class = self.contract["authority_classes"][gap_id][0]
        claims = {
            name: True for name in self.contract["required_claims"][gap_id]
        }
        level = {
            "HG-0012": "E7",
            "HG-0016": "UPSTREAM",
            "HG-0017": "ADMIN",
        }.get(gap_id, "E6" if gap_id in {"HG-0011", "HG-0044"} else "E5")
        return {
            "gap_id": gap_id,
            "evidence_level": level,
            "issuer": {
                "identity": f"issuer-{gap_id.lower()}",
                "organization": f"authority-{gap_id.lower()}",
                "authority_class": authority_class,
                "key_id": f"kid:{gap_id.lower()}:1",
                "contact": None,
            },
            "environment": {
                "fixture": True,
                "candidate": COMMIT,
            },
            "subjects": [f"subject:{gap_id}"],
            "claims": claims,
            "artifacts": [self._artifact(gap_id, synthetic=synthetic)],
            "result": "pass",
            "limitations": ["Synthetic unit-test envelope; not production evidence."],
            "notes": None,
        }

    def _bundle(self, gap_ids: list[str]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "contract_id": "hepta-external-evidence-envelope-v1",
            "candidate": {
                "repository": "TrillionniumFoundation/hepta-glasses",
                "source_commit": COMMIT,
                "source_tree": TREE,
                "contracts_revision": "2026-09-01-g8",
                "release_id": None,
                "binary_digests": [],
                "collected_at": "2026-09-01T12:00:00Z",
            },
            "submissions": [self._submission(gap_id) for gap_id in gap_ids],
            "acceptance": {
                "state": "incomplete",
                "reviewed_at": None,
                "reviewers": [],
                "bundle_digest": None,
                "decision_reference": None,
                "limitations": [],
            },
        }

    def _write_bundle(self, bundle: dict[str, object], name: str = "bundle.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
        return path

    def _validate(
        self,
        bundle: dict[str, object],
        *,
        complete: bool = False,
        accepted: bool = False,
    ) -> dict[str, object]:
        return external_evidence.validate_bundle(
            self._write_bundle(bundle),
            artifact_root=self.artifact_root,
            expected_commit=COMMIT,
            expected_tree=TREE,
            require_complete=complete,
            require_accepted=accepted,
            now=FIXED_NOW,
        )

    def test_partial_valid_submission_is_not_closure(self) -> None:
        bundle = self._bundle(["HG-0017"])
        result = self._validate(bundle)

        self.assertTrue(result["ok"])
        self.assertFalse(result["eligible_for_review"])
        self.assertFalse(result["all_authority_owned_gaps_closed"])
        self.assertIn("HG-0010", result["missing_gaps"])

    def test_complete_accepted_bundle_closes_all_authority_owned_rows(self) -> None:
        gap_ids = list(self.contract["allowed_gap_ids"])
        bundle = self._bundle(gap_ids)
        bundle["acceptance"] = {
            "state": "accepted",
            "reviewed_at": "2026-09-02T10:00:00Z",
            "reviewers": [
                {
                    "identity": "independent-final-reviewer",
                    "organization": "independent-assurance-lab",
                    "independent": True,
                    "decision": "approve",
                    "review_digest": "3" * 64,
                    "signature_uri": None,
                }
            ],
            "bundle_digest": None,
            "decision_reference": "review:fixture:accepted",
            "limitations": [],
        }
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )

        result = self._validate(bundle, complete=True, accepted=True)

        self.assertTrue(result["eligible_for_review"])
        self.assertTrue(result["all_authority_owned_gaps_closed"])
        self.assertEqual(result["missing_gaps"], [])
        self.assertEqual(result["artifact_count"], len(gap_ids))

    def test_physical_gap_rejects_synthetic_evidence(self) -> None:
        bundle = self._bundle(["HG-0010"])
        bundle["submissions"][0]["artifacts"] = [
            self._artifact("HG-0010-synthetic", synthetic=True)
        ]
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "requires physical evidence",
        ):
            self._validate(bundle)

    def test_wrong_authority_class_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0013"])
        bundle["submissions"][0]["issuer"]["authority_class"] = (
            "repository_administrator"
        )
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "cannot attest HG-0013",
        ):
            self._validate(bundle)

    def test_digest_mismatch_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0021"])
        bundle["submissions"][0]["artifacts"][0]["sha256"] = "4" * 64
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "digest mismatch",
        ):
            self._validate(bundle)

    def test_candidate_drift_is_rejected(self) -> None:
        bundle = self._bundle(["HG-0017"])
        bundle["candidate"]["source_commit"] = "5" * 40
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "!= expected",
        ):
            self._validate(bundle)

    def test_self_review_cannot_claim_independence(self) -> None:
        bundle = self._bundle(list(self.contract["allowed_gap_ids"]))
        issuer_identity = bundle["submissions"][0]["issuer"]["identity"]
        bundle["acceptance"] = {
            "state": "accepted",
            "reviewed_at": "2026-09-02T10:00:00Z",
            "reviewers": [
                {
                    "identity": issuer_identity,
                    "organization": "same-evidence-producer",
                    "independent": True,
                    "decision": "approve",
                    "review_digest": "6" * 64,
                    "signature_uri": None,
                }
            ],
            "bundle_digest": None,
            "decision_reference": "review:fixture:self",
            "limitations": [],
        }
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )
        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "claims independence but also issued evidence",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_committed_template_is_deliberately_non_attesting(self) -> None:
        template = json.loads(
            (
                ROOT
                / "evidence/templates/external-evidence-bundle.template.json"
            ).read_text(encoding="utf-8")
        )
        with self.assertRaises(external_evidence.EvidenceError):
            external_evidence.validate_bundle(
                self._write_bundle(template, "template.json"),
                artifact_root=self.artifact_root,
                expected_commit=None,
                expected_tree=None,
                require_complete=False,
                require_accepted=False,
                now=FIXED_NOW,
            )


if __name__ == "__main__":
    unittest.main()
