#!/usr/bin/env python3
"""Generate exact-head SBOM, provenance, history, and source gate inputs."""

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

from services.qualification.sbom import (
    build_sbom,
    inventory_summary,
    sha256_file,
)
from tools.scan_repository_history import (
    HistoryScanError,
    build_history_report,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=root,
        text=True,
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


def material_digests(root: Path) -> dict[str, str]:
    required = (
        "docs/GAP_LEDGER.yaml",
        "docs/EVIDENCE_INDEX.yaml",
        "third_party/components.json",
        "pubspec.lock",
        "ios/Podfile.lock",
        "android/settings.gradle",
        "android/app/build.gradle",
        "android/gradle/wrapper/gradle-wrapper.properties",
    )
    result: dict[str, str] = {}
    for relative in required:
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"required evidence material is missing: {relative}")
        result[relative] = sha256_file(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("build/evidence"))
    parser.add_argument("--contracts-version")
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
        "GITHUB_REPOSITORY",
        "TrillionniumFoundation/hepta-glasses",
    )

    try:
        history_report = build_history_report(root)
    except HistoryScanError as error:
        raise SystemExit(f"credential history scan failed: {error}") from error
    if history_report["head"] != commit:
        raise SystemExit("credential history report is not bound to HEAD")
    if history_report["current_tree_findings_count"] != 0:
        raise SystemExit("current source tree contains credential material")
    history_digest = write_json(
        output / "credential-history-summary.json",
        history_report,
    )

    sbom = build_sbom(
        root,
        document_name=f"{repository}@{commit}",
        namespace=f"urn:hepta:sbom:{repository}:{commit}",
    )
    inventory = inventory_summary(sbom)
    sbom_digest = write_json(output / "source-sbom.spdx.json", sbom)
    materials = material_digests(root)
    third_party_digest = materials["third_party/components.json"]

    provenance = {
        "builder": "github-actions/hepta-source-evidence-v3",
        "build_type": "https://trillionnium.org/buildtypes/hepta-source/v1",
        "commit": commit,
        "contracts_version": contracts_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_scan_digest": history_digest,
        "materials": materials,
        "repository": repository,
        "sbom_digest": sbom_digest,
        "tree": tree,
    }
    provenance_digest = write_json(
        output / "source-provenance.json",
        provenance,
    )
    checks = [
        {
            "name": "repository-contracts",
            "conclusion": os.environ.get(
                "CI_REPOSITORY_CONTRACTS",
                "unknown",
            ),
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
            "conclusion": os.environ.get(
                "CI_NATIVE_SANITIZERS",
                "unknown",
            ),
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
            "contracts_version": contracts_version,
            "credential_history": {
                "current_tree_findings": history_report[
                    "current_tree_findings_count"
                ],
                "historical_findings": history_report[
                    "historical_findings_count"
                ],
                "historical_unique_fingerprints": history_report[
                    "historical_unique_fingerprint_count"
                ],
                "sha256": history_digest,
            },
            "provenance": {"sha256": provenance_digest},
            "sbom": {"sha256": sbom_digest, **inventory},
            "third_party_manifest": {"sha256": third_party_digest},
            "tree": tree,
        }
    }
    write_json(output / "source-release-bundle.json", bundle)
    summary = {
        "commit": commit,
        "contracts_version": contracts_version,
        "credential_history_digest": history_digest,
        "current_tree_credential_findings": history_report[
            "current_tree_findings_count"
        ],
        "historical_credential_findings": history_report[
            "historical_findings_count"
        ],
        **inventory,
        "provenance_digest": provenance_digest,
        "sbom_digest": sbom_digest,
        "third_party_manifest_digest": third_party_digest,
        "tree": tree,
    }
    write_json(output / "source-evidence-summary.json", summary)
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
