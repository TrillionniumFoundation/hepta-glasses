#!/usr/bin/env python3
"""Idempotent qualification repair pass for the staged G7 candidate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def update(path: str, transform) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated = transform(text)
    target.write_text(updated, encoding="utf-8")


def main() -> int:
    update(
        "lib/controllers/bmp_update_manager.dart",
        lambda text: text.replace("import 'dart:async';\n", ""),
    )

    def scanner(text: str) -> str:
        text = text.replace('"schema_version": 2,', '"schema_version": 1,')
        marker = '        "tools/scan_git_history.py",\n'
        additions = (
            marker
            + '        "tools/apply_g7_synthesis.py",\n'
            + '        "tools/apply_g7_repair.py",\n'
        )
        if '"tools/apply_g7_synthesis.py"' not in text:
            text = text.replace(marker, additions, 1)
        return text

    update("tools/scan_git_history.py", scanner)

    for path in (
        ROOT / "tools/scan_git_history.py",
        ROOT / "tools/apply_g7_synthesis.py",
        ROOT / "tools/apply_g7_repair.py",
        ROOT / "tools/run_native_sanitizers.sh",
        ROOT / "tools/run_native_sanitizer_tests.sh",
    ):
        if path.exists():
            path.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
