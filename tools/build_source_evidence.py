#!/usr/bin/env python3
"""Generate exact-head multi-ecosystem source evidence."""

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

from services.qualification.sbom import build_sbom, package_ecosystems
from tools.scan_git_history import build_report as build_history_report


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, text=True
    ).strip()


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def canonical_contracts_version(root: Path) -> str:
    ledger_path = root / "docs/GAP_LEDGER.yaml"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"canonical Gap Ledger is unreadable: {error}") from error
    version = ledger.get("plan_revision") if isinstance(ledger, dict) else None
    if not isinstance(version, str) or not version:
        raise SystemExit("canonical Gap Ledger has no plan_revision")
    return version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("build/evidence"))
    parser.add_argument("--contracts-version")
    parser.add_argument("--native-sanitizer-report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (root / args.output_dir).resolve()
    contracts_version = canonical_contracts_version(root)
    if (
        args.contracts_version is not None
        and args.contracts_version != contracts_version
    ):
        raise SystemExit(
            "requested contracts version does not match the canonical Gap Ledger"
        )

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

    history = build_history_report(root)
    if history["head"] != commit:
        raise SystemExit("history scan did not bind to the exact source head")
    if history["finding_count"] != 0:
        raise SystemExit("history scan found candidate secret material")
    history_digest = write_json(output / "source-history-scan.json", history)

    native_source = args.native_sanitizer_report
    if native_source is None:
        native_source = output / "source-native-sanitizer.json"
    elif not native_source.is_absolute():
        native_source = root / native_source
    if not native_source.is_file():
        raise SystemExit("native sanitizer report is missing")
    native = json.loads(native_source.read_text(encoding="utf-8"))
    if native.get("passed") is not True or native.get(
        "lc3_cross_platform_parity"
    ) is not True:
        raise SystemExit("native sanitizer report did not pass")
    native_digest = write_json(output / "source-native-sanitizer.json", native)

    provenance = {
        "type": "unsigned-source-provenance-v1",
        "attestation": "unsigned-ci-generated-source-metadata",
        "builder": "github-actions/hepta-source-evidence-v3",
        "commit": commit,
        "contracts_version": contracts_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_scan_digest": history_digest,
        "native_sanitizer_digest": native_digest,
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
            "name": "android-native",
            "conclusion": os.environ.get("CI_ANDROID_NATIVE", "unknown"),
        },
        {
            "name": "ios-native",
            "conclusion": os.environ.get("CI_IOS_NATIVE", "unknown"),
        },
        {
            "name": "native-sanitizers",
            "conclusion": os.environ.get("CI_NATIVE_SANITIZERS", "unknown"),
        },
        {
            "name": "secret-and-boundary-scan",
            "conclusion": os.environ.get("CI_SECRET_SCAN", "unknown"),
        },
    ]
    ecosystems = list(package_ecosystems(sbom))
    bundle = {
        "source": {
            "audit_contract": "file-lock-checkpoint-v1",
            "ci_checks": checks,
            "commit": commit,
            "contracts_version": contracts_version,
            "history_scan": {
                "sha256": history_digest,
                "scope": history["scope"],
                "commit_count": history["commit_count"],
                "scanned_blob_count": history["scanned_blob_count"],
                "finding_count": history["finding_count"],
            },
            "native_sanitizer": {
                "sha256": native_digest,
                "passed": native["passed"],
                "lc3_cross_platform_parity": native[
                    "lc3_cross_platform_parity"
                ],
            },
            "provenance": {"sha256": provenance_digest},
            "provenance_type": provenance["type"],
            "sbom": {"sha256": sbom_digest},
            "sbom_ecosystems": ecosystems,
            "tree": tree,
        }
    }
    write_json(output / "source-release-bundle.json", bundle)
    summary = {
        "audit_contract": "file-lock-checkpoint-v1",
        "commit": commit,
        "contracts_version": contracts_version,
        "file_count": len(sbom["files"]),
        "history_commit_count": history["commit_count"],
        "history_finding_count": history["finding_count"],
        "native_sanitizer_digest": native_digest,
        "package_count": len(sbom["packages"]),
        "provenance_digest": provenance_digest,
        "sbom_digest": sbom_digest,
        "sbom_ecosystems": ecosystems,
        "tree": tree,
    }
    write_json(output / "source-evidence-summary.json", summary)
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
