#!/usr/bin/env python3
"""Fail-closed CocoaPods lockfile inspection and operator-only refresh."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PODFILE = ROOT / "ios/Podfile"
LOCKFILE = ROOT / "ios/Podfile.lock"
WORKFLOW = ROOT / ".github/workflows/ci.yml"
APPROVAL_ENV = "HEPTA_COCOAPODS_UPDATE_APPROVED"

_POD_DECLARATION = re.compile(r"""^\s*pod\s+['\"]([^'\"]+)['\"]""")
_COCOAPODS_VERSION = re.compile(r"(?m)^COCOAPODS:\s+([0-9]+(?:\.[0-9]+){1,3})\s*$")


class CocoaPodsPolicyError(RuntimeError):
    pass


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CocoaPodsPolicyError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc


def _external_source_names(lock_text: str) -> list[str]:
    names: list[str] = []
    in_section = False
    for line in lock_text.splitlines():
        if line == "EXTERNAL SOURCES:":
            in_section = True
            continue
        if in_section and line and not line.startswith(" "):
            break
        if in_section:
            match = re.match(r"^  ([^:]+):\s*$", line)
            if match:
                names.append(match.group(1))
    return names


def inspect() -> dict[str, object]:
    podfile = _read(PODFILE)
    lock = _read(LOCKFILE)
    workflow = _read(WORKFLOW)

    declarations = [
        match.group(1)
        for line in podfile.splitlines()
        if not line.lstrip().startswith("#")
        for match in [_POD_DECLARATION.match(line)]
        if match
    ]
    sources = _external_source_names(lock)
    version = _COCOAPODS_VERSION.search(lock)

    if declarations:
        raise CocoaPodsPolicyError(
            "registry-hosted Pod declarations require a reviewed automation and "
            f"trust-policy extension before use: {sorted(declarations)}"
        )
    if sources != ["Flutter"] or ":path: Flutter" not in lock:
        raise CocoaPodsPolicyError(
            "Podfile.lock must contain only the local Flutter source until an "
            f"external-Pod policy is accepted; observed sources={sources}"
        )
    if version is None:
        raise CocoaPodsPolicyError("Podfile.lock does not bind a CocoaPods version")
    if "pod install --deployment" not in workflow:
        raise CocoaPodsPolicyError(
            "canonical iOS qualification no longer enforces Podfile.lock"
        )

    return {
        "schema_version": 1,
        "mode": "local-flutter-pod-only",
        "external_registry_pods": 0,
        "external_sources": sources,
        "cocoapods_version": version.group(1),
        "ci_lock_enforcement": "pod install --deployment",
        "auto_commit": False,
        "auto_push": False,
        "auto_merge": False,
    }


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def _require_apply_boundary() -> None:
    if os.environ.get(APPROVAL_ENV) != "1":
        raise CocoaPodsPolicyError(
            f"--apply requires {APPROVAL_ENV}=1 from an authorized operator"
        )
    for executable in ("flutter", "pod", "git"):
        if shutil.which(executable) is None:
            raise CocoaPodsPolicyError(f"required executable is unavailable: {executable}")

    branch = _git("branch", "--show-current").stdout.strip()
    if not branch or branch == "main":
        raise CocoaPodsPolicyError(
            "lock refresh must run on a named non-main review branch"
        )
    if _git("status", "--porcelain").stdout:
        raise CocoaPodsPolicyError(
            "lock refresh requires a clean worktree so change custody is unambiguous"
        )


def apply_refresh() -> dict[str, object]:
    _require_apply_boundary()
    subprocess.run(["flutter", "pub", "get"], cwd=ROOT, check=True)
    subprocess.run(
        ["pod", "update"],
        cwd=ROOT / "ios",
        check=True,
        env={**os.environ, "COCOAPODS_DISABLE_STATS": "true"},
    )

    changed = sorted(
        line
        for line in _git("diff", "--name-only").stdout.splitlines()
        if line
    )
    if any(path != "ios/Podfile.lock" for path in changed):
        raise CocoaPodsPolicyError(
            "refresh changed files outside ios/Podfile.lock; inspect without "
            f"committing or pushing: {changed}"
        )
    result = inspect()
    result["changed_files"] = changed
    result["operator_next_step"] = (
        "review the lockfile diff and open an ordinary exact-head pull request"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="inspect the committed Pod graph without network access",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="refresh Podfile.lock on a clean authorized review branch",
    )
    args = parser.parse_args(argv)

    try:
        result = apply_refresh() if args.apply else inspect()
    except (CocoaPodsPolicyError, subprocess.CalledProcessError) as exc:
        print(f"cocoapods-policy: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
