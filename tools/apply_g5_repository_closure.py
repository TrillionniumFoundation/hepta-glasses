#!/usr/bin/env python3
"""Apply deterministic G5 migrations that require existing-file context."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "2026-08-31-g5"


def write(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def patch_lc3_bits(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    helper = """
static inline uint32_t lc3_safe_shift_left_u32(uint32_t value, unsigned shift)
{
    return shift >= 32U ? 0U : value << shift;
}
"""
    if "lc3_safe_shift_left_u32" not in text:
        marker = '#include "bits.h"\n'
        if marker not in text:
            raise SystemExit(f"missing bits include marker in {path}")
        text = text.replace(marker, marker + helper, 1)
    replacements = {
        "bits->cache <<= nbits;": (
            "bits->cache = lc3_safe_shift_left_u32(bits->cache, "
            "(unsigned)nbits);"
        ),
        "bits->cache <<= n;": (
            "bits->cache = lc3_safe_shift_left_u32(bits->cache, (unsigned)n);"
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if "lc3_safe_shift_left_u32(bits->cache" not in text:
        raise SystemExit(f"unsafe LC3 cache shift was not located in {path}")
    write(path, text)


def patch_rnnoise(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"(DenoiseState \*st\s*=\s*malloc\(rnnoise_get_size\(\)\);\s*)"
        r"(rnnoise_init\(st, model\);)",
        r"\1if (st == NULL) return NULL;\n  \2",
        text,
        count=1,
    )
    if "st == NULL || out == NULL || x == NULL" not in text:
        text = re.sub(
            r"(float rnnoise_process_frame\([^\n]+\)\s*\{)",
            r"\1\n  if (st == NULL || out == NULL || x == NULL) return 0.0f;",
            text,
            count=1,
        )
    write(path, text)


def patch_tool_gateway(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("return _recordTerminal(", "return await _recordTerminal(")
    write(path, text)


def patch_plan() -> None:
    path = ROOT / "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("Revision: `2026-08-30-g4`", f"Revision: `{REVISION}`")
    text = text.replace(
        "Supersedes: `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
        "Supersedes: `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
    )
    if "## 6. G5 independent-audit closure" not in text:
        text += """

## 6. G5 independent-audit closure

G5 closes repository-side evidence and durability defects without promoting
source evidence into product evidence:

1. the audit journal uses a stable OS advisory lock across instances and a
   journal-before-checkpoint crash-recovery contract;
2. production startup fails closed when durable application-support storage is
   unavailable;
3. the source SBOM covers Dart/Pub, Android/Gradle, iOS/CocoaPods, and vendored
   native components with dependency and containment relationships;
4. every fetched Git ref and deduplicated blob is scanned without emitting
   possible secret material;
5. Android and iOS LC3 copies plus RNNoise execute under ASAN/UBSAN, and LC3
   cross-platform PCM parity is required;
6. the release gate recomputes artifact digests and validates report contents;
7. analyzer warnings are fatal, while product release still requires E5-E7.
"""
    write(path, text)


def patch_ledger() -> None:
    path = ROOT / "docs/GAP_LEDGER.yaml"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["schema_version"] = 4
    ledger["plan_revision"] = REVISION
    ledger["g5_parent_commit"] = "ac2cf9aa428e2e8e7821684aafc89da30bf78b1a"
    gaps = ledger["gaps"]
    existing = {gap["id"] for gap in gaps}
    additions = [
        {
            "id": "HG-0035",
            "title": "Audit journal lacked cross-instance OS locking and crash checkpoint recovery",
            "status": "CLOSED_SOURCE",
            "owner": "runtime",
            "evidence": [
                "lib/runtime/audit_journal.dart",
                "test/runtime/audit_journal_test.dart"
            ]
        },
        {
            "id": "HG-0036",
            "title": "Source SBOM omitted Gradle, CocoaPods, and vendored native components",
            "status": "CLOSED_SOURCE",
            "owner": "release",
            "evidence": [
                "services/qualification/sbom.py",
                "services/qualification/test_sbom.py",
                "third_party/native-components.json"
            ]
        },
        {
            "id": "HG-0037",
            "title": "No redacted all-history secret scan bound to the exact source head",
            "status": "CLOSED_SOURCE",
            "owner": "security",
            "evidence": [
                "tools/scan_git_history.py",
                "services/qualification/test_history_scan.py",
                ".github/workflows/ci.yml"
            ]
        },
        {
            "id": "HG-0038",
            "title": "Release gate accepted digest-shaped metadata without recomputing artifacts",
            "status": "CLOSED_SOURCE",
            "owner": "release",
            "evidence": [
                "services/qualification/release_gate.py",
                "services/qualification/test_release_gate.py",
                "tools/evaluate_release_gate.py"
            ]
        },
        {
            "id": "HG-0039",
            "title": "Vendored LC3 and RNNoise provenance and license inventory was incomplete",
            "status": "CLOSED_SOURCE",
            "owner": "native-audio",
            "evidence": [
                "third_party/native-components.json",
                "services/qualification/sbom.py"
            ]
        },
        {
            "id": "HG-0040",
            "title": "Native decoders were not exercised under ASAN/UBSAN with cross-platform parity",
            "status": "CLOSED_SOURCE",
            "owner": "native-audio",
            "evidence": [
                "tools/run_native_sanitizers.sh",
                "tools/native/lc3_sanitizer_harness.c",
                "tools/native/rnnoise_sanitizer_harness.c",
                "android/app/src/main/cpp/liblc3/bits.c",
                "ios/Runner/lc3/bits.c",
                ".github/workflows/ci.yml"
            ]
        },
        {
            "id": "HG-0041",
            "title": "G5 requires independent review, protected-main integration, and post-merge exact-head evidence",
            "status": "BLOCKED_EXTERNAL",
            "owner": "maintainer",
            "source_preparation": [
                "docs/CURRENT_STATE.md",
                ".github/workflows/ci.yml",
                "contracts/main-branch-protection-v1.json"
            ],
            "evidence_required": [
                "independent non-author approval",
                "non-bypass merge into protected main",
                "successful CI bound to the resulting main commit and tree"
            ],
            "unblock_condition": "An independent maintainer approves and merges the exact G5 head, then the resulting main commit produces and passes a newly downloaded exact-head evidence bundle."
        },
        {
            "id": "HG-0042",
            "title": "Provider-side rotation or revocation evidence for historical credentials is absent",
            "status": "BLOCKED_EXTERNAL",
            "owner": "security-operations",
            "source_preparation": [
                "tools/scan_git_history.py",
                "docs/operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md"
            ],
            "evidence_required": [
                "provider-console key identifier",
                "rotation or revocation timestamp",
                "redacted operator evidence"
            ],
            "unblock_condition": "A provider administrator attaches redacted evidence that every potentially exposed key identifier is rotated or revoked; no credential material may enter the repository."
        },
        {
            "id": "HG-0043",
            "title": "Signed binary SBOM and verifiable release attestation are absent",
            "status": "BLOCKED_EXTERNAL",
            "owner": "release",
            "source_preparation": [
                "services/qualification/release_gate.py",
                "tools/evaluate_release_gate.py",
                "docs/operations/RELEASE_AND_ROLLBACK_RUNBOOK.md"
            ],
            "evidence_required": [
                "signed Android release binary",
                "signed iOS release archive",
                "binary SBOMs",
                "verifiable release provenance or artifact attestation"
            ],
            "unblock_condition": "The protected release environment signs both platform artifacts, publishes binary SBOMs and an independently verifiable attestation, and the product gate validates them."
        }
    ]
    for gap in additions:
        if gap["id"] not in existing:
            gaps.append(gap)
    write(path, json.dumps(ledger, indent=2))


def patch_evidence_index() -> None:
    path = ROOT / "docs/EVIDENCE_INDEX.yaml"
    index = json.loads(path.read_text(encoding="utf-8"))
    index["schema_version"] = 4
    index["plan_revision"] = REVISION
    if not any(item.get("id") == "EV-SRC-G5-V1" for item in index["source_records"]):
        index["source_records"].append(
            {
                "id": "EV-SRC-G5-V1",
                "path": "docs/development/G5_AUDIT_CLOSURE.md",
                "levels": ["E0", "E1", "E2", "E3", "E4"],
                "claim": "G5 file-lock/checkpoint audit durability, multi-ecosystem SBOM, history scan, native sanitizers/parity, and content-verified source gate"
            }
        )
    required = index["ci_records"]["required_files"]
    for filename in ("source-history-scan.json", "source-native-sanitizer.json"):
        if filename not in required:
            required.append(filename)
    write(path, json.dumps(index, indent=2))


def patch_contracts() -> None:
    path = ROOT / "contracts/main-branch-protection-v1.json"
    protection = json.loads(path.read_text(encoding="utf-8"))
    contexts = protection["required_status_checks"]["contexts"]
    if "native-sanitizers" not in contexts:
        contexts.insert(contexts.index("source-evidence"), "native-sanitizers")
    write(path, json.dumps(protection, indent=2))

    path = ROOT / "contracts/release-gates-v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["version"] = 2
    for field in (
        "native-sanitizers",
        "sbom_ecosystems",
        "history_scan_sha256",
        "history_scan_zero_findings",
        "native_sanitizer_sha256",
        "native_cross_platform_parity",
        "audit_contract",
        "artifact_content_verification",
    ):
        if field not in contract["source_gate"]["required"]:
            contract["source_gate"]["required"].append(field)
    for field in (
        "production_identity",
        "platform_attestation",
        "production_capabilities",
        "vendor_firmware_authority",
        "accessibility_review",
        "credential_rotation_evidence",
        "binary_sbom",
        "verified_release_attestation",
    ):
        if field not in contract["product_gate"]["required"]:
            contract["product_gate"]["required"].append(field)
    write(path, json.dumps(contract, indent=2))

    path = ROOT / "evidence/templates/product-release-bundle.template.json"
    template = json.loads(path.read_text(encoding="utf-8"))
    template["source"]["contracts_version"] = REVISION
    template.setdefault("production", {}).update(
        {
            "identity": "pending",
            "attestation": "pending",
            "capabilities": "pending",
            "firmware_authority": "pending",
        }
    )
    template["drills"]["credential_rotation"] = "pending"
    template["signing"]["attestation_verified"] = False
    write(path, json.dumps(template, indent=2))

    path = ROOT / "schemas/release-evidence-bundle.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["properties"]["production"] = {"type": "object"}
    write(path, json.dumps(schema, indent=2))


def patch_validator() -> None:
    path = ROOT / "tools/validate_repository.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace('"2026-08-30-g4"', f'"{REVISION}"')
    text = text.replace("len(gaps) < 34", "len(gaps) < 43")
    additions = {
        '    "docs/development/G4_SOURCE_CLOSURE.md",': '    "docs/development/G4_SOURCE_CLOSURE.md",\n    "docs/development/G5_AUDIT_CLOSURE.md",',
        '    "services/qualification/sbom.py",': '    "services/qualification/sbom.py",\n    "third_party/native-components.json",',
        '    "tools/repository_governance.py",': '    "tools/repository_governance.py",\n    "tools/scan_git_history.py",\n    "tools/run_native_sanitizers.sh",\n    "tools/native/lc3_sanitizer_harness.c",\n    "tools/native/rnnoise_sanitizer_harness.c",',
        '    "repository-contracts",\n    "secret-and-boundary-scan",': '    "repository-contracts",\n    "secret-and-boundary-scan",\n    "native-sanitizers",',
    }
    for old, new in additions.items():
        if new not in text:
            text = text.replace(old, new)
    text = text.replace(
        'if workflow.count(f"ref: {expression}") < 6:',
        'if workflow.count(f"ref: {expression}") < 7:',
    )
    if '        "run_native_sanitizers.sh",' not in text:
        text = text.replace(
            '        "Run iOS native tests",\n    )',
            '        "Run iOS native tests",\n        "run_native_sanitizers.sh",\n        "scan_git_history.py",\n    )',
        )
    write(path, text)


def main() -> int:
    for relative in (
        "android/app/src/main/cpp/liblc3/bits.c",
        "ios/Runner/lc3/bits.c",
    ):
        patch_lc3_bits(ROOT / relative)
    patch_rnnoise(ROOT / "android/app/src/main/cpp/rnnoise/denoise.c")
    patch_tool_gateway(ROOT / "lib/runtime/tool_gateway.dart")
    patch_plan()
    patch_ledger()
    patch_evidence_index()
    patch_contracts()
    patch_validator()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
