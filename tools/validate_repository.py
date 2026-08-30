#!/usr/bin/env python3
"""Fail-closed source contract validator with no third-party dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = {
    "README.md",
    "AGENTS.md",
    "UPSTREAM.md",
    "docs/README.md",
    "docs/CURRENT_STATE.md",
    "docs/PRODUCT_BOUNDARY.md",
    "docs/ARCHITECTURE.md",
    "docs/THREAT_MODEL.md",
    "docs/PRIVACY_MODEL.md",
    "docs/CAPABILITY_MODEL.md",
    "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
    "docs/development/G3_G8_SOURCE_CLOSURE.md",
    "docs/operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md",
    "docs/operations/REALTIME_AND_CAPABILITY_RUNBOOK.md",
    "docs/operations/DEVICE_QUALIFICATION_RUNBOOK.md",
    "docs/operations/REPOSITORY_GOVERNANCE_RUNBOOK.md",
    "docs/operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md",
    "docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md",
    "docs/GAP_LEDGER.yaml",
    "docs/EVIDENCE_INDEX.yaml",
    "contracts/hepta-glasses-runtime-v1.json",
    "contracts/control-plane-v1.json",
    "contracts/main-branch-protection-v1.json",
    "contracts/release-gates-v1.json",
    "contracts/qualification-slo-v1.json",
    "lib/runtime/contracts.dart",
    "lib/runtime/audit_journal.dart",
    "lib/runtime/task_engine.dart",
    "lib/runtime/policy_engine.dart",
    "lib/runtime/tool_gateway.dart",
    "lib/runtime/device_hal.dart",
    "lib/runtime/packet_codec.dart",
    "lib/runtime/dual_leg_coordinator.dart",
    "lib/runtime/model_gateway.dart",
    "lib/runtime/assistant_session.dart",
    "lib/runtime/device_effect_scheduler.dart",
    "lib/runtime/hepta_runtime.dart",
    "lib/simulator/g1_digital_twin.dart",
    "services/control_plane/identity.py",
    "services/control_plane/realtime.py",
    "services/control_plane/capabilities.py",
    "services/skills/registry.py",
    "services/skills/memory.py",
    "services/qualification/device_report.py",
    "services/qualification/release_gate.py",
    "services/qualification/sbom.py",
    "services/qualification/governance.py",
    "services/codex_worker/worker.py",
    "adapters/mcp/hepta_glasses_mcp_server.py",
    "tools/qualify_device_trace.py",
    "tools/build_source_evidence.py",
    "tools/evaluate_release_gate.py",
    "tools/repository_governance.py",
    "evidence/templates/android-g1-qualification-scenario.json",
    "evidence/templates/ios-g1-qualification-scenario.json",
    "evidence/templates/product-release-bundle.template.json",
    ".github/workflows/ci.yml",
}

FORBIDDEN_PATTERNS = {
    "provider key name": re.compile(
        r"DASHSCOPE_API_KEY|DEEPSEEK_API_KEY|OPENAI_API_KEY"
    ),
    "direct provider endpoint": re.compile(
        r"api\.deepseek\.com|dashscope\.aliyuncs\.com|api\.openai\.com"
    ),
    "Codex sandbox bypass": re.compile(
        r"dangerously-bypass-approvals-and-sandbox|--yolo|danger-full-access"
    ),
    "private key material": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "GitHub token material": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
}

SCAN_SOURCE = [
    "lib",
    "android",
    "ios",
    "services",
    "adapters",
    "plugins",
]
ALLOWED_GAP_STATUSES = {
    "CLOSED_SOURCE",
    "CLOSED_VERIFIED",
    "BLOCKED_EXTERNAL",
    "BLOCKED_ADMIN_SETTING",
    "BLOCKED_UPSTREAM",
    "OPEN",
}
EXPECTED_CHECKS = {
    "android-native",
    "flutter",
    "ios-native",
    "repository-contracts",
    "secret-and-boundary-scan",
    "source-evidence",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        fail(f"invalid JSON/YAML-as-JSON {path.relative_to(ROOT)}: {exc}")


def validate_required() -> None:
    missing = sorted(path for path in REQUIRED if not (ROOT / path).is_file())
    if missing:
        fail(f"missing required files: {missing}")
    if len((ROOT / "README.md").read_text(encoding="utf-8").strip()) < 500:
        fail("README.md is not a meaningful product entry point")


def validate_json_contracts() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.json"))
    if len(schemas) < 12:
        fail("expected expanded runtime/control-plane/release schema set")
    for path in schemas:
        document = read_json(path)
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"{path.relative_to(ROOT)} is not a draft-2020-12 schema")
        if document.get("type") != "object" or not document.get("required"):
            fail(f"{path.relative_to(ROOT)} lacks an object/required contract")
    for name in (
        "hepta-glasses-runtime-v1.json",
        "control-plane-v1.json",
        "main-branch-protection-v1.json",
        "release-gates-v1.json",
        "qualification-slo-v1.json",
    ):
        read_json(ROOT / "contracts" / name)


def validate_gap_ledger() -> None:
    ledger = read_json(ROOT / "docs/GAP_LEDGER.yaml")
    if ledger.get("plan_revision") != "2026-08-30-g2":
        fail("Gap Ledger is not bound to the canonical g2 plan")
    gaps = ledger.get("gaps")
    if not isinstance(gaps, list) or len(gaps) < 27:
        fail("Gap Ledger does not contain the complete source/external gate set")
    seen = set()
    for gap in gaps:
        gap_id = gap.get("id")
        status = gap.get("status")
        if not isinstance(gap_id, str) or gap_id in seen:
            fail(f"invalid or duplicate gap id: {gap_id!r}")
        seen.add(gap_id)
        if status not in ALLOWED_GAP_STATUSES:
            fail(f"{gap_id} has invalid status {status!r}")
        if status.startswith("CLOSED") and not gap.get("evidence"):
            fail(f"{gap_id} is closed without evidence")
        if status.startswith("BLOCKED"):
            if not gap.get("evidence_required"):
                fail(f"{gap_id} is blocked without explicit evidence requirements")
            if not gap.get("source_preparation"):
                fail(f"{gap_id} has no source-side resume package")
            if not gap.get("unblock_condition"):
                fail(f"{gap_id} has no concrete unblock condition")
    source_open = [gap["id"] for gap in gaps if gap["status"] == "OPEN"]
    if source_open:
        fail(f"actionable source gaps remain open: {source_open}")


def iter_text_files(base: Path):
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in {
            ".dart",
            ".kt",
            ".swift",
            ".py",
            ".json",
            ".toml",
            ".md",
            ".yaml",
            ".yml",
        }:
            yield path


def validate_boundaries() -> None:
    violations = []
    for relative in SCAN_SOURCE:
        base = ROOT / relative
        if not base.exists():
            continue
        for path in iter_text_files(base):
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern in FORBIDDEN_PATTERNS.items():
                if pattern.search(text):
                    violations.append(f"{name}: {path.relative_to(ROOT)}")
    if violations:
        fail("forbidden product boundary material found: " + ", ".join(sorted(violations)))

    even_ai = (ROOT / "lib/services/evenai.dart").read_text(encoding="utf-8")
    sensitive_log_fragments = [
        "combinedText-------",
        "answer----$answer",
        "sendEvenAIReply---text",
        "content---$content",
    ]
    found = [fragment for fragment in sensitive_log_fragments if fragment in even_ai]
    if found:
        fail(f"sensitive legacy logging remains in EvenAI: {found}")


def validate_codex_policy() -> None:
    policy = read_json(ROOT / "services/codex_worker/policy.json")
    if policy.get("allowed_sandboxes") != ["read-only", "workspace-write"]:
        fail("Codex worker sandbox allowlist changed")
    if policy.get("network_access_default") is not False:
        fail("Codex worker network must default to disabled")
    mcp = (ROOT / "adapters/mcp/hepta_glasses_mcp_server.py").read_text(
        encoding="utf-8"
    )
    forbidden_tools = {
        "shell.exec",
        "firmware.flash",
        "credential.read",
        "payment.execute",
        "account.modify",
        "device.write",
    }
    present = sorted(tool for tool in forbidden_tools if f'"{tool}"' in mcp)
    if present:
        fail(f"forbidden MCP mutation tools are present: {present}")


def validate_governance_contract() -> None:
    protection = read_json(ROOT / "contracts/main-branch-protection-v1.json")
    contexts = set(protection.get("required_status_checks", {}).get("contexts", []))
    if contexts != EXPECTED_CHECKS:
        fail(f"branch protection contexts drifted: {sorted(contexts)}")
    reviews = protection.get("required_pull_request_reviews", {})
    if reviews.get("required_approving_review_count", 0) < 1:
        fail("branch protection requires no independent approval")
    if not reviews.get("require_code_owner_reviews"):
        fail("branch protection does not require CODEOWNER review")
    if protection.get("allow_force_pushes") is not False:
        fail("branch protection permits force push")
    if protection.get("allow_deletions") is not False:
        fail("branch protection permits deletion")


def validate_exact_head_workflow() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    expression = "${{ github.event.pull_request.head.sha || github.sha }}"
    if workflow.count(f"ref: {expression}") < 6:
        fail("all CI jobs must explicitly check out the PR head or push SHA")
    for required_job in EXPECTED_CHECKS:
        if required_job not in workflow:
            fail(f"workflow is missing required job {required_job}")
    if f"name: hepta-source-evidence-{expression}" not in workflow:
        fail("source evidence artifact name is not bound to the exact head SHA")
    if "Verify artifact is bound to PR head" not in workflow:
        fail("source evidence workflow lacks an internal exact-head assertion")


def validate_evidence_templates() -> None:
    for name in (
        "android-g1-qualification-scenario.json",
        "ios-g1-qualification-scenario.json",
        "product-release-bundle.template.json",
    ):
        read_json(ROOT / "evidence" / "templates" / name)
    index = read_json(ROOT / "docs/EVIDENCE_INDEX.yaml")
    if index.get("plan_revision") != "2026-08-30-g2":
        fail("Evidence Index is not bound to the canonical g2 plan")


def main() -> int:
    checks = [
        validate_required,
        validate_json_contracts,
        validate_gap_ledger,
        validate_boundaries,
        validate_codex_policy,
        validate_governance_contract,
        validate_exact_head_workflow,
        validate_evidence_templates,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print("repository source contract: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
