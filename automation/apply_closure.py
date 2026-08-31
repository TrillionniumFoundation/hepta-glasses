#!/usr/bin/env python3
"""Apply only deterministic repository-actionable G8 closure changes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
ACK_PATH = ROOT / "docs/security/HISTORY_SECRET_ACKNOWLEDGEMENTS.json"
REPORT_PATH = ROOT / "build/evidence/pre-finalizer-history-scan.json"
SCANNER_SOURCE = Path(sys.argv[1]).resolve()


def command(*arguments: str) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True)


def patch_android_handler() -> None:
    candidates = list(
        (ROOT / "android/app/src/main/kotlin").rglob("BleDevice.kt")
    )
    if len(candidates) != 1:
        raise SystemExit(f"expected exactly one BleDevice.kt, found {candidates}")
    path = candidates[0]
    text = path.read_text(encoding="utf-8")
    declaration = "    private val writeHandler = Handler(Looper.getMainLooper())\n"
    if declaration in text:
        text = text.replace(
            declaration,
            "    @Volatile\n    private var writeHandler: Handler? = null\n",
            1,
        )
    if "private fun mainHandler(): Handler" not in text:
        marker = "    @Volatile\n    private var drainScheduled = false\n"
        helper = (
            "    @Volatile\n"
            "    private var drainScheduled = false\n\n"
            "    private fun mainHandler(): Handler {\n"
            "        writeHandler?.let { return it }\n"
            "        return synchronized(this) {\n"
            "            writeHandler ?: Handler(Looper.getMainLooper()).also {\n"
            "                writeHandler = it\n"
            "            }\n"
            "        }\n"
            "    }\n"
        )
        if marker not in text:
            raise SystemExit("BleDevice drainScheduled marker not found")
        text = text.replace(marker, helper, 1)
    text = text.replace(
        "writeHandler.post(::drainOne)",
        "mainHandler().post(::drainOne)",
    )
    text = text.replace(
        "writeHandler.postDelayed(::drainOne, WRITE_INTERVAL_MS)",
        "mainHandler().postDelayed(::drainOne, WRITE_INTERVAL_MS)",
    )
    text = text.replace(
        "        writeHandler.removeCallbacksAndMessages(null)\n",
        "        writeHandler?.removeCallbacksAndMessages(null)\n"
        "        writeHandler = null\n",
    )
    path.write_text(text, encoding="utf-8")


def is_fixture_path(path: str) -> bool:
    name = Path(path).name
    return (
        path.startswith("test/")
        or "/src/test/" in path
        or name.startswith("test_")
        or path.startswith("tools/test")
        or path.startswith("evidence/fixtures/")
    )


def key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        str(item[field])
        for field in ("pattern", "path", "object", "fingerprint")
    )


def build_acknowledgements() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            sys.executable,
            "tools/scan_git_history.py",
            "--report-only",
            "--output",
            str(REPORT_PATH),
        ],
        cwd=ROOT,
    )
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    observed: list[dict[str, Any]] = []
    for field in (
        "findings",
        "acknowledged_historical_findings",
        "acknowledged_current_fixture_findings",
    ):
        value = report.get(field, [])
        if isinstance(value, list):
            observed.extend(item for item in value if isinstance(item, dict))
    if ACK_PATH.exists():
        existing = json.loads(ACK_PATH.read_text(encoding="utf-8"))
        entries = existing.get("entries", [])
        if isinstance(entries, list):
            observed.extend(item for item in entries if isinstance(item, dict))

    head_objects: set[str] = set()
    for row in command("git", "ls-tree", "-r", "--full-tree", "HEAD").splitlines():
        metadata, separator, _ = row.partition("\t")
        fields = metadata.split()
        if separator and len(fields) == 3 and fields[1] == "blob":
            head_objects.add(fields[2])

    unique: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for item in observed:
        required = ("pattern", "path", "object", "fingerprint")
        if all(field in item for field in required):
            unique[key(item)] = {
                field: str(item[field]) for field in required
            }

    entries: list[dict[str, str]] = []
    for item_key in sorted(unique):
        item = unique[item_key]
        current = item["object"] in head_objects
        if current and not is_fixture_path(item["path"]):
            raise SystemExit(
                "refusing to acknowledge current production-source finding: "
                f"{item['path']}"
            )
        item["scope"] = (
            "non_secret_test_fixture"
            if current
            else "historical_object_unreachable_from_candidate_head"
        )
        item["remediation_boundary"] = (
            "credential_revocation_requires_provider_evidence"
        )
        item["release_effect"] = (
            "none_fixture_only"
            if current
            else "product_release_remains_blocked_without_external_revocation_evidence"
        )
        entries.append(item)

    ACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACK_PATH.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": (
                    "Only exact non-secret test fixtures or exact historical blobs "
                    "unreachable from candidate HEAD may be acknowledged. Historical "
                    "acknowledgement does not assert provider-side revocation."
                ),
                "entries": entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def install_scanner_and_policy() -> None:
    shutil.copyfile(SCANNER_SOURCE, ROOT / "tools/scan_git_history.py")
    (ROOT / "tools/scan_git_history.py").chmod(0o755)
    policy = ROOT / "docs/security/HISTORICAL_SECRET_HANDLING.md"
    policy.write_text(
        """# Historical secret handling

The candidate tree must contain no unacknowledged secret-pattern match. Every fetched
Git ref remains in scope. Exact acknowledgements are permitted only for non-secret test
fixtures in test-only paths or for historical Git blobs that are unreachable from the
candidate `HEAD` tree.

Historical acknowledgement does not prove that a provider credential was revoked.
Provider-side revocation and rejection evidence remains a separate product-release gate.
Changed fingerprints, new paths, current production-source matches, oversized blobs,
unscanned blobs, duplicate entries, invalid scopes, and stale acknowledgements fail closed.
""",
        encoding="utf-8",
    )


patch_android_handler()
build_acknowledgements()
install_scanner_and_policy()
