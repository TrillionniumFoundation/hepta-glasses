#!/usr/bin/env python3
"""Evaluate a source or product evidence bundle without override paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.release_gate import ReleaseGate, ReleaseGateError


def canonical_version(root: Path) -> str:
    ledger = json.loads((root / "docs/GAP_LEDGER.yaml").read_text(encoding="utf-8"))
    value = ledger.get("plan_revision")
    if not isinstance(value, str) or not value:
        raise SystemExit("canonical Gap Ledger has no plan_revision")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mode", choices=("source", "product"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    bundle_path = args.bundle.resolve()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence_dir = (
        args.evidence_dir.resolve()
        if args.evidence_dir is not None
        else bundle_path.parent
    )
    result = ReleaseGate(
        expected_contracts_version=canonical_version(ROOT)
    ).evaluate(bundle, mode=args.mode, evidence_dir=evidence_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.to_mapping(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.to_mapping(), separators=(",", ":")))
    return 0 if result.passed else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ReleaseGateError) as error:
        print(f"release gate error: {error}", file=sys.stderr)
        raise SystemExit(2)
