#!/usr/bin/env python3
"""Close deterministic current-truth drift after the one-shot G8 transform."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_repository.py"

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
