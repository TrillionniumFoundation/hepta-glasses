from __future__ import annotations

import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path

SUPPORT_PATH = Path(__file__).with_name("external_evidence_test_support.py")
SPEC = importlib.util.spec_from_file_location(
    "external_evidence_authority_seat_scope_support",
    SUPPORT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = support
SPEC.loader.exec_module(support)
external_evidence = support.external_evidence


class ExternalEvidenceAuthoritySeatScopeTest(support.ExternalEvidenceFixture):
    def _all_gap_bundle(self) -> dict[str, object]:
        return self._complete_bundle(list(self.contract["allowed_gap_ids"]))

    @staticmethod
    def _key_name(key_id: str) -> str:
        if not key_id.endswith("-key"):
            raise AssertionError(f"unexpected fixture key ID: {key_id}")
        return key_id.removesuffix("-key")

    def _resign_all_submissions(self, bundle: dict[str, object]) -> None:
        for index, submission in enumerate(bundle["submissions"]):
            issuer = submission["issuer"]
            key_name = self._key_name(str(issuer["key_id"]))
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
                Path("signatures") / f"seat-resigned-{index}.sig",
            )
            submission["attestation"] = {
                "signed_at": "2026-09-01T14:00:00Z",
                "statement_digest": hashlib.sha256(statement).hexdigest(),
                **signature,
            }

    def _submission(
        self,
        bundle: dict[str, object],
        *,
        gap_id: str,
        authority_class: str,
    ) -> dict[str, object]:
        return next(
            submission
            for submission in bundle["submissions"]
            if submission["gap_id"] == gap_id
            and submission["issuer"]["authority_class"] == authority_class
        )

    def _registry_record(self, key_id: str) -> dict[str, object]:
        return next(
            record
            for record in self.registry_document["keys"]
            if record["key_id"] == key_id
        )

    def test_one_key_cannot_span_different_authority_classes_across_gaps(self) -> None:
        bundle = self._all_gap_bundle()
        physical = self._submission(
            bundle,
            gap_id="HG-0010",
            authority_class="physical_device_lab",
        )
        speech = self._submission(
            bundle,
            gap_id="HG-0018",
            authority_class="speech_provider_owner",
        )
        physical_issuer = dict(physical["issuer"])
        physical_key_id = str(physical_issuer["key_id"])
        physical_record = self._registry_record(physical_key_id)
        physical_record["authority_classes"] = sorted(
            set(physical_record["authority_classes"]) | {"speech_provider_owner"}
        )
        physical_record["allowed_gap_ids"] = sorted(
            set(physical_record["allowed_gap_ids"]) | {"HG-0018"}
        )
        speech["issuer"] = {
            **physical_issuer,
            "authority_class": "speech_provider_owner",
        }
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        self._resign_all_submissions(bundle)
        self._accept(bundle)

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "issuer key .* spans authority classes",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_one_identity_pair_cannot_span_roles_with_different_keys(self) -> None:
        bundle = self._all_gap_bundle()
        physical = self._submission(
            bundle,
            gap_id="HG-0010",
            authority_class="physical_device_lab",
        )
        store = self._submission(
            bundle,
            gap_id="HG-0012",
            authority_class="store_authority",
        )
        physical_issuer = physical["issuer"]
        store_issuer = store["issuer"]
        store_issuer["identity"] = physical_issuer["identity"]
        store_issuer["organization"] = physical_issuer["organization"]
        store_record = self._registry_record(str(store_issuer["key_id"]))
        store_record["identity"] = physical_issuer["identity"]
        store_record["organization"] = physical_issuer["organization"]
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        self._resign_all_submissions(bundle)
        self._accept(bundle)

        with self.assertRaisesRegex(
            external_evidence.EvidenceError,
            "issuer identity .* spans authority classes",
        ):
            self._validate(bundle, complete=True, accepted=True)

    def test_same_narrow_authority_key_may_cover_multiple_related_gaps(self) -> None:
        bundle = self._all_gap_bundle()
        device = self._submission(
            bundle,
            gap_id="HG-0010",
            authority_class="physical_device_lab",
        )
        speech = self._submission(
            bundle,
            gap_id="HG-0018",
            authority_class="physical_device_lab",
        )
        speech["issuer"] = dict(device["issuer"])
        self.registry_digest = self._write_registry()
        bundle["trust_registry"]["sha256"] = self.registry_digest
        self._resign_all_submissions(bundle)
        self._accept(bundle)

        result = self._validate(bundle, complete=True, accepted=True)
        self.assertTrue(result["all_authority_owned_gaps_closed"])
        self.assertEqual(result["missing_issuer_authority_classes"], {})


if __name__ == "__main__":
    unittest.main()
