from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/validate_external_evidence.py"
SPEC = importlib.util.spec_from_file_location("validate_external_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
external_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = external_evidence
SPEC.loader.exec_module(external_evidence)

FIXED_NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
COMMIT = "1" * 40
TREE = "2" * 40


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for Ed25519 tests")
class ExternalEvidenceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact_root = self.root / "artifacts"
        self.artifact_root.mkdir()
        self.key_root = self.root / "keys"
        self.key_root.mkdir()
        self.contract = json.loads(
            (ROOT / "contracts/external-evidence-envelope-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.private_keys: dict[str, Path] = {}
        self.registry_document = self._build_registry()
        self.registry_path = self.root / "trust-registry.json"
        self.registry_digest = self._write_registry()

    def _run(self, *args: str) -> None:
        subprocess.run(
            ["openssl", *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _generate_key(self, name: str) -> tuple[Path, str]:
        private_key = self.key_root / f"{name}.private.pem"
        public_key = self.key_root / f"{name}.public.pem"
        self._run("genpkey", "-algorithm", "ED25519", "-out", str(private_key))
        self._run(
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        )
        self.private_keys[name] = private_key
        return public_key, hashlib.sha256(public_key.read_bytes()).hexdigest()

    def _key_record(
        self,
        *,
        name: str,
        key_id: str,
        identity: str,
        organization: str,
        usages: list[str],
        authority_classes: list[str],
        allowed_gap_ids: list[str],
    ) -> dict[str, object]:
        public_key, digest = self._generate_key(name)
        return {
            "key_id": key_id,
            "identity": identity,
            "organization": organization,
            "algorithm": "ed25519",
            "public_key_uri": f"key://keys/{public_key.name}",
            "public_key_sha256": digest,
            "usages": usages,
            "authority_classes": authority_classes,
            "allowed_gap_ids": allowed_gap_ids,
            "valid_from": "2026-08-01T00:00:00Z",
            "valid_until": "2027-09-01T00:00:00Z",
            "revoked_at": None,
        }

    def _build_registry(self) -> dict[str, object]:
        gaps = list(self.contract["allowed_gap_ids"])
        issuer_classes = sorted(
            {
                value
                for values in self.contract["authority_classes"].values()
                for value in values
            }
        )
        general_gaps = [
            gap for gap in gaps if gap not in {"HG-0011", "HG-0017", "HG-0044"}
        ]
        return {
            "schema_version": 1,
            "registry_id": "hepta-external-authority-trust-registry-v1",
            "registry_revision": "fixture-1",
            "issued_at": "2026-08-01T00:00:00Z",
            "expires_at": "2027-09-01T00:00:00Z",
            "keys": [
                self._key_record(
                    name="issuer",
                    key_id="issuer-key",
                    identity="fixture-evidence-authority",
                    organization="fixture-evidence-org",
                    usages=["evidence_issuer", "acceptance_reviewer"],
                    authority_classes=issuer_classes,
                    allowed_gap_ids=gaps,
                ),
                self._key_record(
                    name="release-reviewer",
                    key_id="release-reviewer-key",
                    identity="release-reviewer",
                    organization="release-review-board",
                    usages=["acceptance_reviewer"],
                    authority_classes=["release_acceptance_authority"],
                    allowed_gap_ids=general_gaps,
                ),
                self._key_record(
                    name="dissent-reviewer",
                    key_id="dissent-reviewer-key",
                    identity="dissent-reviewer",
                    organization="independent-dissent-board",
                    usages=["acceptance_reviewer"],
                    authority_classes=["release_acceptance_authority"],
                    allowed_gap_ids=general_gaps,
                ),
                self._key_record(
                    name="assurance-reviewer",
                    key_id="assurance-reviewer-key",
                    identity="assurance-reviewer",
                    organization="independent-assurance-lab",
                    usages=["acceptance_reviewer", "independent_reviewer"],
                    authority_classes=["independent_assurance"],
                    allowed_gap_ids=["HG-0011"],
                ),
                self._key_record(
                    name="governance-reviewer",
                    key_id="governance-reviewer-key",
                    identity="governance-reviewer",
                    organization="repository-governance-audit",
                    usages=["acceptance_reviewer"],
                    authority_classes=["repository_governance_reviewer"],
                    allowed_gap_ids=["HG-0017"],
                ),
                self._key_record(
                    name="code-reviewer",
                    key_id="code-reviewer-key",
                    identity="code-reviewer",
                    organization="independent-code-review",
                    usages=["acceptance_reviewer", "independent_reviewer"],
                    authority_classes=["independent_code_reviewer"],
                    allowed_gap_ids=["HG-0044"],
                ),
            ],
        }

    def _write_registry(self) -> str:
        payload = json.dumps(
            self.registry_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.registry_path.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    def _sign(self, key_name: str, message: bytes, relative: Path) -> dict[str, str]:
        message_path = self.root / "message.bin"
        message_path.write_bytes(message)
        signature_path = self.artifact_root / relative
        signature_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            "pkeyutl",
            "-sign",
            "-inkey",
            str(self.private_keys[key_name]),
            "-rawin",
            "-in",
            str(message_path),
            "-out",
            str(signature_path),
        )
        signature = signature_path.read_bytes()
        return {
            "signature_uri": f"artifact://{relative.as_posix()}",
            "signature_sha256": hashlib.sha256(signature).hexdigest(),
        }

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
            "issued_at": "2026-09-01T13:00:00Z",
            "expires_at": None,
            "contains_secrets": False,
            "synthetic": synthetic,
            "signature_uri": None,
            "signature_sha256": None,
        }

    def _level(self, gap_id: str) -> str:
        return {
            "HG-0012": "E7",
            "HG-0016": "UPSTREAM",
            "HG-0017": "ADMIN",
        }.get(gap_id, "E6" if gap_id in {"HG-0011", "HG-0044"} else "E5")

    def _claims_for(self, gap_id: str, authority_class: str) -> dict[str, bool]:
        scopes = self.contract["required_claims_by_authority_class"]
        return {name: True for name in scopes[gap_id][authority_class]}

    def _unsigned_submission(
        self,
        gap_id: str,
        *,
        synthetic: bool = False,
    ) -> dict[str, object]:
        authority_class = self.contract["authority_classes"][gap_id][0]
        return {
            "gap_id": gap_id,
            "evidence_level": self._level(gap_id),
            "issuer": {
                "identity": "fixture-evidence-authority",
                "organization": "fixture-evidence-org",
                "authority_class": authority_class,
                "key_id": "issuer-key",
                "contact": None,
            },
            "environment": {"fixture": True, "candidate": COMMIT},
            "subjects": [f"subject:{gap_id}"],
            "claims": self._claims_for(gap_id, authority_class),
            "artifacts": [self._artifact(gap_id, synthetic=synthetic)],
            "result": "pass",
            "limitations": ["Cryptographically signed unit-test fixture."],
            "notes": None,
        }

    def _base_bundle(self) -> dict[str, object]:
        return {
            "schema_version": self.contract["schema_version"],
            "contract_id": self.contract["contract_id"],
            "trust_registry": {
                "registry_id": self.registry_document["registry_id"],
                "sha256": self.registry_digest,
            },
            "candidate": {
                "repository": "TrillionniumFoundation/hepta-glasses",
                "source_commit": COMMIT,
                "source_tree": TREE,
                "contracts_revision": "2026-09-01-g8",
                "release_id": None,
                "binary_digests": [],
                "collected_at": "2026-09-01T12:00:00Z",
            },
            "submissions": [],
            "acceptance": {
                "state": "incomplete",
                "reviewed_at": None,
                "reviewers": [],
                "bundle_digest": None,
                "decision_reference": None,
                "limitations": [],
            },
        }

    def _sign_submission(
        self,
        bundle: dict[str, object],
        submission: dict[str, object],
        *,
        key_name: str,
        signature_name: str,
    ) -> dict[str, object]:
        submission["attestation"] = {
            "signed_at": "2026-09-01T14:00:00Z",
            "statement_digest": "0" * 64,
            "signature_uri": "artifact://placeholder",
            "signature_sha256": "0" * 64,
        }
        statement = external_evidence.canonical_submission_statement(
            bundle,
            submission,
            contract_revision=self.contract["contract_revision"],
        )
        signature = self._sign(
            key_name,
            statement,
            Path("signatures") / signature_name,
        )
        submission["attestation"] = {
            "signed_at": "2026-09-01T14:00:00Z",
            "statement_digest": hashlib.sha256(statement).hexdigest(),
            **signature,
        }
        return submission

    def _bundle(self, gap_ids: list[str]) -> dict[str, object]:
        bundle = self._base_bundle()
        bundle["submissions"] = [
            self._sign_submission(
                bundle,
                self._unsigned_submission(gap_id),
                key_name="issuer",
                signature_name=f"{gap_id}.issuer.sig",
            )
            for gap_id in gap_ids
        ]
        return bundle

    @staticmethod
    def _authority_key_name(authority_class: str) -> str:
        return f"issuer-{authority_class.replace('_', '-')}"

    def _ensure_complete_issuer_keys(self) -> None:
        existing = {
            item["key_id"]
            for item in self.registry_document["keys"]
            if isinstance(item, dict)
        }
        all_gaps = list(self.contract["allowed_gap_ids"])
        for authority_class in sorted(
            {
                value
                for values in self.contract["authority_classes"].values()
                for value in values
            }
        ):
            key_name = self._authority_key_name(authority_class)
            key_id = f"{key_name}-key"
            if key_id in existing:
                continue
            allowed = [
                gap
                for gap in all_gaps
                if authority_class in self.contract["authority_classes"][gap]
            ]
            self.registry_document["keys"].append(
                self._key_record(
                    name=key_name,
                    key_id=key_id,
                    identity=f"fixture-{authority_class}-authority",
                    organization=f"fixture-{authority_class}-org",
                    usages=["evidence_issuer"],
                    authority_classes=[authority_class],
                    allowed_gap_ids=allowed,
                )
            )
            existing.add(key_id)

    def _artifact_for_authority(
        self,
        gap_id: str,
        authority_class: str,
    ) -> dict[str, object]:
        relative = Path(gap_id) / authority_class / "report.json"
        path = self.artifact_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "gap_id": gap_id,
                "authority_class": authority_class,
                "result": "pass",
                "fixture": True,
            },
            sort_keys=True,
        ).encode("utf-8")
        path.write_bytes(payload)
        return {
            "artifact_id": f"{gap_id.lower()}-{authority_class}-report",
            "uri": f"artifact://{relative.as_posix()}",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "media_type": "application/json",
            "issued_at": "2026-09-01T13:00:00Z",
            "expires_at": None,
            "contains_secrets": False,
            "synthetic": False,
            "signature_uri": None,
            "signature_sha256": None,
        }

    def _unsigned_submission_for_authority(
        self,
        gap_id: str,
        authority_class: str,
    ) -> dict[str, object]:
        key_name = self._authority_key_name(authority_class)
        return {
            "gap_id": gap_id,
            "evidence_level": self._level(gap_id),
            "issuer": {
                "identity": f"fixture-{authority_class}-authority",
                "organization": f"fixture-{authority_class}-org",
                "authority_class": authority_class,
                "key_id": f"{key_name}-key",
                "contact": None,
            },
            "environment": {
                "fixture": True,
                "candidate": COMMIT,
                "authority_class": authority_class,
            },
            "subjects": [f"subject:{gap_id}:{authority_class}"],
            "claims": self._claims_for(gap_id, authority_class),
            "artifacts": [
                self._artifact_for_authority(gap_id, authority_class)
            ],
            "result": "pass",
            "limitations": [
                "Cryptographically signed multi-authority unit-test fixture."
            ],
            "notes": None,
        }

    def _complete_bundle(self, gap_ids: list[str]) -> dict[str, object]:
        self._ensure_complete_issuer_keys()
        self.registry_digest = self._write_registry()
        bundle = self._base_bundle()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        submissions = []
        for gap_id in gap_ids:
            for authority_class in self.contract["authority_classes"][gap_id]:
                key_name = self._authority_key_name(authority_class)
                submissions.append(
                    self._sign_submission(
                        bundle,
                        self._unsigned_submission_for_authority(
                            gap_id,
                            authority_class,
                        ),
                        key_name=key_name,
                        signature_name=(
                            f"{gap_id}.{authority_class}.issuer.sig"
                        ),
                    )
                )
        bundle["submissions"] = submissions
        return bundle

    def _reviewer(
        self,
        bundle: dict[str, object],
        *,
        key_name: str,
        key_id: str,
        identity: str,
        organization: str,
        authority_class: str,
        gaps: list[str],
    ) -> dict[str, object]:
        review_relative = Path("reviews") / f"{key_name}.json"
        review_path = self.artifact_root / review_relative
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_payload = json.dumps(
            {"reviewer": identity, "gaps": gaps, "decision": "approve"},
            sort_keys=True,
        ).encode("utf-8")
        review_path.write_bytes(review_payload)
        reviewer: dict[str, object] = {
            "identity": identity,
            "organization": organization,
            "authority_class": authority_class,
            "key_id": key_id,
            "decision": "approve",
            "reviewed_gap_ids": gaps,
            "review_uri": f"artifact://{review_relative.as_posix()}",
            "review_sha256": hashlib.sha256(review_payload).hexdigest(),
            "signed_at": "2026-09-02T09:00:00Z",
            "statement_digest": "0" * 64,
            "signature_uri": "artifact://placeholder",
            "signature_sha256": "0" * 64,
        }
        statement = external_evidence.canonical_review_statement(
            bundle,
            reviewer,
            contract_revision=self.contract["contract_revision"],
        )
        signature = self._sign(
            key_name,
            statement,
            Path("signatures") / f"{key_name}.review.sig",
        )
        reviewer["statement_digest"] = hashlib.sha256(statement).hexdigest()
        reviewer.update(signature)
        return reviewer

    def _reviewer_shell(
        self,
        *,
        key_name: str,
        key_id: str,
        identity: str,
        organization: str,
        authority_class: str,
        gaps: list[str],
        decision: str = "approve",
    ) -> tuple[str, dict[str, object]]:
        review_relative = Path("reviews") / f"{key_name}.json"
        return key_name, {
            "identity": identity,
            "organization": organization,
            "authority_class": authority_class,
            "key_id": key_id,
            "decision": decision,
            "reviewed_gap_ids": gaps,
            "review_uri": f"artifact://{review_relative.as_posix()}",
            "review_sha256": "0" * 64,
            "signed_at": "2026-09-02T09:00:00Z",
            "statement_digest": "0" * 64,
            "signature_uri": "artifact://placeholder",
            "signature_sha256": "0" * 64,
        }

    def _materialize_final_reviewer(
        self,
        bundle: dict[str, object],
        *,
        key_name: str,
        reviewer: dict[str, object],
        roster_digest: str,
        context_digest: str,
    ) -> None:
        review_uri = reviewer["review_uri"]
        assert isinstance(review_uri, str)
        review_relative = Path(review_uri.removeprefix("artifact://"))
        review_path = self.artifact_root / review_relative
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_document = {
            "reviewer": reviewer["identity"],
            "organization": reviewer["organization"],
            "authority_class": reviewer["authority_class"],
            "gaps": reviewer["reviewed_gap_ids"],
            "decision": reviewer["decision"],
            "closure_manifest": {
                "schema_version": 1,
                "policy_id": "hepta-external-complete-closure-v1",
                "policy_revision": "2026-09-02-g10-quorum-1",
                "review_set_digest": roster_digest,
                "acceptance_context_digest": context_digest,
            },
        }
        review_payload = json.dumps(
            review_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        review_path.write_bytes(review_payload)
        reviewer["review_sha256"] = hashlib.sha256(review_payload).hexdigest()
        statement = external_evidence.canonical_review_statement(
            bundle,
            reviewer,
            contract_revision=self.contract["contract_revision"],
        )
        signature = self._sign(
            key_name,
            statement,
            Path("signatures") / f"{key_name}.review.sig",
        )
        reviewer["statement_digest"] = hashlib.sha256(statement).hexdigest()
        reviewer.update(signature)

    def _accept(
        self,
        bundle: dict[str, object],
        *,
        include_dissent: bool = False,
    ) -> None:
        submitted_gaps = sorted(
            {
                submission["gap_id"]
                for submission in bundle["submissions"]
                if isinstance(submission, dict)
            }
        )
        general_gaps = [
            gap
            for gap in submitted_gaps
            if gap not in {"HG-0011", "HG-0017", "HG-0044"}
        ]
        reviewer_entries: list[tuple[str, dict[str, object]]] = []
        if general_gaps:
            reviewer_entries.append(
                self._reviewer_shell(
                    key_name="release-reviewer",
                    key_id="release-reviewer-key",
                    identity="release-reviewer",
                    organization="release-review-board",
                    authority_class="release_acceptance_authority",
                    gaps=general_gaps,
                )
            )
        if "HG-0011" in submitted_gaps:
            reviewer_entries.append(
                self._reviewer_shell(
                    key_name="assurance-reviewer",
                    key_id="assurance-reviewer-key",
                    identity="assurance-reviewer",
                    organization="independent-assurance-lab",
                    authority_class="independent_assurance",
                    gaps=["HG-0011"],
                )
            )
        if "HG-0017" in submitted_gaps:
            reviewer_entries.append(
                self._reviewer_shell(
                    key_name="governance-reviewer",
                    key_id="governance-reviewer-key",
                    identity="governance-reviewer",
                    organization="repository-governance-audit",
                    authority_class="repository_governance_reviewer",
                    gaps=["HG-0017"],
                )
            )
        if "HG-0044" in submitted_gaps:
            reviewer_entries.append(
                self._reviewer_shell(
                    key_name="code-reviewer",
                    key_id="code-reviewer-key",
                    identity="code-reviewer",
                    organization="independent-code-review",
                    authority_class="independent_code_reviewer",
                    gaps=["HG-0044"],
                )
            )
        if include_dissent:
            dissent_gap = (
                "HG-0013" if "HG-0013" in submitted_gaps else general_gaps[0]
            )
            reviewer_entries.append(
                self._reviewer_shell(
                    key_name="dissent-reviewer",
                    key_id="dissent-reviewer-key",
                    identity="dissent-reviewer",
                    organization="independent-dissent-board",
                    authority_class="release_acceptance_authority",
                    gaps=[dissent_gap],
                    decision="reject",
                )
            )

        reviewers = [entry[1] for entry in reviewer_entries]
        bundle["acceptance"] = {
            "state": "accepted",
            "reviewed_at": "2026-09-02T10:00:00Z",
            "reviewers": reviewers,
            "bundle_digest": None,
            "decision_reference": "review:fixture:accepted",
            "limitations": [],
        }
        roster_digest = external_evidence.review_set_digest(reviewers)
        context_digest = external_evidence.acceptance_context_digest(
            bundle["acceptance"],
            roster_digest=roster_digest,
        )
        for key_name, reviewer in reviewer_entries:
            self._materialize_final_reviewer(
                bundle,
                key_name=key_name,
                reviewer=reviewer,
                roster_digest=roster_digest,
                context_digest=context_digest,
            )
        bundle["acceptance"]["bundle_digest"] = (
            external_evidence.canonical_bundle_digest(bundle)
        )

    def _write_bundle(
        self,
        bundle: dict[str, object],
        name: str = "bundle.json",
    ) -> Path:
        path = self.root / name
        path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
        return path

    def _validate(
        self,
        bundle: dict[str, object],
        *,
        complete: bool = False,
        accepted: bool = False,
        registry_digest: str | None = None,
    ) -> dict[str, object]:
        return external_evidence.validate_bundle(
            self._write_bundle(bundle),
            artifact_root=self.artifact_root,
            expected_commit=COMMIT,
            expected_tree=TREE,
            require_complete=complete,
            require_accepted=accepted,
            trust_registry_path=self.registry_path,
            expected_trust_registry_sha256=(
                registry_digest if registry_digest is not None else self.registry_digest
            ),
            now=FIXED_NOW,
        )
