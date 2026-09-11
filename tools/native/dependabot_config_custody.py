#!/usr/bin/env python3
"""Closed-world custody for the repository's complete Dependabot configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".github/dependabot.yml"

# SHA-256 of the complete reviewed 749-byte LF-terminated object.
# Any byte movement requires an ordinary source change, seven-job qualification,
# exact-head Artifact verification, and eligible review.
_APPROVED_CONFIG_SHA256 = (
    "c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5"
)
_EXPECTED_ECOSYSTEMS = ("github-actions", "pub", "gradle")
_EXPECTED_DIRECTORIES = ("/", "/", "/android")
_EXPECTED_TIMES = ("03:00", "03:15", "03:30")
_EXPECTED_PREFIXES = ("deps(actions)", "deps(dart)", "deps(android)")

_ECOSYSTEM_KEY = re.compile(
    r"(?m)^[ \t]*-[ \t]*package-ecosystem[ \t]*:"
)
_CANONICAL_ECOSYSTEM = re.compile(
    r"(?m)^  - package-ecosystem: ([a-z0-9][a-z0-9-]*)$"
)
_CANONICAL_DIRECTORY = re.compile(r'(?m)^    directory: "([^"\r\n]+)"$')
_CANONICAL_TIME = re.compile(r'(?m)^      time: "([0-9]{2}:[0-9]{2})"$')
_CANONICAL_PREFIX = re.compile(r'(?m)^      prefix: "([^"\r\n]+)"$')


class DependabotConfigError(RuntimeError):
    pass


def _closed_bytes(text: str) -> bytes:
    if "\ufeff" in text or "\x00" in text or "\r" in text:
        raise DependabotConfigError(
            "Dependabot configuration contains a forbidden BOM, NUL, or CR byte"
        )
    lines = text.splitlines()
    if not lines or any("\t" in line or line.rstrip(" ") != line for line in lines):
        raise DependabotConfigError(
            "Dependabot configuration must be non-empty LF text without tabs "
            "or trailing spaces"
        )
    if not text.endswith("\n") or text.endswith("\n\n"):
        raise DependabotConfigError(
            "Dependabot configuration must have exactly one final LF"
        )
    return text.encode("utf-8")


def verify_text(text: str) -> dict[str, Any]:
    raw = _closed_bytes(text)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != _APPROVED_CONFIG_SHA256:
        raise DependabotConfigError(
            "complete Dependabot object differs from the reviewed SHA-256: "
            f"observed={digest}, expected={_APPROVED_CONFIG_SHA256}"
        )

    if not text.startswith("version: 2\n\nupdates:\n"):
        raise DependabotConfigError(
            "Dependabot object does not start with the reviewed version/updates shape"
        )
    key_count = len(_ECOSYSTEM_KEY.findall(text))
    ecosystems = tuple(_CANONICAL_ECOSYSTEM.findall(text))
    directories = tuple(_CANONICAL_DIRECTORY.findall(text))
    times = tuple(_CANONICAL_TIME.findall(text))
    prefixes = tuple(_CANONICAL_PREFIX.findall(text))
    if key_count != 3 or ecosystems != _EXPECTED_ECOSYSTEMS:
        raise DependabotConfigError(
            "Dependabot ecosystem key set/order differs from the reviewed object"
        )
    if directories != _EXPECTED_DIRECTORIES:
        raise DependabotConfigError(
            "Dependabot directory set/order differs from the reviewed object"
        )
    if times != _EXPECTED_TIMES:
        raise DependabotConfigError(
            "Dependabot schedule set/order differs from the reviewed object"
        )
    if prefixes != _EXPECTED_PREFIXES:
        raise DependabotConfigError(
            "Dependabot commit-prefix set/order differs from the reviewed object"
        )
    if text.count("      interval: weekly\n") != 3:
        raise DependabotConfigError("every reviewed ecosystem must run weekly")
    if text.count("      day: monday\n") != 3:
        raise DependabotConfigError("every reviewed ecosystem must run Monday")
    if text.count('      timezone: "Asia/Singapore"\n') != 3:
        raise DependabotConfigError(
            "every reviewed ecosystem must use Asia/Singapore"
        )
    if text.count("    open-pull-requests-limit: 5\n") != 3:
        raise DependabotConfigError(
            "every reviewed ecosystem must retain the five-proposal bound"
        )

    folded = text.casefold()
    for prohibited in (
        "auto-merge",
        "automerge",
        "target-branch:",
        "insecure-external-code-execution: allow",
        "registries:",
        "package-ecosystem: cocoapods",
        'package-ecosystem: "cocoapods"',
        "package-ecosystem: swift",
        'package-ecosystem: "swift"',
    ):
        if prohibited in folded:
            raise DependabotConfigError(
                f"prohibited Dependabot authority/configuration token: {prohibited}"
            )

    return {
        "schema_version": 1,
        "config_sha256": digest,
        "size_bytes": len(raw),
        "ecosystems": list(ecosystems),
        "directories": list(directories),
        "schedule_times": list(times),
        "timezone": "Asia/Singapore",
        "open_pull_request_limit_each": 5,
        "auto_merge": False,
        "target_branch_override": False,
        "external_registries": False,
        "passed": True,
    }


def verify_path(path: Path = CONFIG) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DependabotConfigError(f"cannot read {path}: {exc}") from exc
    return verify_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the complete reviewed Dependabot object",
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        result = verify_path()
    except DependabotConfigError as exc:
        print(f"dependabot-config-custody: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
