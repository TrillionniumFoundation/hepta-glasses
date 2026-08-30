#!/usr/bin/env python3
"""Evaluate a source or product evidence bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.release_gate import ReleaseGate, ReleaseGateError


def canonical_contracts_version() -> str:
    try:
        ledger = json.loads(
            (ROOT / "docs/GAP_LEDGER.yaml").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseGateError("canonical_gap_ledger_invalid") from error
    version = ledger.get("plan_revision") if isinstance(ledger, dict) else None
    if not isinstance(version, str) or not version:
        raise ReleaseGateError("canonical_contracts_version_missing")
    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mode", choices=("source", "product"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.bundle.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ReleaseGateError("release_bundle_invalid")
        result = ReleaseGate(
            expected_contracts_version=canonical_contracts_version()
        ).evaluate(document, mode=args.mode)
    except (OSError, json.JSONDecodeError, ReleaseGateError) as error:
        code = error.code if isinstance(error, ReleaseGateError) else "release_bundle_invalid"
        print(json.dumps({"ok": False, "error": code}, separators=(",", ":")))
        return 2

    payload = result.to_mapping()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, separators=(",", ":")))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
