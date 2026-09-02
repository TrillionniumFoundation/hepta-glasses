from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tools import external_evidence
from tools.external_evidence import EvidenceError
from tools.external_evidence.repository_admission import (
    discover_accepted_envelopes,
)

ROOT = Path(__file__).resolve().parents[2]


def _accepted_document() -> dict[str, object]:
    return {
        "contract_id": "hepta-external-evidence-envelope-v1",
        "acceptance": {"state": "accepted"},
    }


class DescriptorAnchoredRepositoryAdmissionTest(unittest.TestCase):
    def test_actual_repository_acceptance_is_discovered_and_revalidated(self) -> None:
        base = ROOT / "evidence/external"
        packages = discover_accepted_envelopes(base)
        if not packages:
            return

        external_pin = os.environ.get("HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256")
        self.assertIsNotNone(
            external_pin,
            "committed accepted evidence requires a protected, out-of-band "
            "HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256 value",
        )
        for envelope in packages:
            with self.subTest(bundle=str(envelope.path.relative_to(ROOT))):
                candidate = envelope.document.get("candidate")
                self.assertIsInstance(candidate, dict)
                assert isinstance(candidate, dict)
                custody_root = envelope.path.parent
                while custody_root != base and not (
                    custody_root / "trust-registry.json"
                ).is_file():
                    custody_root = custody_root.parent
                registry_path = custody_root / "trust-registry.json"
                artifact_root = custody_root / "artifacts"
                self.assertTrue(registry_path.is_file())
                self.assertTrue(artifact_root.is_dir())
                result = external_evidence.validate_bundle(
                    envelope.path,
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
                self.assertEqual(result["missing_issuer_authority_classes"], {})
                self.assertTrue(result["review_set_integrity"]["verified"])
                self.assertTrue(result["trust_registry"]["external_pin_verified"])

    def test_opaque_nested_filename_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "evidence"
            path = base / "successors" / "opaque.payload"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(_accepted_document()), encoding="utf-8")
            envelopes = discover_accepted_envelopes(base)
            self.assertEqual([item.path for item in envelopes], [path.resolve()])

    def test_symbolic_link_entry_fails_the_repository_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "evidence"
            base.mkdir()
            outside = Path(directory) / "outside.json"
            outside.write_text(json.dumps(_accepted_document()), encoding="utf-8")
            alias = base / "accepted-link"
            try:
                alias.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            with self.assertRaisesRegex(EvidenceError, "is a symbolic link"):
                discover_accepted_envelopes(base)

    def test_file_replacement_between_stat_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "evidence"
            base.mkdir()
            candidate = base / "candidate.json"
            retired = base / "retired.json"
            candidate.write_text(
                json.dumps(
                    {
                        "contract_id": "hepta-external-evidence-envelope-v1",
                        "acceptance": {"state": "incomplete"},
                    }
                ),
                encoding="utf-8",
            )
            replacement = json.dumps(_accepted_document())
            original_open = os.open
            replaced = False

            def raced_open(
                target: os.PathLike[str] | str,
                flags: int,
                *args: Any,
                **kwargs: Any,
            ) -> int:
                nonlocal replaced
                if (
                    not replaced
                    and target == "candidate.json"
                    and kwargs.get("dir_fd") is not None
                    and not (flags & getattr(os, "O_DIRECTORY", 0))
                ):
                    candidate.rename(retired)
                    candidate.write_text(replacement, encoding="utf-8")
                    replaced = True
                return original_open(target, flags, *args, **kwargs)

            with mock.patch(
                "tools.external_evidence.repository_admission.os.open",
                side_effect=raced_open,
            ):
                with self.assertRaisesRegex(
                    EvidenceError,
                    "changed between lexical inspection and open",
                ):
                    discover_accepted_envelopes(base)
            self.assertTrue(replaced)

    def test_directory_replacement_between_stat_and_open_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "evidence"
            candidate = base / "candidate"
            retired = base / "retired"
            candidate.mkdir(parents=True)
            (candidate / "bundle.json").write_text(
                json.dumps(_accepted_document()),
                encoding="utf-8",
            )
            original_open = os.open
            replaced = False

            def raced_open(
                target: os.PathLike[str] | str,
                flags: int,
                *args: Any,
                **kwargs: Any,
            ) -> int:
                nonlocal replaced
                if (
                    not replaced
                    and target == "candidate"
                    and kwargs.get("dir_fd") is not None
                    and flags & getattr(os, "O_DIRECTORY", 0)
                ):
                    candidate.rename(retired)
                    candidate.mkdir()
                    (candidate / "replacement.json").write_text(
                        json.dumps(_accepted_document()),
                        encoding="utf-8",
                    )
                    replaced = True
                return original_open(target, flags, *args, **kwargs)

            with mock.patch(
                "tools.external_evidence.repository_admission.os.open",
                side_effect=raced_open,
            ):
                with self.assertRaisesRegex(
                    EvidenceError,
                    "changed between inspection and open",
                ):
                    discover_accepted_envelopes(base)
            self.assertTrue(replaced)


if __name__ == "__main__":
    unittest.main()
