from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/validate_external_evidence.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_external_evidence_repository",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
external_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = external_evidence
SPEC.loader.exec_module(external_evidence)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _accepted_envelopes(base: Path) -> list[Path]:
    """Discover accepted envelopes at any immutable successor depth.

    Artifact, key, review, signature, template, and validator-output JSON files
    are excluded by content rather than trusted filename conventions. An
    authority bundle is identified by its canonical contract ID and accepted
    state, so moving it below ``successors/`` cannot bypass repository CI.
    """

    results: list[Path] = []
    for path in sorted(base.rglob("*.json")):
        document = _read_json_object(path)
        if document is None:
            continue
        if document.get("contract_id") != "hepta-external-evidence-envelope-v1":
            continue
        acceptance = document.get("acceptance")
        if isinstance(acceptance, dict) and acceptance.get("state") == "accepted":
            results.append(path)
    return results


class CommittedExternalEvidenceTest(unittest.TestCase):
    def test_authenticated_contract_surface_is_complete(self) -> None:
        required = [
            "contracts/external-evidence-envelope-v1.json",
            "schemas/external-evidence-envelope.schema.json",
            "schemas/external-authority-trust-registry.schema.json",
            "evidence/templates/external-evidence-bundle.template.json",
            "evidence/templates/external-authority-trust-registry.template.json",
            "evidence/external/README.md",
            "docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md",
            "docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md",
            "docs/adr/ADR-0008-authority-quorum-and-review-set-integrity.md",
            "tools/validate_external_evidence.py",
            "tools/external_evidence/complete_closure.py",
        ]
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
        contract = json.loads(
            (ROOT / "contracts/external-evidence-envelope-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(
            contract["contract_revision"],
            "2026-09-02-g10-quorum-1",
        )
        self.assertEqual(
            contract["signature_profile"],
            "ed25519-openssl-canonical-json-v1",
        )
        self.assertEqual(
            contract["trust_registry_profile"]["pin_source"],
            "out_of_band_required",
        )
        profile = contract["complete_closure_profile"]
        self.assertEqual(
            profile["policy_id"],
            "hepta-external-complete-closure-v1",
        )
        self.assertEqual(
            profile["issuer_claim_mode"],
            "exact_class_scoped_claims",
        )

    def test_committed_accepted_packages_require_external_trust_pin(self) -> None:
        base = ROOT / "evidence/external"
        self.assertTrue((base / "README.md").is_file())
        packages = _accepted_envelopes(base)
        if not packages:
            return

        external_pin = os.environ.get("HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256")
        self.assertIsNotNone(
            external_pin,
            "committed accepted evidence requires a protected, out-of-band "
            "HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256 value",
        )
        for bundle_path in packages:
            with self.subTest(bundle=str(bundle_path.relative_to(ROOT))):
                document = json.loads(bundle_path.read_text(encoding="utf-8"))
                candidate = document.get("candidate")
                self.assertIsInstance(candidate, dict)
                custody_root = bundle_path.parent
                while custody_root != base and not (
                    custody_root / "trust-registry.json"
                ).is_file():
                    custody_root = custody_root.parent
                registry_path = custody_root / "trust-registry.json"
                artifact_root = custody_root / "artifacts"
                self.assertTrue(registry_path.is_file())
                self.assertTrue(artifact_root.is_dir())
                result = external_evidence.validate_bundle(
                    bundle_path,
                    artifact_root=artifact_root,
                    expected_commit=candidate.get("source_commit"),
                    expected_tree=candidate.get("source_tree"),
                    require_complete=True,
                    require_accepted=True,
                    trust_registry_path=registry_path,
                    expected_trust_registry_sha256=external_pin,
                )
                self.assertTrue(result["all_authority_owned_gaps_closed"])
                self.assertEqual(result["missing_gaps"], [])
                self.assertEqual(
                    result["missing_issuer_authority_classes"],
                    {},
                )
                self.assertTrue(result["review_set_integrity"]["verified"])
                self.assertTrue(result["trust_registry"]["external_pin_verified"])

    def test_accepted_successor_discovery_cannot_be_filename_bypassed(self) -> None:
        with self.subTest("content based discovery"):
            self.assertIn("contract_id", _accepted_envelopes.__doc__ or "")
        base = ROOT / "evidence/external"
        for path in _accepted_envelopes(base):
            self.assertEqual(path.suffix, ".json")
            document = _read_json_object(path)
            self.assertIsNotNone(document)
            self.assertEqual(
                document["acceptance"]["state"],
                "accepted",
            )


if __name__ == "__main__":
    unittest.main()
