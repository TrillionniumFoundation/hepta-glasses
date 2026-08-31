#!/usr/bin/env python3
"""Close deterministic validator drift after the one-shot G8 truth transform."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_repository.py"
OLD_TEST_PATH = (
    '"android/app/src/test/kotlin/com/example/demo_ai_even/model/'
    'BlePairDeviceTest.kt"'
)
NEW_TEST_PATH = (
    '"android/app/src/test/kotlin/org/trillionnium/heptaglasses/model/'
    'BlePairDeviceTest.kt"'
)

text = VALIDATOR.read_text(encoding="utf-8")
if OLD_TEST_PATH in text:
    text = text.replace(OLD_TEST_PATH, NEW_TEST_PATH)
elif NEW_TEST_PATH not in text:
    raise SystemExit("repository validator has neither legacy nor canonical Android test path")
VALIDATOR.write_text(text, encoding="utf-8")

# This helper is one-shot and must not enter the candidate source tree.
Path(__file__).unlink()
