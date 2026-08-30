#!/usr/bin/env python3
"""Generate exact-head SBOM, provenance, and source release-gate bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.sbom import build_sbom


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, text=True
    ).strip()


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("build/evidence"))
    parser.add_argument("--contracts-version", default="2026-08-30-g2")
    args = parser.parse_args()
    root = args.root.resolve()
    output = (root / args.output_dir).resolve()
    commit = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    repository = os.environ.get(
        "GITHUB_REPOSITORY", "TrillionniumFoundation/hepta-glasses"
    )

    sbom = build_sbom(
        root,
        document_name=f"{repository}@{commit}",
        namespace=f"urn:hepta:sbom:{repository}:{commit}",
    )
    sbom_digest = write_json(output / "source-sbom.spdx.json", sbom)
    provenance = {
        "builder": "github-actions/hepta-source-evidence-v1",
        "commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": repository,
        "sbom_digest": sbom_digest,
        "tree": tree,
    }
    provenance_digest = write_json(output / "source-provenance.json", provenance)
    checks = [
        {
            "name": "repository-contracts",
            "conclusion": os.environ.get("CI_REPOSITORY_CONTRACTS", "unknown"),
        },
        {
            "name": "flutter",
            "conclusion": os.environ.get("CI_FLUTTER", "unknown"),
        },
        {
            "name": "secret-and-boundary-scan",
            "conclusion": os.environ.get("CI_SECRET_SCAN", "unknown"),
        },
    ]
    bundle = {
        "source": {
            "ci_checks": checks,
            "commit": commit,
            "contracts_version": args.contracts_version,
            "provenance": {"sha256": provenance_digest},
            "repository": repository,
            "sbom": {"sha256": sbom_digest},
            "tree": tree,
        }
    }
    write_json(output / "source-release-bundle.json", bundle)
    summary = {
        "commit": commit,
        "file_count": len(sbom["files"]),
        "package_count": len(sbom["packages"]),
        "provenance_digest": provenance_digest,
        "repository": repository,
        "sbom_digest": sbom_digest,
        "tree": tree,
    }
    write_json(output / "source-evidence-summary.json", summary)
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
