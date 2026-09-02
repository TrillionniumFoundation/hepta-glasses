from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .acceptance import validate_bundle
from .core import EvidenceError, require_sha


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--trust-registry", required=True, type=Path)
    parser.add_argument("--expected-trust-registry-sha256", required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-tree")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-accepted", action="store_true")
    parser.add_argument("--openssl-binary", default="openssl")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        expected_commit = (
            require_sha(args.expected_commit, label="--expected-commit", width=40)
            if args.expected_commit
            else None
        )
        expected_tree = (
            require_sha(args.expected_tree, label="--expected-tree", width=40)
            if args.expected_tree
            else None
        )
        result = validate_bundle(
            args.bundle,
            artifact_root=args.artifact_root,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
            require_complete=args.require_complete,
            require_accepted=args.require_accepted,
            trust_registry_path=args.trust_registry,
            expected_trust_registry_sha256=args.expected_trust_registry_sha256,
            openssl_binary=args.openssl_binary,
        )
    except EvidenceError as error:
        result = {"ok": False, "error": str(error)}
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        sys.stderr.write(payload)
        return 1

    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
