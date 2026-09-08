#!/usr/bin/env python3
"""Validate cross-document project truth without promoting external authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PLAN_REVISION = "2026-09-01-g8"
EXPECTED_HG0087_SLICES = {
    "identity",
    "model",
    "realtime",
    "capabilities",
    "speech",
    "skills",
    "memory",
}
EXPECTED_REQUIRED_JOBS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
)
EXPECTED_MATURITY_STAGES = (
    "design_draft",
    "source_implemented",
    "ci_qualified",
    "integration_qualified",
    "physical_device_qualified",
    "pilot_qualified",
    "released",
)
STALE_SOURCE_PHRASES = (
    "HG-0087 remains OPEN",
    "seven still-open production slices",
    "Speech source is unchanged by these increments",
    "HG-0087/model remains OPEN",
    "HG-0087/skills remains OPEN",
    "final unchanged head still requires a fresh complete seven-lane result",
)


class DocumentationTruthError(AssertionError):
    """Stable documentation-truth validation failure."""


def fail(message: str) -> None:
    raise DocumentationTruthError(message)


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        fail(f"missing or linked truth document: {relative}")
    return path.read_text(encoding="utf-8")


def read_object(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(read_text(root, relative))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"invalid truth JSON {relative}: {error}")
    if not isinstance(value, dict):
        fail(f"{relative} must contain an object")
    return value


def require_phrase(text: str, phrase: str, *, document: str) -> None:
    if phrase not in text:
        fail(f"{document} lacks required truth phrase: {phrase}")


def validate(root: Path = ROOT) -> dict[str, Any]:
    root_readme = read_text(root, "README.md")
    current_state = read_text(root, "docs/CURRENT_STATE.md")
    maturity = read_text(root, "docs/MATURITY_MODEL.md")
    roadmap = read_text(
        root,
        "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md",
    )
    project = read_object(root, "docs/PROJECT_STATE.json")
    implementation = read_object(root, "docs/HG0087_IMPLEMENTATION_STATUS.json")
    remediation = read_object(root, "docs/REMEDIATION_GAP_LEDGER.json")

    if project.get("plan_revision") != EXPECTED_PLAN_REVISION:
        fail("PROJECT_STATE plan revision drifted")
    require_phrase(
        current_state,
        f"Canonical plan revision: `{EXPECTED_PLAN_REVISION}`",
        document="docs/CURRENT_STATE.md",
    )

    gate = project.get("repository_actionable_gate")
    if not isinstance(gate, dict):
        fail("PROJECT_STATE lacks repository_actionable_gate")
    if gate.get("active_open_gap_ids") != []:
        fail("PROJECT_STATE reports repository-actionable OPEN gaps")
    if gate.get("documentation_truth_validator") != (
        "services/qualification/documentation_truth.py"
    ):
        fail("PROJECT_STATE does not register the documentation-truth validator")
    if tuple(gate.get("required_checks", ())) != EXPECTED_REQUIRED_JOBS:
        fail("PROJECT_STATE required check set drifted")
    status = gate.get("status")
    if not isinstance(status, str) or (
        "source_closed" not in status
        or "admin_and_external_authority" not in status
    ):
        fail("PROJECT_STATE gate status overclaims or omits remaining authority")

    if implementation.get("aggregate_status") != "CLOSED_SOURCE":
        fail("HG0087 aggregate status is not CLOSED_SOURCE")
    slices = implementation.get("slices")
    if not isinstance(slices, list):
        fail("HG0087 slices are missing")
    rows = {
        row.get("id"): row
        for row in slices
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if set(rows) != EXPECTED_HG0087_SLICES:
        fail("HG0087 slice identity set drifted")
    for name, row in rows.items():
        if row.get("status") != "CLOSED_SOURCE":
            fail(f"HG0087 slice {name} is not CLOSED_SOURCE")
        if not row.get("remaining_external"):
            fail(f"HG0087 slice {name} lacks remaining external truth")

    gaps = remediation.get("gaps")
    if not isinstance(gaps, list):
        fail("remediation gap ledger lacks gaps")
    by_id = {
        row.get("id"): row
        for row in gaps
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if by_id.get("HG-0087", {}).get("status") != "CLOSED_SOURCE":
        fail("remediation ledger disagrees on HG-0087")
    if by_id.get("HG-0089", {}).get("status") != "BLOCKED_ADMIN_SETTING":
        fail("remediation ledger does not preserve HG-0089 administration gate")
    open_rows = sorted(
        gap_id
        for gap_id, row in by_id.items()
        if row.get("status") == "OPEN"
    )
    if open_rows:
        fail(f"repository-actionable remediation rows remain OPEN: {open_rows}")

    for relative, text in (
        ("README.md", root_readme),
        ("docs/CURRENT_STATE.md", current_state),
    ):
        require_phrase(
            text,
            "HG-0087 is `CLOSED_SOURCE`",
            document=relative,
        )
        for phrase in STALE_SOURCE_PHRASES:
            if phrase in text:
                fail(f"{relative} contains stale source-status phrase: {phrase}")

    for relative in (
        "docs/CURRENT_STATE.md",
        "docs/PROJECT_STATE.json",
        "docs/REMEDIATION_GAP_LEDGER.json",
        "docs/HG0087_IMPLEMENTATION_STATUS.json",
        "docs/MATURITY_MODEL.md",
        "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md",
        "docs/MODULE_COVERAGE.json",
        "docs/MODULE_HANDOFF.json",
        "docs/development/MODULE_HANDOFF.md",
        "contracts/conformance/canonical-json-v1.json",
    ):
        require_phrase(root_readme, relative, document="README.md")

    for stage in EXPECTED_MATURITY_STAGES:
        require_phrase(maturity, f"`{stage}`", document="docs/MATURITY_MODEL.md")
    require_phrase(
        maturity,
        "overall product maturity is bounded by the least mature required axis",
        document="docs/MATURITY_MODEL.md",
    )
    require_phrase(
        roadmap,
        "Source code, local tests, mocks, screenshots",
        document="productization roadmap",
    )

    qualified = project.get("last_qualified_source")
    if not isinstance(qualified, dict) or qualified.get("completed") is not True:
        fail("PROJECT_STATE lacks a completed last-qualified source record")
    if qualified.get("repository") != "TrillionniumFoundation/hepta-glasses":
        fail("last-qualified repository identity drifted")
    if qualified.get("pull_request") != 101:
        fail("last-qualified pull request identity drifted")
    if tuple(qualified.get("required_jobs", ())) != EXPECTED_REQUIRED_JOBS:
        fail("last-qualified required jobs drifted")
    commit = qualified.get("commit")
    tree = qualified.get("tree")
    artifact_name = qualified.get("artifact_name")
    artifact_digest = qualified.get("artifact_zip_sha256")
    if not isinstance(commit, str) or len(commit) != 40:
        fail("last-qualified commit is malformed")
    if not isinstance(tree, str) or len(tree) != 40:
        fail("last-qualified tree is malformed")
    if artifact_name != f"hepta-source-evidence-{commit}":
        fail("last-qualified artifact name is not bound to its commit")
    if not isinstance(artifact_digest, str) or len(artifact_digest) != 64:
        fail("last-qualified artifact digest is malformed")
    if qualified.get("source_gate_checks") != "17/17":
        fail("last-qualified source-gate result drifted")
    if qualified.get("independent_artifact_checks") != "39/39":
        fail("last-qualified independent artifact result drifted")
    if qualified.get("successor_requires_fresh_qualification") is not True:
        fail("PROJECT_STATE permits successor evidence transfer")

    require_phrase(
        root_readme,
        commit,
        document="README.md",
    )
    require_phrase(
        current_state,
        commit,
        document="docs/CURRENT_STATE.md",
    )
    require_phrase(
        root_readme,
        artifact_digest,
        document="README.md",
    )
    require_phrase(
        current_state,
        artifact_digest,
        document="docs/CURRENT_STATE.md",
    )

    return {
        "plan_revision": EXPECTED_PLAN_REVISION,
        "hg0087_status": "CLOSED_SOURCE",
        "hg0087_slices": len(rows),
        "repository_actionable_open": 0,
        "hg0089_status": "BLOCKED_ADMIN_SETTING",
        "maturity_stages": len(EXPECTED_MATURITY_STAGES),
        "last_qualified_commit": commit,
        "required_jobs": len(EXPECTED_REQUIRED_JOBS),
    }


def main() -> int:
    try:
        result = validate()
    except (DocumentationTruthError, OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
