#!/usr/bin/env python3
"""Fail-closed repository source-contract validator."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
REVISION = "2026-08-30-g5"
CHECKS = {
    "repository-contracts", "flutter", "android-native", "ios-native",
    "native-sanitizers", "secret-and-boundary-scan", "source-evidence",
}
REQUIRED = {
    "README.md", "AGENTS.md", "UPSTREAM.md", "docs/README.md",
    "docs/CURRENT_STATE.md", "docs/PRODUCT_BOUNDARY.md", "docs/ARCHITECTURE.md",
    "docs/THREAT_MODEL.md", "docs/PRIVACY_MODEL.md", "docs/CAPABILITY_MODEL.md",
    "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
    "docs/development/G3_G8_SOURCE_CLOSURE.md", "docs/development/G4_SOURCE_CLOSURE.md",
    "docs/development/G5_AUDIT_CLOSURE.md", "docs/GAP_LEDGER.yaml",
    "docs/EVIDENCE_INDEX.yaml", "docs/operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md",
    "docs/operations/REALTIME_AND_CAPABILITY_RUNBOOK.md",
    "docs/operations/DEVICE_QUALIFICATION_RUNBOOK.md",
    "docs/operations/REPOSITORY_GOVERNANCE_RUNBOOK.md",
    "docs/operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md",
    "docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md",
    "docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md",
    "contracts/hepta-glasses-runtime-v1.json", "contracts/control-plane-v1.json",
    "contracts/main-branch-protection-v1.json", "contracts/release-gates-v1.json",
    "contracts/qualification-slo-v1.json", "third_party/components.json",
    "third_party/README.md", "lib/runtime/contracts.dart",
    "lib/runtime/audit_journal.dart", "lib/runtime/task_engine.dart",
    "lib/runtime/policy_engine.dart", "lib/runtime/tool_gateway.dart",
    "lib/runtime/device_hal.dart", "lib/runtime/packet_codec.dart",
    "lib/runtime/dual_leg_coordinator.dart", "lib/runtime/model_gateway.dart",
    "lib/runtime/assistant_session.dart", "lib/runtime/device_effect_scheduler.dart",
    "lib/runtime/hepta_runtime.dart", "lib/simulator/g1_digital_twin.dart",
    "services/control_plane/identity.py", "services/control_plane/realtime.py",
    "services/control_plane/capabilities.py", "services/skills/registry.py",
    "services/skills/memory.py", "services/qualification/device_report.py",
    "services/qualification/release_gate.py", "services/qualification/sbom.py",
    "services/qualification/governance.py", "services/codex_worker/worker.py",
    "adapters/mcp/hepta_glasses_mcp_server.py", "tools/qualify_device_trace.py",
    "tools/build_source_evidence.py", "tools/evaluate_release_gate.py",
    "tools/repository_governance.py", "tools/scan_repository_history.py",
    "tools/run_native_sanitizer_tests.sh", ".github/workflows/ci.yml",
    "evidence/templates/android-g1-qualification-scenario.json",
    "evidence/templates/ios-g1-qualification-scenario.json",
    "evidence/templates/product-release-bundle.template.json",
    "evidence/templates/credential-incident-closure.template.json",
    "android/app/src/main/cpp/lc3_decoder_core.h",
    "android/app/src/main/cpp/lc3_decoder_core.cpp",
    "android/app/src/test/kotlin/com/example/demo_ai_even/model/BlePairDeviceTest.kt",
    "ios/RunnerTests/RunnerTests.swift", "native_tests/lc3_decoder_core_test.cpp",
    "native_tests/lc3_decoder_fuzz.cpp",
}
STATUSES = {
    "CLOSED_SOURCE", "CLOSED_VERIFIED", "BLOCKED_EXTERNAL",
    "BLOCKED_ADMIN_SETTING", "BLOCKED_UPSTREAM", "OPEN",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def read_json(relative: str) -> Any:
    try:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        fail(f"invalid JSON/YAML-as-JSON {relative}: {error}")


def contains(relative: str, fragments: tuple[str, ...]) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    missing = [item for item in fragments if item not in text]
    if missing:
        fail(f"{relative} lacks required invariants: {missing}")


def validate_required() -> None:
    missing = sorted(item for item in REQUIRED if not (ROOT / item).is_file())
    if missing:
        fail(f"missing required files: {missing}")
    if len((ROOT / "README.md").read_text(encoding="utf-8").strip()) < 500:
        fail("README.md is not a meaningful product entry point")


def validate_contracts_and_ledger() -> None:
    schemas = sorted((ROOT / "schemas").glob("*.json"))
    if len(schemas) < 12:
        fail("expanded schema set is incomplete")
    for path in schemas:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or doc.get("type") != "object" or not doc.get("required"):
            fail(f"invalid schema contract: {path.relative_to(ROOT)}")
    for path in ("contracts/hepta-glasses-runtime-v1.json", "contracts/control-plane-v1.json", "contracts/main-branch-protection-v1.json", "contracts/release-gates-v1.json", "contracts/qualification-slo-v1.json"):
        read_json(path)
    ledger = read_json("docs/GAP_LEDGER.yaml")
    if ledger.get("plan_revision") != REVISION or not isinstance(ledger.get("gaps"), list) or len(ledger["gaps"]) < 41:
        fail("Gap Ledger is not the complete canonical g5 ledger")
    seen: set[str] = set()
    for gap in ledger["gaps"]:
        if not isinstance(gap, Mapping):
            fail("Gap Ledger contains non-object entry")
        gap_id, status = gap.get("id"), gap.get("status")
        if not isinstance(gap_id, str) or gap_id in seen or status not in STATUSES:
            fail(f"invalid gap identity/status: {gap_id!r}/{status!r}")
        seen.add(gap_id)
        if str(status).startswith("CLOSED") and not gap.get("evidence"):
            fail(f"{gap_id} is closed without evidence")
        if str(status).startswith("BLOCKED") and not all(gap.get(field) for field in ("source_preparation", "evidence_required", "unblock_condition")):
            fail(f"{gap_id} lacks a concrete external resume package")
        if status == "OPEN":
            fail(f"actionable source gap remains open: {gap_id}")
    index = read_json("docs/EVIDENCE_INDEX.yaml")
    if index.get("plan_revision") != REVISION:
        fail("Evidence Index is not bound to g5")


def validate_boundaries() -> None:
    patterns = {
        "provider credential name": re.compile(r"DASHSCOPE_API_KEY|DEEPSEEK_API_KEY|OPENAI_API_KEY"),
        "direct provider endpoint": re.compile(r"api\.deepseek\.com|dashscope\.aliyuncs\.com|api\.openai\.com"),
        "sandbox bypass": re.compile(r"dangerously-bypass-approvals-and-sandbox|--yolo|danger-full-access"),
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    }
    violations: list[str] = []
    for base in ("lib", "android", "ios", "services", "adapters", "plugins"):
        for path in (ROOT / base).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".c", ".cpp", ".dart", ".h", ".json", ".kt", ".m", ".md", ".py", ".swift", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            violations.extend(f"{name}: {path.relative_to(ROOT)}" for name, pattern in patterns.items() if pattern.search(text))
    if violations:
        fail("forbidden boundary material: " + ", ".join(sorted(violations)))
    contains("lib/services/evenai.dart", tuple())


def validate_durable_audit() -> None:
    contains("lib/runtime/audit_journal.dart", ("FileLock.blockingExclusive", "create(exclusive: true)", "staleLockAge", "maxEntryBytes", "torn final record", "await handle.flush()"))
    if "Directory.systemTemp.path" in (ROOT / "lib/main.dart").read_text(encoding="utf-8"):
        fail("product startup silently uses temporary audit storage")
    contains("test/runtime/audit_journal_test.dart", ("independent instances", "separate isolates", "torn final record", "entry and file bounds"))


def validate_supply_chain() -> None:
    manifest = read_json("third_party/components.json")
    components = manifest.get("components") if isinstance(manifest, Mapping) else None
    if manifest.get("schema_version") != 1 or not isinstance(components, list) or len(components) < 2:
        fail("third-party component inventory is incomplete")
    seen: set[str] = set()
    for component in components:
        name = component.get("name") if isinstance(component, Mapping) else None
        if not isinstance(name, str) or not name or name in seen or component.get("license") in {None, "", "NOASSERTION"}:
            fail(f"invalid third-party component: {name!r}")
        seen.add(name)
        paths = component.get("paths")
        if not isinstance(paths, list) or not paths or any(not isinstance(item, str) or not (ROOT / item).exists() for item in paths):
            fail(f"{name} references missing source")
    contains("services/qualification/sbom.py", ("parse_pubspec_lock", "parse_podfile_lock", "parse_gradle_packages", "parse_vendored_components", "relationships", "inventory_summary"))
    contains("tools/build_source_evidence.py", ("credential-history-summary.json", "third_party_manifest", "inventory_summary"))


def validate_policy_governance_release() -> None:
    policy = read_json("services/codex_worker/policy.json")
    if policy.get("allowed_sandboxes") != ["read-only", "workspace-write"] or policy.get("network_access_default") is not False:
        fail("Codex worker boundary widened")
    mcp = (ROOT / "adapters/mcp/hepta_glasses_mcp_server.py").read_text(encoding="utf-8")
    forbidden = {"shell.exec", "firmware.flash", "credential.read", "payment.execute", "account.modify", "device.write"}
    present = sorted(item for item in forbidden if f'"{item}"' in mcp)
    if present:
        fail(f"forbidden MCP mutation tools present: {present}")
    protection = read_json("contracts/main-branch-protection-v1.json")
    contexts = set(protection.get("required_status_checks", {}).get("contexts", []))
    reviews = protection.get("required_pull_request_reviews", {})
    if contexts != CHECKS or protection.get("allow_force_pushes") is not False or protection.get("allow_deletions") is not False or reviews.get("required_approving_review_count", 0) < 1 or not reviews.get("require_code_owner_reviews"):
        fail("branch-protection contract drifted")
    contains("services/qualification/release_gate.py", (REVISION, "credential_incident_closed", "binary_sbom", "artifact_attestation", "native-sanitizers"))


def validate_ci_and_native() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    expression = "${{ github.event.pull_request.head.sha || github.sha }}"
    if workflow.count(f"ref: {expression}") < len(CHECKS) or any(f"  {job}:" not in workflow for job in CHECKS):
        fail("not every canonical CI job checks out the exact head")
    for fragment in ("fetch-depth: 0", "flutter analyze --fatal-warnings", "./gradlew assembleRelease testDebugUnitTest lintDebug", "flutter build ios --release --no-codesign", "xcodebuild test", "tools/run_native_sanitizer_tests.sh", "tools/scan_repository_history.py", "CI_NATIVE_SANITIZERS", f"name: hepta-source-evidence-{expression}"):
        if fragment not in workflow:
            fail(f"CI hardening is missing: {fragment}")
    contains("android/app/src/main/cpp/lc3_decoder_core.cpp", ("catch (const std::bad_alloc&)", "isValidLc3PayloadLength"))
    contains("tools/run_native_sanitizer_tests.sh", ("-fsanitize=address,undefined", "-fsanitize=fuzzer,address,undefined", "-runs=2000"))


def main() -> int:
    for check in (validate_required, validate_contracts_and_ledger, validate_boundaries, validate_durable_audit, validate_supply_chain, validate_policy_governance_release, validate_ci_and_native):
        check()
        print(f"PASS {check.__name__}")
    print("repository source contract: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL {error}", file=sys.stderr)
        raise SystemExit(1)
