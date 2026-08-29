
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
    "docs/GAP_LEDGER.yaml",
    "docs/EVIDENCE_INDEX.yaml",
    "contracts/hepta-glasses-runtime-v1.json",
    "lib/runtime/contracts.dart",
    "lib/runtime/audit_journal.dart",
    "lib/runtime/task_engine.dart",
    "lib/runtime/policy_engine.dart",
    "lib/runtime/tool_gateway.dart",
    "lib/runtime/device_hal.dart",
    "lib/runtime/packet_codec.dart",
    "lib/runtime/dual_leg_coordinator.dart",
    "lib/runtime/model_gateway.dart",
    "lib/simulator/g1_digital_twin.dart",
    "services/codex_worker/worker.py",
    "adapters/mcp/hepta_glasses_mcp_server.py",
    ".github/workflows/ci.yml",
}

FORBIDDEN_PATTERNS = {
    "provider key name": re.compile(r"DASHSCOPE_API_KEY|DEEPSEEK_API_KEY|OPENAI_API_KEY"),
    "direct provider endpoint": re.compile(r"api\.deepseek\.com|dashscope\.aliyuncs\.com"),
    "Codex sandbox bypass": re.compile(r"dangerously-bypass-approvals-and-sandbox|--yolo|danger-full-access"),
}

SCAN_SOURCE = ["lib", "android", "ios", "services", "adapters", "plugins"]
ALLOWED_GAP_STATUSES = {
    "CLOSED_SOURCE",
    "CLOSED_VERIFIED",
    "BLOCKED_EXTERNAL",
    "BLOCKED_ADMIN_SETTING",
    "BLOCKED_UPSTREAM",
    "OPEN",
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
    if len((ROOT / "README.md").read_text(encoding="utf-8").strip()) < 200:
        fail("README.md is not a meaningful product entry point")


def validate_json_contracts() -> None:
    for path in sorted((ROOT / "schemas").glob("*.json")):
        document = read_json(path)
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            fail(f"{path.relative_to(ROOT)} is not a draft-2020-12 schema")
        if document.get("type") != "object" or not document.get("required"):
            fail(f"{path.relative_to(ROOT)} lacks an object/required contract")
    read_json(ROOT / "contracts/hepta-glasses-runtime-v1.json")


def validate_gap_ledger() -> None:
    ledger = read_json(ROOT / "docs/GAP_LEDGER.yaml")
    gaps = ledger.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        fail("Gap Ledger has no gaps")
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
        if status.startswith("BLOCKED") and not gap.get("evidence_required"):
            fail(f"{gap_id} is blocked without explicit evidence requirements")
    source_open = [g["id"] for g in gaps if g["status"] == "OPEN"]
    if source_open:
        fail(f"actionable source gaps remain open: {source_open}")


def iter_text_files(base: Path):
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dart", ".kt", ".swift", ".py", ".json", ".toml", ".md"}:
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


def main() -> int:
    checks = [
        validate_required,
        validate_json_contracts,
        validate_gap_ledger,
        validate_boundaries,
        validate_codex_policy,
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
