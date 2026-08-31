#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace(path: str, old: str, new: str, *, required: bool = True) -> None:
    value = text(path)
    if required and old not in value:
        raise SystemExit(f"missing replacement anchor in {path}: {old!r}")
    write(path, value.replace(old, new))


def replace_tree(roots: tuple[str, ...], old: str, new: str) -> None:
    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file() or ".git" in path.parts or path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".jar", ".so", ".a", ".zip", ".gz"}:
                continue
            try:
                value = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if old in value:
                path.write_text(value.replace(old, new), encoding="utf-8")


text_roots = (
    "README.md", "AGENTS.md", ".github", "contracts", "docs", "evidence",
    "lib", "test", "tools", "services", "adapters", "plugins", "android", "ios",
)
replace_tree(text_roots, "2026-08-31-g7", "2026-08-31-g8")
replace_tree(text_roots, "docs/GAP_LEDGER.yaml", "docs/GAP_LEDGER.json")
replace_tree(text_roots, "docs/EVIDENCE_INDEX.yaml", "docs/EVIDENCE_INDEX.json")
replace_tree(text_roots, "GAP_LEDGER.yaml", "GAP_LEDGER.json")
replace_tree(text_roots, "EVIDENCE_INDEX.yaml", "EVIDENCE_INDEX.json")
replace_tree(("lib", "test"), "package:demo_ai_even/", "package:hepta_glasses/")
replace_tree(text_roots, "docs/development/G3_G8_SOURCE_CLOSURE.md", "docs/history/source-closure/G3_G8_SOURCE_CLOSURE.md")
replace_tree(text_roots, "docs/development/G4_SOURCE_CLOSURE.md", "docs/history/source-closure/G4_SOURCE_CLOSURE.md")
replace_tree(text_roots, "docs/development/G5_AUDIT_CLOSURE.md", "docs/history/source-closure/G5_AUDIT_CLOSURE.md")
replace_tree(text_roots, "docs/development/G7_SOURCE_CONVERGENCE.md", "docs/history/source-closure/G7_SOURCE_CONVERGENCE.md")

for old, new in (
    ("docs/GAP_LEDGER.yaml", "docs/GAP_LEDGER.json"),
    ("docs/EVIDENCE_INDEX.yaml", "docs/EVIDENCE_INDEX.json"),
    ("docs/development/G3_G8_SOURCE_CLOSURE.md", "docs/history/source-closure/G3_G8_SOURCE_CLOSURE.md"),
    ("docs/development/G4_SOURCE_CLOSURE.md", "docs/history/source-closure/G4_SOURCE_CLOSURE.md"),
    ("docs/development/G5_AUDIT_CLOSURE.md", "docs/history/source-closure/G5_AUDIT_CLOSURE.md"),
    ("docs/development/G7_SOURCE_CONVERGENCE.md", "docs/history/source-closure/G7_SOURCE_CONVERGENCE.md"),
):
    source, target = ROOT / old, ROOT / new
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

history_warning = (
    "> Historical record only. Current authority is `docs/PROJECT_STATE.json`, "
    "the G8 canonical plan, and `docs/development/G8_SOURCE_CONVERGENCE.md`.\n\n"
)
for name in ("G3_G8_SOURCE_CLOSURE.md", "G4_SOURCE_CLOSURE.md", "G5_AUDIT_CLOSURE.md", "G7_SOURCE_CONVERGENCE.md"):
    path = ROOT / "docs/history/source-closure" / name
    value = path.read_text(encoding="utf-8")
    if history_warning.strip() not in value:
        lines = value.splitlines(keepends=True)
        lines.insert(1 if lines else 0, "\n" + history_warning)
        path.write_text("".join(lines), encoding="utf-8")

replace("pubspec.yaml", "name: demo_ai_even", "name: hepta_glasses")

replace_tree(("android/app/src/main/kotlin", "android/app/src/test/kotlin"), "com.example.demo_ai_even", "org.trillionnium.heptaglasses")
for scope in ("main", "test"):
    old = ROOT / f"android/app/src/{scope}/kotlin/com/example/demo_ai_even"
    new = ROOT / f"android/app/src/{scope}/kotlin/org/trillionnium/heptaglasses"
    if old.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        if new.exists():
            shutil.rmtree(new)
        shutil.move(str(old), str(new))
        for parent in [old.parent, old.parent.parent, old.parent.parent.parent]:
            try:
                parent.rmdir()
            except OSError:
                pass
replace("android/app/build.gradle", 'namespace = "com.example.demo_ai_even"', 'namespace = "org.trillionnium.heptaglasses"')
replace("android/app/build.gradle", '    implementation "org.jetbrains.kotlin:kotlin-reflect:$kotlin_version"\n', "", required=False)
replace("android/app/build.gradle", "            signingConfig signingConfigs.debug\n", "", required=False)
replace_tree(("android/app/src/main/cpp",), "Java_com_example_demo_1ai_1even_cpp_Cpp_", "Java_org_trillionnium_heptaglasses_cpp_Cpp_")

manifest = text("android/app/src/main/AndroidManifest.xml")
manifest = manifest.replace(
    'android:label="Hepta Glasses"\n        android:name="${applicationName}"',
    'android:label="Hepta Glasses"\n        android:name="${applicationName}"\n        android:allowBackup="false"\n        android:usesCleartextTraffic="false"',
)
manifest = re.sub(r"\n    <!-- Required to query activities[^<]*<queries>.*?</queries>\n", "\n", manifest, flags=re.S)
write("android/app/src/main/AndroidManifest.xml", manifest)
write(
    "android/app/src/debug/AndroidManifest.xml",
    """<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\"\n    xmlns:tools=\"http://schemas.android.com/tools\">\n    <application\n        android:usesCleartextTraffic=\"true\"\n        tools:replace=\"android:usesCleartextTraffic\" />\n</manifest>\n""",
)

plist = text("ios/Runner/Info.plist")
plist = plist.replace("<string>Demo Ai Even</string>", "<string>Hepta Glasses</string>")
plist = plist.replace("<string>demo_ai_even</string>", "<string>Hepta Glasses</string>")
plist = re.sub(r"\n\s*<key>NSPhotoLibraryUsageDescription</key>\n\s*<string>.*?</string>", "", plist)
write("ios/Runner/Info.plist", plist)

for name in ("linux", "macos", "web", "windows", ".vscode"):
    path = ROOT / name
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
write(
    ".metadata",
    """# This file tracks properties of this Flutter project.\n# Used by Flutter tool to assess capabilities and perform upgrades etc.\n#\n# This file should be version controlled and should not be manually edited.\n\nversion:\n  revision: \"0b8abb4724aa590dd0f429683339b1e045a1594d\"\n  channel: \"stable\"\n\nproject_type: app\n\nmigration:\n  platforms:\n    - platform: root\n      create_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n      base_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n    - platform: android\n      create_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n      base_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n    - platform: ios\n      create_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n      base_revision: 0b8abb4724aa590dd0f429683339b1e045a1594d\n\n  unmanaged_files:\n    - 'lib/main.dart'\n    - 'ios/Runner.xcodeproj/project.pbxproj'\n""",
)

matrix_path = ROOT / "docs/architecture/PLATFORM_CAPABILITY_MATRIX.md"
if matrix_path.exists():
    matrix = matrix_path.read_text(encoding="utf-8")
    marker = "## Evidence status vocabulary"
    if marker not in matrix:
        heading = "# Platform Capability Matrix\n"
        replacement = heading + "\nThis matrix describes the current G8 source candidate. It does not imply physical-device, deployed-production, independent-review, signing, pilot, rollout, or store evidence.\n\n## Evidence status vocabulary\n\n- `CONTRACT_ONLY` — a contract exists, but no source implementation is claimed.\n- `SOURCE_IMPLEMENTED` — source exists; hosted CI or physical evidence may still be pending.\n- `CI_VERIFIED` — the unchanged exact head passed the required hosted check.\n- `PHYSICAL_PENDING` — source exists, but real phone/G1 qualification is required.\n- `UNSUPPORTED` — the product does not currently expose the capability.\n- `BLOCKED_EXTERNAL` — completion depends on deployed, vendor, reviewer, signing, pilot, rollout, or store authority.\n"
        matrix = matrix.replace(heading, replacement, 1)
    matrix_path.write_text(matrix, encoding="utf-8")

for path in (
    "tools/build_source_evidence.py",
    "services/qualification/release_gate.py",
    "services/qualification/test_release_gate.py",
    "evidence/templates/product-release-bundle.template.json",
):
    replace(path, "file-lock-checkpoint-v1", "file-lock-checkpoint-v2")
replace(".github/workflows/ci.yml", "./gradlew testDebugUnitTest\n", "./gradlew testDebugUnitTest lintDebug\n")

ledger_path = ROOT / "docs/GAP_LEDGER.json"
ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
ledger["plan_revision"] = "2026-08-31-g8"
ledger["updated_at"] = "2026-08-31"
by_id = {gap["id"]: gap for gap in ledger["gaps"]}
by_id["HG-0017"].update(
    title="Canonical main branch protection completeness lacks authorized administration readback",
    status="BLOCKED_ADMIN_SETTING",
    owner="repository-admin",
    evidence=[
        "docs/operations/REPOSITORY_GOVERNANCE_RUNBOOK.md",
        "contracts/main-branch-protection-v1.json",
        "tools/repository_governance.py",
        "github:issue/26",
    ],
)
by_id["HG-0042"]["evidence"] = ["docs/development/G8_SOURCE_CONVERGENCE.md"]
by_id["HG-0043"]["evidence"] = ["docs/development/G8_SOURCE_CONVERGENCE.md"]
by_id["HG-0043"]["source_preparation"] = ["docs/development/G8_SOURCE_CONVERGENCE.md"]
by_id["HG-0050"]["evidence"] = ["docs/development/G8_SOURCE_CONVERGENCE.md"]
new_gaps = [
    ("HG-0052", "Exact-head CI formatting, analyzer, Android JVM, history-fixture, and audit serialization blockers are closed", [".github/workflows/ci.yml", "contracts/history-scan-acknowledgements-v1.json", "lib/runtime/audit_journal.dart"]),
    ("HG-0053", "Legacy demo identity and unsupported Flutter platform templates are removed", ["pubspec.yaml", "android/app/build.gradle", "ios/Runner/Info.plist", "docs/PROJECT_STATE.json"]),
    ("HG-0054", "Machine-readable current Project State is authoritative", ["docs/PROJECT_STATE.json", "docs/CURRENT_STATE.md"]),
    ("HG-0055", "Mobile release defaults and permission surface are hardened", ["android/app/src/main/AndroidManifest.xml", "android/app/src/debug/AndroidManifest.xml", "ios/Runner/Info.plist"]),
    ("HG-0056", "Android lint is part of the required native CI job", [".github/workflows/ci.yml"]),
    ("HG-0057", "Audit-journal source evidence and release gate require the v2 contract", ["tools/build_source_evidence.py", "services/qualification/release_gate.py", "evidence/templates/product-release-bundle.template.json"]),
]
for gap_id, title, evidence in new_gaps:
    if gap_id not in by_id:
        ledger["gaps"].append({"id": gap_id, "title": title, "status": "CLOSED_SOURCE", "owner": "source-platform", "evidence": evidence})
ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

index_path = ROOT / "docs/EVIDENCE_INDEX.json"
index = json.loads(index_path.read_text(encoding="utf-8"))
index["schema_version"] = 5
index["plan_revision"] = "2026-08-31-g8"
index["generated_at"] = "2026-08-31"
path_map = {
    "EV-SRC-G3-G8-V1": ("docs/history/source-closure/G3_G8_SOURCE_CLOSURE.md", "Historical G3-G8 contract and evidence-harness foundation; current authority is the G8 Project State and convergence record."),
    "EV-SRC-G4-EXACT-HEAD-V1": ("docs/history/source-closure/G4_SOURCE_CLOSURE.md", "Historical G4 exact-head source evidence only; it does not attest the current G8 tree."),
    "EV-SRC-G5-AUDIT-V1": ("docs/history/source-closure/G5_AUDIT_CLOSURE.md", "Historical G5 audit controls incorporated into G8; prior red CI runs are not E4 evidence."),
    "EV-SRC-G7-CANDIDATE-V1": ("docs/history/source-closure/G7_SOURCE_CONVERGENCE.md", "Historical G7 convergence record; it does not attest the current G8 exact head."),
}
for record in index["source_records"]:
    if record["id"] in path_map:
        record["path"], record["claim"] = path_map[record["id"]]
extra = [
    {"id":"EV-SRC-G8-CANDIDATE-V1","path":"docs/development/G8_SOURCE_CONVERGENCE.md","levels":["E0","E1","E2","E3"],"claim":"Current G8 source-convergence contract. E4 exists only for an unchanged exact-head CI artifact generated by GitHub Actions."},
    {"id":"EV-SRC-PROJECT-STATE-V1","path":"docs/PROJECT_STATE.json","levels":["E0"],"claim":"Machine-readable current product stage, claim ceiling, source authority, capability status, and external gate set without a self-attested commit SHA."},
    {"id":"EV-SRC-HISTORY-ACK-V1","path":"contracts/history-scan-acknowledgements-v1.json","levels":["E0","E1"],"claim":"Exact fingerprint-and-path acknowledgements for synthetic detector fixtures; unknown or unused acknowledgements fail closed."},
]
ids = {record["id"] for record in index["source_records"]}
index["source_records"].extend(record for record in extra if record["id"] not in ids)
index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

validator = text("tools/validate_repository.py")
if "from validate_product_surface import validate_product_surface" not in validator:
    validator = validator.replace(
        "from typing import Iterable\n",
        "from typing import Iterable\n\nfrom validate_product_surface import validate_product_surface\n",
    )
validator = validator.replace('CANONICAL_REVISION = "2026-08-31-g7"', 'CANONICAL_REVISION = "2026-08-31-g8"')
validator = validator.replace('ROOT / "docs/GAP_LEDGER.yaml"', 'ROOT / "docs/GAP_LEDGER.json"')
validator = validator.replace('ROOT / "docs/EVIDENCE_INDEX.yaml"', 'ROOT / "docs/EVIDENCE_INDEX.json"')
validator = validator.replace('"docs/GAP_LEDGER.yaml"', '"docs/GAP_LEDGER.json"')
validator = validator.replace('"docs/EVIDENCE_INDEX.yaml"', '"docs/EVIDENCE_INDEX.json"')
validator = validator.replace(
    '    "docs/development/G3_G8_SOURCE_CLOSURE.md",\n    "docs/development/G4_SOURCE_CLOSURE.md",\n    "docs/development/G5_AUDIT_CLOSURE.md",\n    "docs/development/G7_SOURCE_CONVERGENCE.md",\n',
    '    "docs/PROJECT_STATE.json",\n    "docs/development/G8_SOURCE_CONVERGENCE.md",\n    "docs/history/source-closure/G3_G8_SOURCE_CLOSURE.md",\n    "docs/history/source-closure/G4_SOURCE_CLOSURE.md",\n    "docs/history/source-closure/G5_AUDIT_CLOSURE.md",\n    "docs/history/source-closure/G7_SOURCE_CONVERGENCE.md",\n    "tools/validate_product_surface.py",\n',
)
validator = validator.replace('if len(gaps) < 51:', 'if len(gaps) < 57:')
validator = validator.replace('if f"Revision: `{CANONICAL_REVISION}`" not in plan:', 'if f"Canonical revision: `{CANONICAL_REVISION}`" not in plan:')
validator = validator.replace('if f"Canonical plan revision: `{CANONICAL_REVISION}`" not in current:', 'if f"Canonical revision: `{CANONICAL_REVISION}`" not in current:')
path_check_anchor = '''        if status.startswith("CLOSED") and not gap.get("evidence"):\n            fail(f"{gap_id} is closed without evidence")\n        if status.startswith("BLOCKED"):\n'''
path_check = '''        if status.startswith("CLOSED") and not gap.get("evidence"):\n            fail(f"{gap_id} is closed without evidence")\n        for field in ("evidence", "source_preparation"):\n            for item in gap.get(field, []):\n                if not isinstance(item, str) or not item.strip():\n                    fail(f"{gap_id} has an invalid {field} entry")\n                if item.startswith("github:"):\n                    continue\n                if not (ROOT / item).exists():\n                    fail(f"{gap_id} references missing {field}: {item}")\n        if status.startswith("BLOCKED"):\n'''
if path_check_anchor in validator:
    validator = validator.replace(path_check_anchor, path_check)
evidence_anchor = '''    index = read_json(ROOT / "docs/EVIDENCE_INDEX.json")\n    if index.get("plan_revision") != CANONICAL_REVISION:\n        fail("Evidence Index is not bound to the canonical revision")\n'''
evidence_check = evidence_anchor + '''    records = index.get("source_records")\n    if not isinstance(records, list) or not records:\n        fail("Evidence Index has no source records")\n    seen: set[str] = set()\n    for record in records:\n        record_id = record.get("id")\n        path = record.get("path")\n        levels = record.get("levels")\n        if not isinstance(record_id, str) or record_id in seen:\n            fail(f"invalid or duplicate evidence record id: {record_id!r}")\n        seen.add(record_id)\n        if not isinstance(path, str) or not (ROOT / path).is_file():\n            fail(f"evidence record {record_id} references a missing file")\n        if not isinstance(levels, list) or not levels:\n            fail(f"evidence record {record_id} has no evidence levels")\n        if record_id == "EV-SRC-G8-CANDIDATE-V1" and "E4" in levels:\n            fail("current G8 source document self-claims dynamic E4 evidence")\n'''
if evidence_anchor in validator and "Evidence Index has no source records" not in validator:
    validator = validator.replace(evidence_anchor, evidence_check)
call_anchor = "        validate_gap_ledger,\n        validate_boundaries,"
if call_anchor in validator:
    validator = validator.replace(
        call_anchor,
        "        validate_gap_ledger,\n        lambda: validate_product_surface(\n            ROOT,\n            canonical_revision=CANONICAL_REVISION,\n            expected_checks=EXPECTED_CHECKS,\n            read_json=read_json,\n            iter_text_files=iter_text_files,\n            fail=fail,\n        ),\n        validate_boundaries,",
    )
write("tools/validate_repository.py", validator)

cn = ROOT / "docs/G1连接.md"
if cn.exists():
    value = cn.read_text(encoding="utf-8")
    value = value.replace("`isBothConnected()` 固定返回 `true`，所以 SDK 现在把写入特征发现视作连接成功。", "连接成功必须由左右耳分别完成通知订阅、MTU 协商和初始化写入后再汇总；不能固定返回双耳已连接。")
    cn.write_text(value, encoding="utf-8")
en = ROOT / "docs/G1连接_en.md"
if en.exists():
    value = en.read_text(encoding="utf-8")
    value = value.replace("`isBothConnected()` currently always returns `true`, so the SDK treats discovery of the writable characteristic as a successful connection.", "A successful connection requires both legs to complete notification subscription, MTU negotiation, and initialization before readiness is reported; the implementation must not hard-code dual-leg success.")
    en.write_text(value, encoding="utf-8")

for path in (ROOT / ".github/g8_truth_transform.py", ROOT / ".github/workflows/g8-truth-materialize.yml"):
    if path.exists():
        path.unlink()
