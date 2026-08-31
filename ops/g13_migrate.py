#!/usr/bin/env python3
"""Idempotently normalize Hepta Glasses product identity and JSON-ledger truth.

This script intentionally avoids rewriting historical-secret acknowledgement files.
Those records refer to immutable Git objects and must retain their exact paths and
fingerprints. Product identity checks are instead scoped to executable/current
product source.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
from pathlib import Path
from typing import Iterable

ANDROID_ID = "org.trillionnium.heptaglasses"
DART_PACKAGE = "hepta_glasses"
PRODUCT_NAME = "Hepta Glasses"
IOS_BUNDLE_NAME = "HeptaGlasses"

EXCLUDED_PARTS = {
    ".git",
    "build",
    ".dart_tool",
    ".gradle",
    "Pods",
    "DerivedData",
    ".idea",
}


def text_files(root: Path, bases: Iterable[Path]) -> Iterable[Path]:
    for base in bases:
        path = root / base
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else path.rglob("*")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if any(part in EXCLUDED_PARTS for part in candidate.parts):
                continue
            try:
                candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            yield candidate


def replace_text(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    text = path.read_text(encoding="utf-8")
    updated = text
    for old, new in replacements:
        updated = updated.replace(old, new)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def normalize_ledger_references(root: Path) -> None:
    replacements = (
        ("docs/GAP_LEDGER.yaml", "docs/GAP_LEDGER.json"),
        ("docs/EVIDENCE_INDEX.yaml", "docs/EVIDENCE_INDEX.json"),
        ("GAP_LEDGER.yaml", "GAP_LEDGER.json"),
        ("EVIDENCE_INDEX.yaml", "EVIDENCE_INDEX.json"),
    )
    for path in text_files(
        root,
        (
            Path("README.md"),
            Path("docs"),
            Path("contracts"),
            Path("evidence"),
            Path("tools"),
            Path("services"),
            Path("adapters"),
            Path("plugins"),
            Path("lib"),
            Path("test"),
            Path("android"),
            Path("ios"),
            Path(".github/workflows/ci.yml"),
        ),
    ):
        replace_text(path, replacements)

    for old_name, new_name in (
        ("docs/GAP_LEDGER.yaml", "docs/GAP_LEDGER.json"),
        ("docs/EVIDENCE_INDEX.yaml", "docs/EVIDENCE_INDEX.json"),
    ):
        old = root / old_name
        new = root / new_name
        if old.exists():
            parsed = json.loads(old.read_text(encoding="utf-8"))
            if new.exists():
                existing = json.loads(new.read_text(encoding="utf-8"))
                if parsed != existing:
                    raise SystemExit(
                        f"conflicting JSON ledger representations: {old_name}, {new_name}"
                    )
                old.unlink()
            else:
                old.rename(new)
        if not new.is_file():
            raise SystemExit(f"required JSON ledger missing: {new_name}")
        json.loads(new.read_text(encoding="utf-8"))


def normalize_dart(root: Path) -> None:
    pubspec = root / "pubspec.yaml"
    text = pubspec.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^name:\s*[A-Za-z0-9_\-]+\s*$",
        f"name: {DART_PACKAGE}",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("unable to set the Dart package name deterministically")
    pubspec.write_text(updated, encoding="utf-8")

    for path in text_files(root, (Path("lib"), Path("test"))):
        if path.suffix != ".dart":
            continue
        replace_text(
            path,
            (
                ("package:demo_ai_even/", f"package:{DART_PACKAGE}/"),
                ("package:demo-ai-even/", f"package:{DART_PACKAGE}/"),
            ),
        )

    for path in text_files(root, (Path("lib"), Path("README.md"))):
        replace_text(
            path,
            (
                ("Demo Ai Even", PRODUCT_NAME),
                ("Demo AI Even", PRODUCT_NAME),
            ),
        )


def merge_move(old: Path, new: Path) -> None:
    if not old.exists():
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    if not new.exists():
        shutil.move(str(old), str(new))
        return

    for item in sorted(old.rglob("*"), key=lambda value: len(value.parts)):
        target = new / item.relative_to(old)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != item.read_bytes():
                raise SystemExit(f"conflicting Android source during move: {target}")
            item.unlink()
        else:
            shutil.move(str(item), str(target))
    shutil.rmtree(old)


def normalize_android(root: Path) -> None:
    replacements = (
        ("com.example.demo_ai_even", ANDROID_ID),
        ("com/example/demo_ai_even", "org/trillionnium/heptaglasses"),
        ("com_example_demo_1ai_1even", "org_trillionnium_heptaglasses"),
        ("com.example.demoAiEven", ANDROID_ID),
        ("com.example.demoaieven", ANDROID_ID),
    )
    for path in text_files(root, (Path("android"),)):
        replace_text(path, replacements)

    for gradle_name in (
        "android/app/build.gradle",
        "android/app/build.gradle.kts",
    ):
        path = root / gradle_name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"(?m)^(\s*namespace\s*(?:=\s*)?)[\"'][^\"']+[\"']",
            rf'\1"{ANDROID_ID}"',
            text,
        )
        text = re.sub(
            r"(?m)^(\s*applicationId\s*(?:=\s*)?)[\"'][^\"']+[\"']",
            rf'\1"{ANDROID_ID}"',
            text,
        )
        path.write_text(text, encoding="utf-8")

    for source_set in ("main", "test", "androidTest"):
        for language in ("kotlin", "java"):
            base = root / "android" / "app" / "src" / source_set / language
            old = base / "com" / "example" / "demo_ai_even"
            new = base / "org" / "trillionnium" / "heptaglasses"
            merge_move(old, new)
            for parent in (base / "com" / "example", base / "com"):
                try:
                    parent.rmdir()
                except OSError:
                    pass


def normalize_ios(root: Path) -> None:
    plist_path = root / "ios" / "Runner" / "Info.plist"
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    plist["CFBundleDisplayName"] = PRODUCT_NAME
    plist["CFBundleName"] = IOS_BUNDLE_NAME
    with plist_path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=False)

    project_path = root / "ios" / "Runner.xcodeproj" / "project.pbxproj"
    project = project_path.read_text(encoding="utf-8")

    def bundle_replacement(match: re.Match[str]) -> str:
        prefix = match.group(1)
        current = match.group(2).strip().strip('"')
        lowered = current.lower()
        if "runneruitests" in lowered:
            value = f"{ANDROID_ID}.RunnerUITests"
        elif "runnertests" in lowered:
            value = f"{ANDROID_ID}.RunnerTests"
        else:
            value = ANDROID_ID
        return f"{prefix}{value};"

    project, count = re.subn(
        r"(?m)^(\s*PRODUCT_BUNDLE_IDENTIFIER\s*=\s*)([^;]+);",
        bundle_replacement,
        project,
    )
    if count == 0:
        raise SystemExit("no iOS PRODUCT_BUNDLE_IDENTIFIER settings found")
    project = project.replace("Demo Ai Even", PRODUCT_NAME)
    project = project.replace("Demo AI Even", PRODUCT_NAME)
    project_path.write_text(project, encoding="utf-8")


def write_identity_contract(root: Path) -> None:
    contract = {
        "schema_version": 2,
        "product": PRODUCT_NAME,
        "dart_package": DART_PACKAGE,
        "android_namespace": ANDROID_ID,
        "android_application_id": ANDROID_ID,
        "ios_bundle_identifier": ANDROID_ID,
        "ios_display_name": PRODUCT_NAME,
        "supported_product_platforms": ["android", "ios"],
        "ledger_formats": {
            "gap_ledger": "docs/GAP_LEDGER.json",
            "evidence_index": "docs/EVIDENCE_INDEX.json",
        },
        "history_acknowledgements_are_immutable_object_references": True,
    }
    target = root / "contracts" / "product-identity-v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    validator = f'''#!/usr/bin/env python3
"""Fail closed on executable product-identity or document-format drift."""
from __future__ import annotations

import json
import plistlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_ID = {ANDROID_ID!r}
DART_PACKAGE = {DART_PACKAGE!r}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


contract = json.loads((ROOT / "contracts/product-identity-v1.json").read_text())
require(contract["dart_package"] == DART_PACKAGE, "identity contract Dart drift")
require(contract["android_namespace"] == ANDROID_ID, "identity contract Android drift")
require(contract["ios_bundle_identifier"] == ANDROID_ID, "identity contract iOS drift")

pubspec = (ROOT / "pubspec.yaml").read_text()
require(bool(re.search(r"(?m)^name:\\s*hepta_glasses\\s*$", pubspec)), "Dart package identity drift")
for base in (ROOT / "lib", ROOT / "test"):
    if not base.exists():
        continue
    for path in base.rglob("*.dart"):
        text = path.read_text(encoding="utf-8")
        require("package:demo_ai_even/" not in text, f"legacy Dart import: {{path.relative_to(ROOT)}}")

app_gradle = next(
    (path for path in (ROOT / "android/app/build.gradle", ROOT / "android/app/build.gradle.kts") if path.exists()),
    None,
)
require(app_gradle is not None, "Android app Gradle file missing")
gradle = app_gradle.read_text(encoding="utf-8")
require(ANDROID_ID in gradle, "Android namespace/application ID drift")

android_legacy = ("com.example.demo_ai_even", "com/example/demo_ai_even", "com_example_demo_1ai_1even")
for base in (ROOT / "android/app/src", ROOT / "android/app/CMakeLists.txt"):
    paths = [base] if base.is_file() else base.rglob("*") if base.exists() else []
    for path in paths:
        if not path.is_file() or any(part in {{"build", ".gradle"}} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        require(not any(token in text for token in android_legacy), f"legacy Android identity: {{path.relative_to(ROOT)}}")
for source_set in ("main", "test", "androidTest"):
    for language in ("kotlin", "java"):
        legacy = ROOT / "android/app/src" / source_set / language / "com/example/demo_ai_even"
        require(not legacy.exists(), f"legacy Android path remains: {{legacy.relative_to(ROOT)}}")
require(
    (ROOT / "android/app/src/main/kotlin/org/trillionnium/heptaglasses").is_dir()
    or (ROOT / "android/app/src/main/java/org/trillionnium/heptaglasses").is_dir(),
    "canonical Android source path missing",
)

with (ROOT / "ios/Runner/Info.plist").open("rb") as handle:
    plist = plistlib.load(handle)
require(plist.get("CFBundleDisplayName") == "Hepta Glasses", "iOS display name drift")
require(plist.get("CFBundleName") == "HeptaGlasses", "iOS bundle name drift")
project = (ROOT / "ios/Runner.xcodeproj/project.pbxproj").read_text()
bundle_values = re.findall(r"(?m)^\\s*PRODUCT_BUNDLE_IDENTIFIER\\s*=\\s*([^;]+);", project)
require(bool(bundle_values), "iOS bundle identifiers missing")
for value in bundle_values:
    require(value.strip().strip('"').startswith(ANDROID_ID), f"iOS bundle identifier drift: {{value}}")

for path in (ROOT / "docs/GAP_LEDGER.json", ROOT / "docs/EVIDENCE_INDEX.json"):
    require(path.is_file(), f"JSON ledger missing: {{path.relative_to(ROOT)}}")
    json.loads(path.read_text())
require(not (ROOT / "docs/GAP_LEDGER.yaml").exists(), "misleading YAML Gap Ledger remains")
require(not (ROOT / "docs/EVIDENCE_INDEX.yaml").exists(), "misleading YAML Evidence Index remains")

print(json.dumps({{"product_identity": "verified", "ledger_format": "verified"}}, separators=(",", ":")))
'''
    validator_path = root / "tools" / "validate_product_identity.py"
    validator_path.write_text(validator, encoding="utf-8")
    validator_path.chmod(0o755)

    doc_path = root / "docs" / "development" / "G13_PRODUCT_IDENTITY_AND_DOCUMENT_FORMAT.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "# G13 product identity and document-format contract\n\n"
        "The executable product identity is defined by `contracts/product-identity-v1.json` "
        "and enforced by `tools/validate_product_identity.py` in the required "
        "`repository-contracts` job.\n\n"
        "Dart imports, Android namespace/application ID, Kotlin/Java source paths, JNI "
        "symbols, iOS bundle identifiers, and visible names are normalized atomically. "
        "Historical secret-scan acknowledgements retain exact immutable-object paths and "
        "fingerprints.\n\n"
        "`docs/GAP_LEDGER.json` and `docs/EVIDENCE_INDEX.json` are strict JSON. Dynamic "
        "commit, workflow-run, artifact, branch-governance, and review identities remain "
        "external exact-head attestations.\n",
        encoding="utf-8",
    )


def wire_ci(root: Path) -> None:
    workflow = root / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    step = "      - run: python3 tools/validate_product_identity.py\n"
    if step in text:
        return
    anchor = "      - run: python3 tools/validate_repository.py\n"
    if text.count(anchor) != 1:
        raise SystemExit("cannot insert product identity validation deterministically")
    workflow.write_text(text.replace(anchor, anchor + step, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    root = parser.parse_args().root.resolve()
    normalize_ledger_references(root)
    normalize_dart(root)
    normalize_android(root)
    normalize_ios(root)
    write_identity_contract(root)
    wire_ci(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
