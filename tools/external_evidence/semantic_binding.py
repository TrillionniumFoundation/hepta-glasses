"""Bind canonical contract semantics into issuer and reviewer signatures."""

from __future__ import annotations

from types import ModuleType
from typing import Any, Mapping

_CONTRACT_BINDING_STATEMENT = "hepta.external-evidence-contract-binding.v1"


def install_semantic_binding(
    core: ModuleType,
    submission: ModuleType,
    acceptance: ModuleType,
) -> None:
    """Install contract-content-bound canonical statement functions.

    A revision label alone is not an immutable semantic identity. These
    functions add the canonical SHA-256 of the complete current contract to
    every issuer and reviewer preimage. Keeping the revision string while
    changing authority classes, claim partitions, review rules, or closure
    semantics therefore invalidates every existing signature.
    """

    def contract_binding(contract_revision: str) -> dict[str, Any]:
        contract = core.read_object(
            core.CONTRACT_PATH,
            "external evidence contract",
        )
        actual_revision = contract.get("contract_revision")
        if actual_revision != contract_revision:
            core.fail(
                "canonical statement contract revision differs from the "
                "current contract bytes"
            )
        return {
            "statement_type": _CONTRACT_BINDING_STATEMENT,
            "contract_id": contract.get("contract_id"),
            "contract_revision": actual_revision,
            "contract_sha256": core.canonical_digest(contract),
        }

    def evidence_set_digest(bundle: Mapping[str, Any]) -> str:
        contract = core.read_object(
            core.CONTRACT_PATH,
            "external evidence contract",
        )
        revision = contract.get("contract_revision")
        if not isinstance(revision, str) or not revision:
            core.fail("external evidence contract_revision is unavailable")
        return core.canonical_digest(
            {
                "statement_type": "hepta.external-evidence-set.v1",
                "contract_binding": contract_binding(revision),
                "contract_id": bundle.get("contract_id"),
                "trust_registry": bundle.get("trust_registry"),
                "candidate": bundle.get("candidate"),
                "submissions": bundle.get("submissions"),
            }
        )

    def canonical_submission_statement(
        bundle: Mapping[str, Any],
        submission_value: Mapping[str, Any],
        *,
        contract_revision: str,
    ) -> bytes:
        unsigned = {
            key: value
            for key, value in submission_value.items()
            if key != "attestation"
        }
        attestation = submission_value.get("attestation")
        signed_at = (
            attestation.get("signed_at")
            if isinstance(attestation, Mapping)
            else None
        )
        unsigned["attestation"] = {"signed_at": signed_at}
        return core.canonical_bytes(
            {
                "statement_type": "hepta.external-evidence-submission.v1",
                "contract_binding": contract_binding(contract_revision),
                "contract_id": bundle.get("contract_id"),
                "contract_revision": contract_revision,
                "trust_registry": bundle.get("trust_registry"),
                "candidate": bundle.get("candidate"),
                "submission": unsigned,
            }
        )

    def canonical_review_statement(
        bundle: Mapping[str, Any],
        reviewer: Mapping[str, Any],
        *,
        contract_revision: str,
    ) -> bytes:
        unsigned = {
            key: value
            for key, value in reviewer.items()
            if key
            not in {
                "statement_digest",
                "signature_uri",
                "signature_sha256",
            }
        }
        return core.canonical_bytes(
            {
                "statement_type": "hepta.external-evidence-review.v1",
                "contract_binding": contract_binding(contract_revision),
                "contract_id": bundle.get("contract_id"),
                "contract_revision": contract_revision,
                "trust_registry": bundle.get("trust_registry"),
                "candidate": bundle.get("candidate"),
                "evidence_set_digest": evidence_set_digest(bundle),
                "reviewer": unsigned,
            }
        )

    core.contract_binding = contract_binding
    core.evidence_set_digest = evidence_set_digest
    core.canonical_submission_statement = canonical_submission_statement
    core.canonical_review_statement = canonical_review_statement
    submission.canonical_submission_statement = canonical_submission_statement
    acceptance.evidence_set_digest = evidence_set_digest
    acceptance.canonical_review_statement = canonical_review_statement
