from __future__ import annotations

import json
import unittest
from pathlib import Path

from services.qualification.release_gate import ReleaseGate

ROOT = Path(__file__).resolve().parents[2]


class TrustedReleaseContractTest(unittest.TestCase):
    def test_product_contract_requires_authenticated_g10_closure(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/release-gates-v1.json").read_text(encoding="utf-8")
        )
        trusted = contract["trusted_product_gate"]
        self.assertEqual(contract["version"], 4)
        self.assertEqual(
            trusted["validator"],
            "tools.external_evidence.validate_bundle",
        )
        self.assertEqual(
            trusted["trust_anchor"],
            "out_of_band_registry_sha256",
        )
        self.assertIs(trusted["self_attested_product_fields_authoritative"], False)
        self.assertEqual(
            set(trusted["required_gap_ids"]),
            set(ReleaseGate.REQUIRED_AUTHORITY_GAPS),
        )

    def test_release_template_contains_paths_not_authority_booleans(self) -> None:
        template = json.loads(
            (
                ROOT
                / "evidence/templates/product-release-bundle.template.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(template), {"source", "external_evidence"})
        self.assertEqual(
            set(template["external_evidence"]),
            {"bundle", "artifact_root", "trust_registry"},
        )
        for forbidden in (
            "branch_protection",
            "device_qualification",
            "production",
            "reviews",
            "drills",
            "signing",
            "pilot",
        ):
            self.assertNotIn(forbidden, template)

    def test_product_cli_owns_external_validation(self) -> None:
        source = (ROOT / "tools/evaluate_release_gate.py").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256",
            "validate_bundle(",
            "expected_commit=source_commit",
            "expected_tree=source_tree",
            "require_complete=True",
            "require_accepted=True",
        ):
            self.assertIn(fragment, source)
        self.assertNotIn("--expected-trust-registry-sha256", source)

    def test_release_gate_contains_no_legacy_string_authority(self) -> None:
        source = (
            ROOT / "services/qualification/release_gate.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            'production.get("identity") == "verified"',
            'reviews.get("security") == "approved"',
            'drills.get("rollback") == "passed"',
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("all_authority_owned_gaps_closed", source)
        self.assertIn("external_pin_verified", source)
        self.assertIn("review_set_integrity", source)

    def test_physical_scenarios_require_sample_and_recovery_evidence(self) -> None:
        for platform in ("android", "ios"):
            scenario = json.loads(
                (
                    ROOT
                    / f"evidence/templates/{platform}-g1-qualification-scenario.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIs(scenario["require_fault_recovery"], True)
            self.assertGreaterEqual(
                scenario["minimum_wake_to_listening_samples"],
                30,
            )
            self.assertGreaterEqual(
                scenario["minimum_eos_to_first_display_samples"],
                30,
            )
            self.assertGreaterEqual(
                scenario["minimum_packet_samples_per_side"],
                1000,
            )
            self.assertGreaterEqual(scenario["minimum_battery_samples"], 12)
            self.assertGreaterEqual(scenario["minimum_temperature_samples"], 12)

    def test_trace_evaluator_cannot_sort_away_acquisition_drift(self) -> None:
        source = (
            ROOT / "services/qualification/device_report.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("sorted(events, key=lambda item: item.timestamp_ms)", source)
        for fragment in (
            "trace_not_monotonic",
            "trace_capture_sequence_not_contiguous",
            "required_faults_observed",
            "required_faults_recovered",
            "raw acquisition order",
        ):
            self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
