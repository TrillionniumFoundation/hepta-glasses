#!/usr/bin/env python3
"""Scan every fetched Git object with exact fixture/history acknowledgements."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

MAX_BLOB_BYTES = 16 * 1024 * 1024
DEFAULT_ACKNOWLEDGEMENTS = Path(
    "docs/security/HISTORY_SECRET_ACKNOWLEDGEMENTS.json"
)
PATTERNS = {
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "provider_token": re.compile(
        rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"
    ),
    "aws_access_key": re.compile(
        rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"
    ),
}
PATTERN_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "tools/scan_git_history.py",
        "tools/validate_repository.py",
    }
)


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=root)


def object_paths(root: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    output = git(root, "rev-list", "--objects", "--all").decode(
        "utf-8", errors="replace"
    )
    for raw in output.splitlines():
        if not raw.strip():
            continue
        parts = raw.split(" ", 1)
        result.append((parts[0], parts[1] if len(parts) == 2 else ""))
    return result


def head_blob_ids(root: Path) -> set[str]:
    output = git(root, "ls-tree", "-r", "--full-tree", "HEAD").decode(
        "utf-8", errors="replace"
    )
    result: set[str] = set()
    for row in output.splitlines():
        metadata, separator, _ = row.partition("\t")
        fields = metadata.split()
        if separator and len(fields) == 3 and fields[1] == "blob":
            result.add(fields[2])
    return result


def is_fixture_path(path: str) -> bool:
    name = Path(path).name
    return (
        path.startswith("test/")
        or "/src/test/" in path
        or name.startswith("test_")
        or path.startswith("tools/test")
        or path.startswith("evidence/fixtures/")
    )


def fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def finding_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        str(item[field])
        for field in ("pattern", "path", "object", "fingerprint")
    )


def scan_blob(
    data: bytes,
    *,
    path: str,
    object_id: str,
) -> list[dict[str, str]]:
    if path in PATTERN_DEFINITION_PATHS:
        return []
    result: list[dict[str, str]] = []
    for pattern_name, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            result.append(
                {
                    "pattern": pattern_name,
                    "path": path or "<unpathed-blob>",
                    "object": object_id,
                    "fingerprint": fingerprint(match.group(0)),
                }
            )
    return result


def load_acknowledgements(
    root: Path,
    relative_path: Path,
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    path = relative_path if relative_path.is_absolute() else root / relative_path
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("acknowledgement schema_version must equal 1")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("acknowledgement entries must be a list")
    result: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("acknowledgement entry must be an object")
        key = finding_key(entry)
        if key in result:
            raise ValueError(f"duplicate acknowledgement: {key}")
        scope = entry.get("scope")
        if scope not in {
            "non_secret_test_fixture",
            "historical_object_unreachable_from_candidate_head",
        }:
            raise ValueError(f"invalid acknowledgement scope: {scope}")
        result[key] = entry
    return result


def build_report(
    root: Path,
    acknowledgement_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    paths_by_object: dict[str, set[str]] = {}
    for object_id, path in object_paths(root):
        paths_by_object.setdefault(object_id, set()).add(path)

    raw_findings: list[dict[str, str]] = []
    unscanned: list[dict[str, Any]] = []
    scanned_blobs = 0
    bytes_scanned = 0
    for object_id in sorted(paths_by_object):
        if git(root, "cat-file", "-t", object_id).decode().strip() != "blob":
            continue
        size = int(git(root, "cat-file", "-s", object_id).decode().strip())
        paths = sorted(path for path in paths_by_object[object_id] if path) or [""]
        if size > MAX_BLOB_BYTES:
            unscanned.append(
                {"object": object_id, "paths": paths, "size": size}
            )
            continue
        data = git(root, "cat-file", "blob", object_id)
        scanned_blobs += 1
        bytes_scanned += len(data)
        for path in paths:
            raw_findings.extend(
                scan_blob(data, path=path, object_id=object_id)
            )

    unique = {finding_key(item): item for item in raw_findings}
    ordered = [unique[key] for key in sorted(unique)]
    current_ids = head_blob_ids(root)
    acknowledgements = load_acknowledgements(root, acknowledgement_path)

    acknowledged_current: list[dict[str, str]] = []
    acknowledged_historical: list[dict[str, str]] = []
    actionable: list[dict[str, str]] = []
    observed_acknowledgement_keys: set[tuple[str, str, str, str]] = set()
    for item in ordered:
        key = finding_key(item)
        entry = acknowledgements.get(key)
        current = item["object"] in current_ids
        if current:
            valid_fixture = bool(
                entry
                and entry.get("scope") == "non_secret_test_fixture"
                and is_fixture_path(item["path"])
            )
            if valid_fixture:
                acknowledged_current.append(item)
                observed_acknowledgement_keys.add(key)
            else:
                actionable.append(item)
        else:
            valid_historical = bool(
                entry
                and entry.get("scope")
                == "historical_object_unreachable_from_candidate_head"
            )
            if valid_historical:
                acknowledged_historical.append(item)
                observed_acknowledgement_keys.add(key)
            else:
                actionable.append(item)

    stale = sorted(set(acknowledgements) - observed_acknowledgement_keys)
    refs = git(root, "for-each-ref", "--format=%(refname)").decode().splitlines()
    return {
        "schema_version": 2,
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "scope": "all-fetched-refs-and-deduplicated-blobs",
        "ref_count": len(refs),
        "commit_count": int(
            git(root, "rev-list", "--all", "--count").decode().strip()
        ),
        "scanned_blob_count": scanned_blobs,
        "bytes_scanned": bytes_scanned,
        "unscanned_blob_count": len(unscanned),
        "unscanned_blobs": unscanned,
        "raw_finding_count": len(ordered),
        "finding_count": len(actionable),
        "acknowledged_current_fixture_count": len(acknowledged_current),
        "acknowledged_historical_finding_count": len(
            acknowledged_historical
        ),
        "stale_acknowledgement_count": len(stale),
        "findings": actionable,
        "acknowledged_current_fixture_findings": acknowledged_current,
        "acknowledged_historical_findings": acknowledged_historical,
        "stale_acknowledgement_keys": [list(key) for key in stale],
        "redaction": "match material is never emitted; fingerprint is SHA-256",
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--acknowledgements",
        type=Path,
        default=DEFAULT_ACKNOWLEDGEMENTS,
    )
    parser.add_argument("--report-only", action="store_true")
    arguments = parser.parse_args()
    report = build_report(arguments.root, arguments.acknowledgements)
    write_report(arguments.output, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "head",
                    "finding_count",
                    "raw_finding_count",
                    "acknowledged_current_fixture_count",
                    "acknowledged_historical_finding_count",
                    "stale_acknowledgement_count",
                    "scanned_blob_count",
                    "unscanned_blob_count",
                )
            },
            separators=(",", ":"),
        )
    )
    failed = bool(
        report["finding_count"]
        or report["unscanned_blob_count"]
        or report["stale_acknowledgement_count"]
    )
    return 1 if failed and not arguments.report_only else 0


if __name__ == "__main__":
    raise SystemExit(main())
