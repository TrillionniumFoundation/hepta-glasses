from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tools.external_evidence.committed_snapshot import validate_committed_packages

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
MAX_DISCOVERY_JSON_BYTES = 16 * 1024 * 1024


def _file_identity(status: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """Read one candidate through a bounded, no-follow stable descriptor.

    The initial lexical-object identity must equal the object opened with
    ``O_NOFOLLOW``. The descriptor identity must then remain unchanged for the
    complete bounded read. A replacement between discovery and open, a symbolic
    link, a special object, an oversized file, an unsupported no-follow API, or
    an unstable read is ignored rather than being promoted into an accepted
    envelope candidate.
    """

    descriptor: int | None = None
    try:
        lexical_status = path.lstat()
        if not stat.S_ISREG(lexical_status.st_mode):
            return None
        if lexical_status.st_size > MAX_DISCOVERY_JSON_BYTES:
            return None
        if not hasattr(os, "O_NOFOLLOW"):
            return None

        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(path, flags)
        opened_status = os.fstat(descriptor)
        if not stat.S_ISREG(opened_status.st_mode):
            return None
        if _file_identity(opened_status) != _file_identity(lexical_status):
            return None
        if opened_status.st_size > MAX_DISCOVERY_JSON_BYTES:
            return None

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(
                    1024 * 1024,
                    MAX_DISCOVERY_JSON_BYTES + 1 - total,
                ),
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_DISCOVERY_JSON_BYTES:
                return None

        final_status = os.fstat(descriptor)
        payload = b"".join(chunks)
        if _file_identity(final_status) != _file_identity(opened_status):
            return None
        if len(payload) != opened_status.st_size:
            return None
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return value if isinstance(value, dict) else None


def _accepted_envelopes(base: Path) -> list[Path]:
    """Discover accepted envelopes at any immutable successor depth.

    Discovery uses canonical content identity rather than a filename or suffix.
    Only stable regular-file descriptors whose lexical and opened identities
    match are read; repository symbolic links, replacement races, and other
    special objects are never promoted. Artifact, key, review, signature,
    template, and validator-output files are ignored unless they actually
    declare the canonical envelope contract and an accepted state. Moving an
    accepted envelope below ``successors/`` or giving it an opaque filename
    therefore cannot bypass repository CI.
    """

    results: list[Path] = []
    for path in sorted(base.rglob("*")):
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
        result = validate_committed_packages(
            base,
            expected_trust_registry_sha256=os.environ.get(
                "HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256"
            ),
        )
        self.assertTrue(result["verified"])
        # Legacy helpers below remain diagnostic test fixtures only. The actual
        # repository gate no longer reopens discovered mutable pathnames.

    def test_accepted_successor_discovery_cannot_be_filename_bypassed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "opaque" / "not-a-bundle-extension.payload"
            path.parent.mkdir()
            path.write_text(
                json.dumps(
                    {
                        "contract_id": "hepta-external-evidence-envelope-v1",
                        "acceptance": {"state": "accepted"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(_accepted_envelopes(base), [path])

    def test_repository_symlink_is_not_followed_during_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "evidence"
            outside = Path(directory) / "outside.json"
            base.mkdir()
            outside.write_text(
                json.dumps(
                    {
                        "contract_id": "hepta-external-evidence-envelope-v1",
                        "acceptance": {"state": "accepted"},
                    }
                ),
                encoding="utf-8",
            )
            alias = base / "accepted-link"
            try:
                alias.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            self.assertEqual(_accepted_envelopes(base), [])

    def test_regular_replacement_between_lstat_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.json"
            retired = root / "retired.json"
            candidate.write_text(
                json.dumps(
                    {
                        "contract_id": "hepta-external-evidence-envelope-v1",
                        "acceptance": {"state": "incomplete"},
                    }
                ),
                encoding="utf-8",
            )
            replacement = json.dumps(
                {
                    "contract_id": "hepta-external-evidence-envelope-v1",
                    "acceptance": {"state": "accepted"},
                }
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
                if not replaced and Path(target) == candidate:
                    candidate.rename(retired)
                    candidate.write_text(replacement, encoding="utf-8")
                    replaced = True
                return original_open(target, flags, *args, **kwargs)

            with mock.patch.object(os, "open", side_effect=raced_open):
                self.assertIsNone(_read_json_object(candidate))
            self.assertTrue(replaced)
            self.assertEqual(
                json.loads(candidate.read_text(encoding="utf-8"))["acceptance"][
                    "state"
                ],
                "accepted",
            )


if __name__ == "__main__":
    unittest.main()
