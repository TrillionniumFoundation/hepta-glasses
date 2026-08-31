#!/usr/bin/env python3
"""Close deterministic current-truth drift after the one-shot G8 transform."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_repository.py"
SURFACE_VALIDATOR = ROOT / "tools" / "validate_product_surface.py"
ANDROID_BUILD = ROOT / "android" / "app" / "build.gradle"
ANDROID_MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"

PATH_REPLACEMENTS = (
    (
        "android/app/src/main/kotlin/com/example/demo_ai_even",
        "android/app/src/main/kotlin/org/trillionnium/heptaglasses",
    ),
    (
        "android/app/src/test/kotlin/com/example/demo_ai_even",
        "android/app/src/test/kotlin/org/trillionnium/heptaglasses",
    ),
    (
        "android/app/src/androidTest/kotlin/com/example/demo_ai_even",
        "android/app/src/androidTest/kotlin/org/trillionnium/heptaglasses",
    ),
)
TEXT_REPLACEMENTS = PATH_REPLACEMENTS + (
    ("com.example.demo_ai_even", "org.trillionnium.heptaglasses"),
)


def replace_text(value: str) -> str:
    for old, new in TEXT_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def replace_json(value: Any) -> Any:
    if isinstance(value, str):
        return replace_text(value)
    if isinstance(value, list):
        return [replace_json(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_json(item) for key, item in value.items()}
    return value


# Required-file contract must point to the canonical test package. The legacy
# directory existence checks intentionally remain unchanged so stale paths are
# still rejected.
old_required = (
    '"android/app/src/test/kotlin/com/example/demo_ai_even/model/'
    'BlePairDeviceTest.kt"'
)
new_required = (
    '"android/app/src/test/kotlin/org/trillionnium/heptaglasses/model/'
    'BlePairDeviceTest.kt"'
)
validator = VALIDATOR.read_text(encoding="utf-8")
if old_required in validator:
    validator = validator.replace(old_required, new_required)
elif new_required not in validator:
    raise SystemExit("repository validator has neither legacy nor canonical Android test path")

# The transform introduced an external product-surface validator but its
# original import anchor did not exist in the base file. Install the import
# deterministically rather than allowing a late NameError.
import_line = "from validate_product_surface import validate_product_surface"
if import_line not in validator:
    anchor = "from pathlib import Path\n"
    if anchor not in validator:
        raise SystemExit("repository validator import anchor is missing")
    validator = validator.replace(anchor, f"{anchor}\n{import_line}\n", 1)
VALIDATOR.write_text(validator, encoding="utf-8")

# The broad filename migration also rewrote the negative legacy-file check in
# the product validator. Restore that check after the one-shot transform. The
# legacy suffix is assembled dynamically so the transform cannot rewrite this
# helper before it runs.
legacy_gap = "docs/GAP_LEDGER." + "yaml"
legacy_index = "docs/EVIDENCE_INDEX." + "yaml"
transformed_check = (
    '    if (root / "docs/GAP_LEDGER.json").exists() or '
    '(root / "docs/EVIDENCE_INDEX.json").exists():\n'
)
legacy_check = (
    f'    if (root / "{legacy_gap}").exists() or '
    f'(root / "{legacy_index}").exists():\n'
)
surface = SURFACE_VALIDATOR.read_text(encoding="utf-8")
if transformed_check in surface:
    surface = surface.replace(transformed_check, legacy_check, 1)
elif legacy_check not in surface:
    raise SystemExit("product-surface legacy-ledger check cannot be reconciled")
SURFACE_VALIDATOR.write_text(surface, encoding="utf-8")

# Remove Kotlin reflection regardless of whether an older branch pinned the
# version directly or interpolated it from a Gradle variable.
android_build = ANDROID_BUILD.read_text(encoding="utf-8")
android_build = re.sub(
    r"(?m)^\s*(?:implementation|api)\s+[\"']org\.jetbrains\.kotlin:kotlin-reflect:[^\"']+[\"']\s*$\n?",
    "",
    android_build,
)
if "kotlin-reflect" in android_build:
    raise SystemExit("unable to remove every Kotlin reflection dependency")
ANDROID_BUILD.write_text(android_build, encoding="utf-8")

# Remove the unrelated package-visibility query structurally. Older transforms
# depended on a generated comment that is not present in every Flutter tree.
manifest = ANDROID_MANIFEST.read_text(encoding="utf-8")
manifest = re.sub(r"\n\s*<queries\b[^>]*>.*?</queries>\s*", "\n", manifest, flags=re.S)
if "PROCESS_TEXT" in manifest or "<queries" in manifest:
    raise SystemExit("unable to remove Android PROCESS_TEXT query surface")
ANDROID_MANIFEST.write_text(manifest, encoding="utf-8")

# Machine truth must never reference files removed by the package migration.
for relative in ("docs/GAP_LEDGER.json", "docs/EVIDENCE_INDEX.json"):
    path = ROOT / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(replace_json(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

# Keep current developer-facing documentation aligned without rewriting
# historical closure records or immutable history-scan acknowledgements.
text_roots = [ROOT / "README.md"]
text_roots.extend(
    path
    for path in (ROOT / "docs").rglob("*")
    if path.is_file() and "history" not in path.parts
)
text_roots.extend(
    path
    for base in (ROOT / "contracts", ROOT / "evidence")
    if base.exists()
    for path in base.rglob("*")
    if path.is_file()
    and path.name != "history-scan-acknowledgements-v1.json"
)
for path in text_roots:
    try:
        before = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    after = replace_text(before)
    if after != before:
        path.write_text(after, encoding="utf-8")

# This helper is one-shot and must not enter the candidate source tree.
Path(__file__).unlink()
