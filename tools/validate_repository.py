#!/usr/bin/env python3
"""Fail-closed source contract validator with no third-party dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_REVISION = "2026-09-01-g8"
AUDIT_CONTRACT = "file-lock-checkpoint-v2"

REQUIRED = {
    "README.md",
    "AGENTS.md",
    "UPSTREAM.md",
    "docs/README.md",
    "docs/CURRENT_STATE.md",
    "docs/PROJECT_STATE.json",
    "docs/PRODUCT_BOUNDARY.md",
    "docs/PLATFORM_CAPABILITIES.json",
    "docs/ARCHITECTURE.md",
    "docs/THREAT_MODEL.md",
    "docs/PRIVACY_MODEL.md",
    "docs/CAPABILITY_MODEL.md",
    "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
    "docs/development/G3_G8_SOURCE_CLOSURE.md",
    "docs/development/G4_SOURCE_CLOSURE.md",
    "docs/development/G5_AUDIT_CLOSURE.md",
    "docs/development/G7_SOURCE_CONVERGENCE.md",
    "docs/development/G8_SOURCE_REMEDIATION.md",
    "docs/operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md",
    "docs/operations/REALTIME_AND_CAPABILITY_RUNBOOK.md",
    "docs/operations/DEVICE_QUALIFICATION_RUNBOOK.md",
    "docs/operations/REPOSITORY_GOVERNANCE_RUNBOOK.md",
    "docs/operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md",
    "docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md",
    "docs/operations/CREDENTIAL_INCIDENT_RUNBOOK.md",
    "docs/GAP_LEDGER.yaml",
    "docs/EVIDENCE_INDEX.yaml",
    "contracts/hepta-glasses-runtime-v1.json",
    "contracts/control-plane-v1.json",
    "contracts/main-branch-protection-v1.json",
    "contracts/release-gates-v1.json",
    "contracts/qualification-slo-v1.json",
    "contracts/g1-ble-protocol-v1.json",
    "contracts/history-scan-acknowledgements-v1.json",
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
    "lib/runtime/ble_request_slot.dart",
    "lib/adapters/even_g1/even_g1_transport.dart",
    "lib/ble_manager.dart",
    "lib/services/ble.dart",
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
    "android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt",
    "android/app/src/test/kotlin/com/example/demo_ai_even/model/BlePairDeviceTest.kt",
    "ios/Runner/BluetoothManager.swift",
    "ios/RunnerTests/RunnerTests.swift",
    "test/runtime/ble_request_slot_test.dart",
    "test/runtime/ble_manager_authority_test.dart",
    "test/runtime/even_g1_transport_authority_test.dart",
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
    "native-sanitizers",
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
    probes = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "docs/development").glob(".*probe*")
        if path.is_file()
    )
    if probes:
        fail(f"transient connector probes remain in source authority: {probes}")


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
        "g1-ble-protocol-v1.json",
        "history-scan-acknowledgements-v1.json",
    ):
        read_json(ROOT / "contracts" / name)


def validate_gap_ledger() -> None:
    ledger = read_json(ROOT / "docs/GAP_LEDGER.yaml")
    if ledger.get("plan_revision") != CANONICAL_REVISION:
        fail("Gap Ledger is not bound to the canonical revision")
    gaps = ledger.get("gaps")
    if not isinstance(gaps, list) or len(gaps) < 57:
        fail("Gap Ledger does not contain the complete source/external gate set")
    seen = set()
    by_id = {}
    for gap in gaps:
        gap_id = gap.get("id")
        status = gap.get("status")
        if not isinstance(gap_id, str) or gap_id in seen:
            fail(f"invalid or duplicate gap id: {gap_id!r}")
        seen.add(gap_id)
        by_id[gap_id] = gap
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
    for gap_id in ("HG-0055", "HG-0056", "HG-0057"):
        if by_id.get(gap_id, {}).get("status") != "CLOSED_SOURCE":
            fail(f"{gap_id} BLE authority remediation is not source-closed")


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


def validate_canonical_truth() -> None:
    plan = (ROOT / "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md").read_text(
        encoding="utf-8"
    )
    current = (ROOT / "docs/CURRENT_STATE.md").read_text(encoding="utf-8")
    if f"Revision: `{CANONICAL_REVISION}`" not in plan:
        fail("canonical plan revision drifted")
    if f"Canonical plan revision: `{CANONICAL_REVISION}`" not in current:
        fail("Current State revision drifted")
    release = read_json(ROOT / "contracts/release-gates-v1.json")
    if release.get("contracts_version") != CANONICAL_REVISION:
        fail("release-gate contract revision drifted")
    template = read_json(
        ROOT / "evidence/templates/product-release-bundle.template.json"
    )
    source = template.get("source")
    if not isinstance(source, dict) or source.get("contracts_version") != CANONICAL_REVISION:
        fail("product evidence template revision drifted")

    if source.get("audit_contract") != AUDIT_CONTRACT:
        fail("product evidence template audit contract drifted")
    audit_source = (ROOT / "lib/runtime/audit_journal.dart").read_text(
        encoding="utf-8"
    )
    if (
        f"static const String contractVersion = '{AUDIT_CONTRACT}';"
        not in audit_source
    ):
        fail("runtime audit contract drifted")
    release_gate_source = (
        ROOT / "services/qualification/release_gate.py"
    ).read_text(encoding="utf-8")
    if AUDIT_CONTRACT not in release_gate_source:
        fail("release gate audit contract drifted")
    evidence_builder_source = (
        ROOT / "tools/build_source_evidence.py"
    ).read_text(encoding="utf-8")
    if evidence_builder_source.count(AUDIT_CONTRACT) < 2:
        fail("source evidence audit contract drifted")

    project_state = read_json(ROOT / "docs/PROJECT_STATE.json")
    if project_state.get("plan_revision") != CANONICAL_REVISION:
        fail("machine-readable Project State revision drifted")
    if project_state.get("program_increment") != "G8":
        fail("machine-readable Project State increment drifted")
    platform = read_json(ROOT / "docs/PLATFORM_CAPABILITIES.json")
    if platform.get("physical_qualification") != "blocked_external":
        fail("platform capability matrix overclaims physical qualification")
    protocol = read_json(ROOT / "contracts/g1-ble-protocol-v1.json")
    if protocol.get("contract_id") != "hepta-g1-ble-protocol-v1":
        fail("G1 BLE protocol contract identity drifted")


def validate_ble_authority() -> None:
    transport = (
        ROOT / "lib/adapters/even_g1/even_g1_transport.dart"
    ).read_text(encoding="utf-8")
    manager = (ROOT / "lib/ble_manager.dart").read_text(encoding="utf-8")
    slots = (ROOT / "lib/runtime/ble_request_slot.dart").read_text(
        encoding="utf-8"
    )
    ios = (ROOT / "ios/Runner/BluetoothManager.swift").read_text(
        encoding="utf-8"
    )
    android = (
        ROOT
        / "android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt"
    ).read_text(encoding="utf-8")
    transport_test = (
        ROOT / "test/runtime/even_g1_transport_authority_test.dart"
    ).read_text(encoding="utf-8")
    manager_test = (
        ROOT / "test/runtime/ble_manager_authority_test.dart"
    ).read_text(encoding="utf-8")
    ios_test = (ROOT / "ios/RunnerTests/RunnerTests.swift").read_text(
        encoding="utf-8"
    )

    transport_fragments = (
        "pairIdentity",
        "generation",
        "side",
        "payloadDigest",
        "expectedGeneration",
        "expectedPairIdentity",
        "idempotency_authority_capacity_exhausted",
    )
    if any(fragment not in transport for fragment in transport_fragments):
        fail("public BLE transport does not bind complete idempotency authority")

    manager_fragments = (
        "clearQuarantineForGeneration(retiredGeneration)",
        "takePendingWhere",
        "expected_generation_mismatch_before_write",
        "expected_pair_mismatch_before_write",
        "request_slot_quarantined",
    )
    if any(fragment not in manager for fragment in manager_fragments):
        fail("Flutter BLE request authority or scoped quarantine drifted")
    disconnect_section = manager.split("void _onGlassesDisconnected", 1)[1].split(
        "void _onPairedGlassesFound", 1
    )[0]
    if "clearQuarantine" in disconnect_section:
        fail("disconnect path globally clears uncertain-write quarantine")
    if "clearQuarantineForGenerationSide" not in slots:
        fail("BLE request registry lacks exact-leg reconciliation release")

    ios_fragments = (
        "PeripheralAttemptToken",
        "ConnectionAttemptAuthority",
        "RetiredConnectionBarrier",
        "PeripheralAttemptDelegate",
        "guard owns(peripheral, token: token)",
        "expectedAuthorityMatches",
    )
    if any(fragment not in ios for fragment in ios_fragments):
        fail("iOS callbacks are not bound to immutable connection attempts")
    if "else { return \"R\" }" in ios or "? \"L\" : \"R\"" in ios:
        fail("iOS callback side has an unsafe right-leg fallback")

    for native_source, name in ((android, "Android"), (ios, "iOS")):
        if (
            "expectedGeneration" not in native_source
            or "expectedPairIdentity" not in native_source
        ):
            fail(f"{name} native writer does not enforce captured authority")

    test_fragments = (
        "same caller key cannot alias left and right legs",
        "same caller key is a new authority after reconnect generation",
        "same caller key is a new authority for a different pair",
        "same scoped authority rejects argument drift",
    )
    if any(fragment not in transport_test for fragment in test_fragments):
        fail("hostile transport authority regression set is incomplete")
    if "left disconnect cannot release an uncertain right-leg write" not in manager_test:
        fail("one-leg disconnect quarantine regression is missing")
    if "testGenerationNTokenCannotOwnGenerationNPlusOne" not in ios_test:
        fail("iOS stale-attempt regression is missing")

    protocol = read_json(ROOT / "contracts/g1-ble-protocol-v1.json")
    authority = protocol.get("authority")
    if protocol.get("version", 0) < 2 or not isinstance(authority, dict):
        fail("machine-readable BLE authority contract is missing")
    idempotency = authority.get("idempotency_identity", [])
    required_identity = {
        "pair_identity",
        "connection_generation",
        "side",
        "caller_idempotency_key",
        "payload_sha256",
    }
    if set(idempotency) != required_identity:
        fail("machine-readable BLE idempotency identity drifted")
    quarantine = authority.get("uncertain_write_quarantine", {})
    if quarantine.get("opposite_leg_disconnect_releases") is not False:
        fail("BLE contract permits opposite-leg quarantine release")


def validate_single_ci_authority() -> None:
    workflows = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / ".github/workflows").glob("*.yml")
    )
    if workflows != [".github/workflows/ci.yml"]:
        fail(f"temporary or competing workflow authority remains: {workflows}")
    sanitizer = ROOT / "tools/run_native_sanitizers.sh"
    if sanitizer.stat().st_mode & 0o111 == 0:
        fail("native sanitizer runner is not executable")


def validate_history_gate() -> None:
    acknowledgement_contract = read_json(
        ROOT / "contracts/history-scan-acknowledgements-v1.json"
    )
    acknowledgements = acknowledgement_contract.get("acknowledgements")
    if acknowledgement_contract.get("schema_version") != 1 or not isinstance(
        acknowledgements, list
    ):
        fail("history acknowledgement contract is malformed")
    if not acknowledgements:
        fail("history acknowledgement contract is unexpectedly empty")
    for acknowledgement in acknowledgements:
        if acknowledgement.get("classification") != "synthetic_test_fixture":
            fail("history acknowledgement is broader than a synthetic fixture")
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(acknowledgement.get("fingerprint", ""))
        ):
            fail("history acknowledgement lacks an exact SHA-256 fingerprint")
    scanner = (ROOT / "tools/scan_git_history.py").read_text(encoding="utf-8")
    required = (
        "unscanned_blob_count",
        "MAX_BLOB_BYTES = 16 * 1024 * 1024",
        'report["unscanned_blob_count"]',
        "unused_acknowledgement_count",
        "synthetic_test_fixture",
    )
    if any(fragment not in scanner for fragment in required):
        fail("history scanner does not fail closed on unscanned blobs")
    release = (ROOT / "services/qualification/release_gate.py").read_text(
        encoding="utf-8"
    )
    if 'int(history.get("unscanned_blob_count", -1)) == 0' not in release:
        fail("release gate does not reject incomplete history scans")


def validate_codex_policy() -> None:
    policy = read_json(ROOT / "services/codex_worker/policy.json")
    if policy.get("allowed_sandboxes") != ["read-only", "workspace-write"]:
        fail("Codex worker sandbox allowlist changed")
    if policy.get("network_access_default") is not False:
        fail("Codex worker network must default to disabled")
    isolation = policy.get("network_isolation_command")
    if not isinstance(isolation, list) or not isolation:
        fail("Codex worker has no mandatory network-isolation command")
    if int(policy.get("maximum_workspace_entries", 0)) < 1:
        fail("Codex worker workspace traversal is unbounded")
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
    if workflow.count(f"ref: {expression}") < 7:
        fail("all CI jobs must explicitly check out the PR head or push SHA")
    for required_job in EXPECTED_CHECKS:
        if required_job not in workflow:
            fail(f"workflow is missing required job {required_job}")
    if f"name: hepta-source-evidence-{expression}" not in workflow:
        fail("source evidence artifact name is not bound to the exact head SHA")
    exact_head_fragments = (
        "source-evidence-summary.json",
        "summary['commit'] != expected",
        "SOURCE_HEAD_SHA",
    )
    if any(fragment not in workflow for fragment in exact_head_fragments):
        fail("source evidence workflow lacks an internal exact-head assertion")
    native_test_fragments = (
        "./gradlew testDebugUnitTest",
        "xcodebuild test",
        "Run iOS native tests",
    )
    if any(fragment not in workflow for fragment in native_test_fragments):
        fail("workflow does not execute Android and iOS native tests")


def validate_evidence_templates() -> None:
    for name in (
        "android-g1-qualification-scenario.json",
        "ios-g1-qualification-scenario.json",
        "product-release-bundle.template.json",
    ):
        read_json(ROOT / "evidence" / "templates" / name)
    index = read_json(ROOT / "docs/EVIDENCE_INDEX.yaml")
    if index.get("plan_revision") != CANONICAL_REVISION:
        fail("Evidence Index is not bound to the canonical revision")


def main() -> int:
    checks = [
        validate_required,
        validate_json_contracts,
        validate_gap_ledger,
        validate_boundaries,
        validate_canonical_truth,
        validate_ble_authority,
        validate_single_ci_authority,
        validate_history_gate,
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
