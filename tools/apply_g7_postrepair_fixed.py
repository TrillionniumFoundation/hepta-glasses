#!/usr/bin/env python3
"""Normalize active G7 truth without rewriting historical evidence records."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_REVISIONS = ("2026-08-30-g4", "2026-08-31-g5")
NEW_REVISION = "2026-08-31-g7"


def active_paths() -> list[Path]:
    explicit = [
        ROOT / "README.md",
        ROOT / "docs/CURRENT_STATE.md",
        ROOT / "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
        ROOT / "docs/GAP_LEDGER.yaml",
        ROOT / "docs/EVIDENCE_INDEX.yaml",
        ROOT / "docs/README.md",
        ROOT / "contracts/release-gates-v1.json",
        ROOT / "evidence/templates/product-release-bundle.template.json",
        ROOT / "services/qualification/release_gate.py",
        ROOT / "tools/build_source_evidence.py",
        ROOT / "tools/evaluate_release_gate.py",
        ROOT / "tools/validate_repository.py",
        ROOT / ".github/workflows/ci.yml",
        ROOT / ".github/workflows/g7-qualify.yml",
    ]
    explicit.extend((ROOT / "services/qualification").glob("test_*.py"))
    return [path for path in explicit if path.is_file()]


def normalize_revisions() -> None:
    for path in active_paths():
        text = path.read_text(encoding="utf-8")
        for old in OLD_REVISIONS:
            text = text.replace(old, NEW_REVISION)
        text = text.replace("## 5. G4 closure order", "## 5. G7 closure order")
        if path == ROOT / "README.md":
            text = text.replace(
                "flutter analyze --no-fatal-infos --no-fatal-warnings",
                "flutter analyze --no-fatal-infos",
            )
        path.write_text(text, encoding="utf-8")


def update_gap_ledger() -> None:
    path = ROOT / "docs/GAP_LEDGER.yaml"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["plan_revision"] = NEW_REVISION
    existing = {item["id"] for item in document["gaps"]}
    additions = [
        {
            "id": "HG-0035",
            "title": "Historical provider credential requires verified rotation or revocation",
            "status": "BLOCKED_EXTERNAL",
            "owner": "security-operations",
            "source_preparation": [
                "tools/scan_git_history.py",
                "docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md",
                "evidence/templates/credential-incident-closure.template.json",
                "services/qualification/release_gate.py",
            ],
            "evidence_required": [
                "provider-side credential rotation or revocation record",
                "independent verification that the old credential is unusable",
                "incident owner and closure timestamp",
            ],
            "unblock_condition": "Attach redacted provider-side rotation or revocation evidence and pass the product release gate.",
        },
        {
            "id": "HG-0036",
            "title": "G4 and G6 source lines diverged without one canonical convergence head",
            "status": "CLOSED_SOURCE",
            "owner": "repository",
            "evidence": [
                "docs/development/G7_SYNTHESIS.md",
                "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
                ".github/workflows/g7-qualify.yml",
            ],
        },
        {
            "id": "HG-0037",
            "title": "Bitmap transfer, heartbeat, and history UI retained demo-level failure modes",
            "status": "CLOSED_SOURCE",
            "owner": "mobile-runtime",
            "evidence": [
                "lib/controllers/bmp_update_manager.dart",
                "lib/ble_manager.dart",
                "lib/views/even_list_page.dart",
                "test/controllers/bmp_update_manager_test.dart",
                "test/views/even_list_page_test.dart",
            ],
        },
        {
            "id": "HG-0038",
            "title": "Reference capability and realtime state machines admitted in-process concurrency races",
            "status": "CLOSED_SOURCE",
            "owner": "control-plane",
            "evidence": [
                "services/control_plane/capabilities.py",
                "services/control_plane/realtime.py",
                "services/control_plane/test_concurrency_g7.py",
            ],
        },
        {
            "id": "HG-0039",
            "title": "Skill package bytes and model-gateway bind mode lacked fail-closed verification",
            "status": "CLOSED_SOURCE",
            "owner": "security",
            "evidence": [
                "services/skills/registry.py",
                "services/skills/test_package_integrity_g7.py",
                "services/model_gateway/app.py",
                "services/model_gateway/test_binding_guard_g7.py",
            ],
        },
    ]
    document["gaps"].extend(item for item in additions if item["id"] not in existing)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def update_current_state() -> None:
    path = ROOT / "docs/CURRENT_STATE.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "G5 is an independent-audit closure stacked on the exact G4 source candidate.",
        "G7 is the sole convergence candidate combining the stricter G4 native/mobile line with the G5/G6 audit and evidence line.",
    )
    text = text.replace(
        "Repository-actionable G5 gaps are closed only when the exact-head source gate",
        "Repository-actionable G7 gaps are closed only when the exact-head source gate",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    normalize_revisions()
    update_gap_ledger()
    update_current_state()
    for path in ROOT.glob("tools/apply_g7_*.py"):
        path.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
