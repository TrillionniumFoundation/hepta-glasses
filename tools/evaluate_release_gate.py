#!/usr/bin/env python3
"""Evaluate source or product evidence without override or self-attestation.

Product mode invokes the authenticated G10 external-evidence validator in the
same process.  The trust-registry digest must arrive out of band through
``HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256``; a digest written inside the release
bundle is never accepted as its own trust anchor.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.release_gate import ReleaseGate, ReleaseGateError


def canonical_version(root: Path) -> str:
    ledger = json.loads((root / "docs/GAP_LEDGER.yaml").read_text(encoding="utf-8"))
    value = ledger.get("plan_revision")
    if not isinstance(value, str) or not value:
        raise ReleaseGateError("canonical_gap_ledger_revision_missing")
    return value


def _mapping(value: Any, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseGateError(code)
    return value


def _repository_path(value: Any, *, label: str, directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ReleaseGateError(f"{label}_missing")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or "\\" in value
        or not pure.parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ReleaseGateError(f"{label}_path_invalid")
    path = ROOT.joinpath(*pure.parts)
    if directory:
        if not path.is_dir():
            raise ReleaseGateError(f"{label}_directory_missing")
    elif not path.is_file():
        raise ReleaseGateError(f"{label}_file_missing")
    return path


def _trust_registry_pin() -> str:
    value = os.environ.get("HEPTA_EXTERNAL_TRUST_REGISTRY_SHA256", "")
    if len(value) != 64 or value != value.lower() or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ReleaseGateError("external_trust_registry_pin_missing_or_invalid")
    return value


def _external_evidence_result(
    release_bundle: Mapping[str, Any],
    source: Mapping[str, Any],
) -> Mapping[str, Any]:
    configuration = _mapping(
        release_bundle.get("external_evidence"),
        code="external_evidence_configuration_missing",
    )
    if set(configuration) != {"bundle", "artifact_root", "trust_registry"}:
        raise ReleaseGateError("external_evidence_configuration_fields_invalid")
    source_commit = source.get("commit")
    source_tree = source.get("tree")
    if not isinstance(source_commit, str) or not isinstance(source_tree, str):
        raise ReleaseGateError("external_evidence_source_identity_missing")

    # Lazy import keeps source-only qualification independent of the trusted
    # product verifier host. Product mode still fails closed if the verifier
    # runtime or its absolute OpenSSL boundary is unavailable.
    from tools.external_evidence import EvidenceError, validate_bundle

    try:
        return validate_bundle(
            _repository_path(
                configuration["bundle"],
                label="external_evidence_bundle",
                directory=False,
            ),
            artifact_root=_repository_path(
                configuration["artifact_root"],
                label="external_evidence_artifact_root",
                directory=True,
            ),
            trust_registry_path=_repository_path(
                configuration["trust_registry"],
                label="external_evidence_trust_registry",
                directory=False,
            ),
            expected_trust_registry_sha256=_trust_registry_pin(),
            expected_commit=source_commit,
            expected_tree=source_tree,
            require_complete=True,
            require_accepted=True,
        )
    except EvidenceError as error:
        raise ReleaseGateError(
            f"external_evidence_validation_failed:{error}"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mode", choices=("source", "product"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()

    bundle_path = args.bundle
    if not bundle_path.is_absolute():
        bundle_path = ROOT / bundle_path
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    release_bundle = _mapping(bundle, code="release_bundle_must_be_object")
    source = _mapping(
        release_bundle.get("source"),
        code="release_source_evidence_missing",
    )
    evidence_dir = (
        args.evidence_dir
        if args.evidence_dir is not None
        else bundle_path.parent
    )
    if not evidence_dir.is_absolute():
        evidence_dir = ROOT / evidence_dir

    external_result = None
    if args.mode == "product":
        external_result = _external_evidence_result(release_bundle, source)

    result = ReleaseGate(
        expected_contracts_version=canonical_version(ROOT)
    ).evaluate(
        release_bundle,
        mode=args.mode,
        evidence_dir=evidence_dir,
        external_evidence_result=external_result,
    )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.to_mapping(), separators=(",", ":")))
    return 0 if result.passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        json.JSONDecodeError,
        ReleaseGateError,
    ) as error:
        code = error.code if isinstance(error, ReleaseGateError) else str(error)
        print(f"release gate error: {code}", file=sys.stderr)
        raise SystemExit(2)
