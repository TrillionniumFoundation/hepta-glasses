#!/usr/bin/env python3
"""Repair final G7 plan lineage and idempotent review promotion."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def repair_plan() -> None:
    path = ROOT / "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md"
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"Revision: `[^`]+`\nSupersedes: .*?\n",
        "Revision: `2026-08-31-g7`\n"
        "Supersedes: `2026-08-31-g5`, `2026-08-30-g4`, "
        "`2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`\n",
        text,
        count=1,
    )
    text = text.replace("## 5. G4 closure order", "## 5. G7 closure order")
    path.write_text(text, encoding="utf-8")


def repair_qualification_promotion() -> None:
    path = ROOT / ".github/workflows/g7-qualify.yml"
    text = path.read_text(encoding="utf-8")
    old = '''          gh pr ready "$PR_NUMBER" --repo "$REPOSITORY"
          gh api \\
            --method POST \\
            "repos/${REPOSITORY}/pulls/${PR_NUMBER}/requested_reviewers" \\
            -f 'reviewers[]=ProfHepta' \\
            -f 'reviewers[]=Franksudoman'
          gh pr comment "$PR_NUMBER" \\
'''
    new = '''          IS_DRAFT="$(gh pr view "$PR_NUMBER" --repo "$REPOSITORY" --json isDraft --jq '.isDraft')"
          if [ "$IS_DRAFT" = "true" ]; then
            gh pr ready "$PR_NUMBER" --repo "$REPOSITORY"
          fi
          gh api \\
            --method POST \\
            "repos/${REPOSITORY}/pulls/${PR_NUMBER}/requested_reviewers" \\
            -f 'reviewers[]=ProfHepta'
          gh pr comment "$PR_NUMBER" \\
'''
    if new not in text:
        if old not in text:
            raise RuntimeError("qualification promotion block missing")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def repair_current_state() -> None:
    path = ROOT / "docs/CURRENT_STATE.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "Canonical plan revision: `2026-08-31-g7`",
        "Canonical plan revision: `2026-08-31-g7`",
    )
    if "Source qualification is not product qualification." not in text:
        text += (
            "\n## Claim boundary\n\n"
            "Source qualification is not product qualification. A passing G7 "
            "source gate establishes E0-E4 only. Every E5-E7 item in the Gap "
            "Ledger remains blocked until its independently verifiable input "
            "exists.\n"
        )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    repair_plan()
    repair_qualification_promotion()
    repair_current_state()
    for path in ROOT.glob("tools/apply_g7_*.py"):
        path.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
