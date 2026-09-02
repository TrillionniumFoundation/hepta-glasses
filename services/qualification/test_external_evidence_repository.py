from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

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
            "tools/validate_external_evidence.py",
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
            contract["signature_profile"],
            "ed25519-openssl-canonical-json-v1",
        )
        self.assertEqual(
            contract["trust_registry_profile"]["pin_source"],
            "out_of_band_required",
        )

    def test_committed_candidate_packages_require_external_trust_pin(self) -> None:
        base = ROOT / "evidence/external"
        self.assertTrue((base / "README.md").is_file())

        packages = sorted(
            path
            for path in base.glob("*/bundle.json")
            if path.parent.name not in {"templates", "example"}
        )
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
                registry_path = bundle_path.parent / "trust-registry.json"
                self.assertTrue(registry_path.is_file())
                result = external_evidence.validate_bundle(
                    bundle_path,
                    artifact_root=bundle_path.parent / "artifacts",
                    expected_commit=candidate.get("source_commit"),
                    expected_tree=candidate.get("source_tree"),
                    require_complete=True,
                    require_accepted=True,
                    trust_registry_path=registry_path,
                    expected_trust_registry_sha256=external_pin,
                )
                self.assertTrue(result["all_authority_owned_gaps_closed"])
                self.assertEqual(result["missing_gaps"], [])
                self.assertTrue(result["trust_registry"]["external_pin_verified"])


if __name__ == "__main__":
    unittest.main()
