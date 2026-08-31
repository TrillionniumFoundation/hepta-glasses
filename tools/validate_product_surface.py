#!/usr/bin/env python3
"""Validate G8 machine truth and the supported mobile product surface."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable


def validate_product_surface(
    root: Path,
    *,
    canonical_revision: str,
    expected_checks: set[str],
    read_json: Callable[[Path], dict[str, object]],
    iter_text_files: Callable[[Path], Iterable[Path]],
    fail: Callable[[str], None],
) -> None:
    state = read_json(root / "docs/PROJECT_STATE.json")
    if state.get("schema_version") != 1:
        fail("Project State schema_version must be 1")
    if state.get("canonical_revision") != canonical_revision:
        fail("Project State revision drifted")
    if state.get("product_stage") != "pre_alpha_qualification":
        fail("Project State overstates or obscures the product stage")
    if state.get("claim_ceiling") != "source_candidate":
        fail("Project State claim ceiling is not source_candidate")
    if state.get("supported_product_platforms") != ["android", "ios"]:
        fail("Project State product platform list must be exactly Android/iOS")

    authority = state.get("source_authority")
    if not isinstance(authority, dict):
        fail("Project State source_authority is missing")
    expected_authority = {
        "repository": "TrillionniumFoundation/hepta-glasses",
        "candidate_branch": "codex/hepta-glasses-gap-closure-g8",
        "pull_request": 23,
        "exact_head_identity": "github_pull_request_head",
        "exact_head_evidence": "github_actions_artifact",
        "self_attested_commit_sha": False,
    }
    for key, expected in expected_authority.items():
        if authority.get(key) != expected:
            fail(f"Project State source authority drifted at {key}")
    if set(authority.get("required_checks", [])) != expected_checks:
        fail("Project State required checks drifted")

    if state.get("declared_repository_actionable_open_gaps") != []:
        fail("Project State declares repository-actionable open gaps")
    expected_external = {f"HG-{number:04d}" for number in range(15, 21)}
    if set(state.get("open_external_gates", [])) != expected_external:
        fail("Project State external gate set drifted")

    rules = state.get("evidence_rules")
    rule_names = (
        "source_implementation_does_not_imply_physical_verification",
        "source_implementation_does_not_imply_production_deployment",
        "any_new_push_invalidates_prior_exact_head_ci_and_review",
        "implementer_must_not_self_approve_or_self_merge",
    )
    if not isinstance(rules, dict) or not all(rules.get(name) is True for name in rule_names):
        fail("Project State evidence rules are incomplete")

    contracts = state.get("source_contracts")
    expected_contracts = {
        "audit_journal": "hepta-jsonl-audit-v2",
        "history_scan_acknowledgements": "exact-fixture-fingerprint-v1",
        "source_release_gate": "release-gates-v1",
        "gap_ledger": "docs/GAP_LEDGER.json",
        "evidence_index": "docs/EVIDENCE_INDEX.json",
    }
    if not isinstance(contracts, dict):
        fail("Project State source contracts are missing")
    for key, expected in expected_contracts.items():
        if contracts.get(key) != expected:
            fail(f"Project State source contract drifted at {key}")

    ledger = read_json(root / "docs/GAP_LEDGER.json")
    by_id = {gap.get("id"): gap for gap in ledger.get("gaps", []) if isinstance(gap, dict)}
    for gap_id in expected_external:
        gap = by_id.get(gap_id)
        if not isinstance(gap, dict) or not str(gap.get("status", "")).startswith("BLOCKED"):
            fail(f"external gate {gap_id} is not truthfully blocked in the ledger")
    if (root / "docs/GAP_LEDGER.yaml").exists() or (root / "docs/EVIDENCE_INDEX.yaml").exists():
        fail("legacy YAML-named JSON ledgers remain")

    pubspec = (root / "pubspec.yaml").read_text(encoding="utf-8")
    if not re.search(r"(?m)^name:\s*hepta_glasses\s*$", pubspec):
        fail("Dart package identity is not hepta_glasses")

    build = (root / "android/app/build.gradle").read_text(encoding="utf-8")
    if 'namespace = "org.trillionnium.heptaglasses"' not in build or (
        'applicationId = "org.trillionnium.heptaglasses"' not in build
    ):
        fail("Android product identity drifted")
    if "kotlin-reflect" in build:
        fail("unused Kotlin reflection runtime remains")
    if "signingConfig signingConfigs.debug" in build:
        fail("release build falls back to the debug signing key")

    android_main = root / "android/app/src/main/kotlin/org/trillionnium/heptaglasses"
    android_test = root / "android/app/src/test/kotlin/org/trillionnium/heptaglasses"
    if not (android_main / "MainActivity.kt").is_file() or not android_test.is_dir():
        fail("canonical Android source or test package path is missing")
    for legacy in (
        root / "android/app/src/main/kotlin/com/example/demo_ai_even",
        root / "android/app/src/test/kotlin/com/example/demo_ai_even",
    ):
        if legacy.exists():
            fail("legacy Android package path remains")

    native = (root / "android/app/src/main/cpp/liblc3.cpp").read_text(encoding="utf-8")
    if "Java_org_trillionnium_heptaglasses_cpp_Cpp_" not in native or (
        "Java_com_example_demo_1ai_1even" in native
    ):
        fail("Android JNI symbols do not match the canonical package")

    manifest = (root / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    if 'android:allowBackup="false"' not in manifest:
        fail("Android backup is not disabled")
    if 'android:usesCleartextTraffic="false"' not in manifest:
        fail("Android release cleartext traffic is not disabled")
    if "PROCESS_TEXT" in manifest or "<queries>" in manifest:
        fail("unrelated Android intent-query surface remains")
    debug_manifest = (root / "android/app/src/debug/AndroidManifest.xml").read_text(encoding="utf-8")
    if 'android:usesCleartextTraffic="true"' not in debug_manifest or (
        'tools:replace="android:usesCleartextTraffic"' not in debug_manifest
    ):
        fail("debug-only cleartext exception is not explicit")

    plist = (root / "ios/Runner/Info.plist").read_text(encoding="utf-8")
    if plist.count("<string>Hepta Glasses</string>") < 2:
        fail("iOS visible product name drifted")
    if "NSPhotoLibraryUsageDescription" in plist:
        fail("unused iOS photo-library permission remains")
    project = (root / "ios/Runner.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    if "PRODUCT_BUNDLE_IDENTIFIER = org.trillionnium.heptaglasses;" not in project:
        fail("iOS bundle identity drifted")

    unsupported = [name for name in ("linux", "macos", "web", "windows") if (root / name).exists()]
    if unsupported:
        fail(f"unsupported Flutter platform templates remain: {unsupported}")
    metadata = (root / ".metadata").read_text(encoding="utf-8")
    for name in ("linux", "macos", "web", "windows"):
        if f"platform: {name}" in metadata:
            fail(f"Flutter metadata still declares unsupported platform {name}")

    legacy = re.compile(r"demo_ai_even|com\.example\.demo_ai_even|Demo Ai Even")
    legacy_files: list[str] = []
    for base in (root / "lib", root / "test", root / "android", root / "ios"):
        for path in iter_text_files(base):
            if legacy.search(path.read_text(encoding="utf-8", errors="replace")):
                legacy_files.append(str(path.relative_to(root)))
    if legacy_files:
        fail(f"legacy demo identity remains in product source: {sorted(legacy_files)}")

    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    if "./gradlew testDebugUnitTest lintDebug" not in workflow:
        fail("Android lint is not part of the required native CI job")
    evidence_builder = (root / "tools/build_source_evidence.py").read_text(encoding="utf-8")
    release_gate = (root / "services/qualification/release_gate.py").read_text(encoding="utf-8")
    if "file-lock-checkpoint-v2" not in evidence_builder or (
        "file-lock-checkpoint-v2" not in release_gate
    ):
        fail("source evidence still accepts the superseded audit contract")
