#!/usr/bin/env python3
"""Evaluate a source or signed product evidence bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.release_gate import (
    EvidenceTrustStore,
    ReleaseGate,
    ReleaseGateError,
)


def read_mapping(path: Path, *, error_code: str) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseGateError(error_code) from error
    if not isinstance(document, dict):
        raise ReleaseGateError(error_code)
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mode", choices=("source", "product"), required=True)
    parser.add_argument(
        "--trust-store",
        type=Path,
        help=(
            "Product-mode HMAC trust roots from a protected ephemeral secret "
            "mount. Never commit this file or place it in the evidence bundle."
        ),
    )
    parser.add_argument(
        "--now",
        type=int,
        help="Optional Unix time override for deterministic offline verification.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        document = read_mapping(
            args.bundle,
            error_code="release_bundle_invalid",
        )
        trust_store = None
        if args.mode == "product":
            if args.trust_store is None:
                raise ReleaseGateError("release_trust_store_required")
            trust_document = read_mapping(
                args.trust_store,
                error_code="release_trust_store_invalid",
            )
            trust_store = EvidenceTrustStore.from_document(trust_document)
        clock = (lambda: args.now) if args.now is not None else None
        result = ReleaseGate(
            trust_store=trust_store,
            clock=clock,
        ).evaluate(document, mode=args.mode)
    except ReleaseGateError as error:
        print(json.dumps({"ok": False, "error": error.code}, separators=(",", ":")))
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
