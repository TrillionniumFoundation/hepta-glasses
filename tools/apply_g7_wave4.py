#!/usr/bin/env python3
"""Repair conditional release-gate and test-lifecycle details for G7."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"pattern missing in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    path = ROOT / "services/qualification/release_gate.py"
    text = path.read_text(encoding="utf-8")
    anchor = '''        credential_incident = (
            credential_incident
            if isinstance(credential_incident, Mapping)
            else {}
        )
'''
    addition = anchor + '''        source_evidence = bundle.get("source")
        source_evidence = (
            source_evidence if isinstance(source_evidence, Mapping) else {}
        )
        history_evidence = source_evidence.get("history_scan")
        history_evidence = (
            history_evidence if isinstance(history_evidence, Mapping) else {}
        )
        historical_credential_findings = int(
            history_evidence.get("historical_finding_count", 0)
        )
'''
    if "historical_credential_findings = int(" not in text:
        if anchor not in text:
            raise RuntimeError("credential incident anchor missing")
        text = text.replace(anchor, addition, 1)
    old_check = '''            "historical_credential_revoked": (
                credential_incident.get("provider_rotation_or_revocation")
                == "verified"
            ),
'''
    new_check = '''            "historical_credential_revoked": (
                historical_credential_findings == 0
                or credential_incident.get("provider_rotation_or_revocation")
                == "verified"
            ),
'''
    if new_check not in text:
        if old_check not in text:
            raise RuntimeError("historical credential check missing")
        text = text.replace(old_check, new_check, 1)
    path.write_text(text, encoding="utf-8")

    test_path = ROOT / "test/views/even_list_page_test.dart"
    if test_path.exists():
        test = test_path.read_text(encoding="utf-8")
        test = test.replace(
            '''  tearDown(() {
    Get.reset();
    EvenAI.isEvenAISyncing.value = false;
  });
''',
            '''  tearDown(() async {
    await Get.reset();
    EvenAI.isEvenAISyncing.value = false;
  });
''',
        )
        test_path.write_text(test, encoding="utf-8")

    broken = ROOT / "tools/apply_g7_wave3.py"
    if broken.exists():
        broken.unlink()
    for item in ROOT.glob("tools/apply_g7_*.py"):
        item.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
