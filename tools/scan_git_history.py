#!/usr/bin/env python3
"""Scan current source and all fetched Git history without secret disclosure."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "provider_token": re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(
        rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"
    ),
}
PATTERN_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "tools/scan_git_history.py",
        "tools/apply_g7_synthesis.py",
        "tools/apply_g7_repair.py",
        "tools/validate_repository.py",
    }
)


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=root)


def object_paths(root: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for raw in git(root, "rev-list", "--objects", "--all").decode(
        "utf-8", errors="replace"
    ).splitlines():
        if raw.strip():
            parts = raw.split(" ", 1)
            records.append((parts[0], parts[1] if len(parts) == 2 else ""))
    return records


def head_blob_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for raw in git(root, "ls-tree", "-r", "--full-tree", "HEAD").decode(
        "utf-8", errors="replace"
    ).splitlines():
        metadata, _, _path = raw.partition("\t")
        parts = metadata.split()
        if len(parts) >= 3 and parts[1] == "blob":
            ids.add(parts[2])
    return ids


def scan_blob(
    data: bytes,
    *,
    path: str,
    object_id: str,
    current_tree: bool = False,
) -> list[dict[str, str]]:
    if path in PATTERN_DEFINITION_PATHS:
        return []
    findings: list[dict[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            findings.append(
                {
                    "pattern": name,
                    "path": path or "<unpathed-blob>",
                    "object": object_id,
                    "fingerprint": hashlib.sha256(match.group(0)).hexdigest(),
                    "scope": "current-tree" if current_tree else "historical-only",
                }
            )
    return findings


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    current_ids = head_blob_ids(root)
    paths_by_object: dict[str, set[str]] = {}
    for object_id, path in object_paths(root):
        paths_by_object.setdefault(object_id, set()).add(path)
    findings: list[dict[str, str]] = []
    scanned_blobs = 0
    bytes_scanned = 0
    for object_id in sorted(paths_by_object):
        if git(root, "cat-file", "-t", object_id).decode().strip() != "blob":
            continue
        data = git(root, "cat-file", "blob", object_id)
        scanned_blobs += 1
        bytes_scanned += len(data)
        paths = sorted(value for value in paths_by_object[object_id] if value) or [""]
        for path in paths:
            findings.extend(
                scan_blob(
                    data,
                    path=path,
                    object_id=object_id,
                    current_tree=object_id in current_ids,
                )
            )
    unique = {
        (
            item["pattern"],
            item["path"],
            item["object"],
            item["fingerprint"],
            item["scope"],
        ): item
        for item in findings
    }
    ordered = [unique[key] for key in sorted(unique)]
    blocking = [item for item in ordered if item["scope"] == "current-tree"]
    historical = [item for item in ordered if item["scope"] == "historical-only"]
    return {
        "schema_version": 1,
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "scope": "all-fetched-refs-and-deduplicated-blobs",
        "ref_count": len(
            git(root, "for-each-ref", "--format=%(refname)").decode().splitlines()
        ),
        "commit_count": int(
            git(root, "rev-list", "--all", "--count").decode().strip()
        ),
        "scanned_blob_count": scanned_blobs,
        "bytes_scanned": bytes_scanned,
        "skipped_large_blob_count": 0,
        "finding_count": len(ordered),
        "blocking_finding_count": len(blocking),
        "historical_finding_count": len(historical),
        "findings": ordered,
        "redaction": "match material is never emitted; fingerprint is SHA-256",
        "historical_incident_policy": (
            "Historical-only findings require provider rotation/revocation or "
            "administrator-authorized history rewrite before product release."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    report = build_report(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "head": report["head"],
                "finding_count": report["finding_count"],
                "blocking_finding_count": report["blocking_finding_count"],
                "historical_finding_count": report["historical_finding_count"],
                "scanned_blob_count": report["scanned_blob_count"],
            },
            separators=(",", ":"),
        )
    )
    return int(bool(report["blocking_finding_count"] and not args.report_only))


if __name__ == "__main__":
    raise SystemExit(main())
