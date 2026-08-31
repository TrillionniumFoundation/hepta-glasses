#!/usr/bin/env python3
"""Apply all available G7 repairs, then leave only read-only qualification CI."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    path = ROOT / script
    if path.exists():
        subprocess.run(["python3", str(path)], cwd=ROOT, check=True)


def main() -> int:
    for script in (
        "tools/apply_g7_synthesis.py",
        "tools/apply_g7_repair.py",
        "tools/apply_g7_wave2.py",
        "tools/apply_g7_wave3_fixed.py",
        "tools/apply_g7_wave4.py",
        "tools/apply_g7_postrepair_fixed.py",
        "tools/apply_g7_tail_repair.py",
    ):
        run(script)

    workflow_dir = ROOT / ".github/workflows"
    for path in workflow_dir.glob("g7-*.yml"):
        if path.name == "g7-qualify.yml":
            continue
        path.unlink()
    for path in ROOT.glob("tools/g7-*.trigger"):
        path.unlink()
    for path in ROOT.glob("tools/apply_g7_*.py"):
        path.unlink()

    for path in (
        ROOT / "tools/run_native_sanitizers.sh",
        ROOT / "tools/run_native_sanitizer_tests.sh",
        ROOT / "tools/scan_git_history.py",
    ):
        if path.exists():
            path.chmod(0o755)

    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
