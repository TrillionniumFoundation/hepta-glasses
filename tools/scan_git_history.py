#!/usr/bin/env python3
"""Scan every fetched Git object without printing possible secret material."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

MAX_BLOB_BYTES = 16 * 1024 * 1024
ACKNOWLEDGEMENTS_PATH = Path("contracts/history-scan-acknowledgements-v1.json")
PATTERNS = {
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
}
PATTERN_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "tools/scan_git_history.py",
        "tools/validate_repository.py",
    }
)



def load_acknowledgements(root: Path) -> list[dict[str, str]]:
    path = root / ACKNOWLEDGEMENTS_PATH
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"history acknowledgement contract is invalid: {error}") from error
    if document.get("schema_version") != 1:
        raise RuntimeError("history acknowledgement contract schema_version must be 1")
    raw_entries = document.get("acknowledgements")
    if not isinstance(raw_entries, list):
        raise RuntimeError("history acknowledgement contract must contain a list")

    entries: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise RuntimeError(f"history acknowledgement {index} is not an object")
        required = ("id", "pattern", "path", "fingerprint", "classification", "reason")
        if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
            raise RuntimeError(f"history acknowledgement {index} has invalid fields")
        entry = {key: raw[key].strip() for key in required}
        if entry["id"] in seen_ids:
            raise RuntimeError(f"duplicate history acknowledgement id: {entry['id']}")
        if entry["pattern"] not in PATTERNS:
            raise RuntimeError(f"unknown history acknowledgement pattern: {entry['pattern']}")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["fingerprint"]):
            raise RuntimeError(f"invalid history acknowledgement fingerprint: {entry['id']}")
        if entry["classification"] != "synthetic_test_fixture":
            raise RuntimeError(f"history acknowledgement {entry['id']} is not a synthetic fixture")
        key = (entry["pattern"], entry["path"], entry["fingerprint"])
        if key in seen_keys:
            raise RuntimeError(f"duplicate history acknowledgement key: {entry['id']}")
        seen_ids.add(entry["id"]); seen_keys.add(key); entries.append(entry)
    return entries

def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=root)


def object_paths(root: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for raw in git(root, "rev-list", "--objects", "--all").decode(
        "utf-8", errors="replace"
    ).splitlines():
        if not raw.strip():
            continue
        parts = raw.split(" ", 1)
        records.append((parts[0], parts[1] if len(parts) == 2 else ""))
    return records


def _fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def scan_blob(data: bytes, *, path: str, object_id: str) -> list[dict[str, str]]:
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
                    "fingerprint": _fingerprint(match.group(0)),
                }
            )
    return findings


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    records = object_paths(root)
    paths_by_object: dict[str, set[str]] = {}
    for object_id, path in records:
        paths_by_object.setdefault(object_id, set()).add(path)

    findings: list[dict[str, str]] = []
    scanned_blobs = 0
    bytes_scanned = 0
    unscanned_blobs: list[dict[str, object]] = []
    for object_id in sorted(paths_by_object):
        object_type = git(root, "cat-file", "-t", object_id).decode().strip()
        if object_type != "blob":
            continue
        size = int(git(root, "cat-file", "-s", object_id).decode().strip())
        if size > MAX_BLOB_BYTES:
            paths = sorted(
                value for value in paths_by_object[object_id] if value
            ) or [""]
            unscanned_blobs.append(
                {
                    "object": object_id,
                    "paths": paths,
                    "size": size,
                }
            )
            continue
        data = git(root, "cat-file", "blob", object_id)
        scanned_blobs += 1
        bytes_scanned += len(data)
        paths = sorted(value for value in paths_by_object[object_id] if value) or [""]
        for path in paths:
            findings.extend(scan_blob(data, path=path, object_id=object_id))

    refs = git(root, "for-each-ref", "--format=%(refname)").decode().splitlines()
    commit_count = int(git(root, "rev-list", "--all", "--count").decode().strip())
    head = git(root, "rev-parse", "HEAD").decode().strip()
    unique_findings = {
        (item["pattern"], item["path"], item["object"], item["fingerprint"]): item
        for item in findings
    }
    raw_ordered = [unique_findings[key] for key in sorted(unique_findings)]
    acknowledgements = load_acknowledgements(root)
    acknowledgements_by_key = {
        (item["pattern"], item["path"], item["fingerprint"]): item
        for item in acknowledgements
    }
    matched_acknowledgement_ids: set[str] = set()
    acknowledged_findings: list[dict[str, str]] = []
    unacknowledged_findings: list[dict[str, str]] = []
    for finding in raw_ordered:
        key = (finding["pattern"], finding["path"], finding["fingerprint"])
        acknowledgement = acknowledgements_by_key.get(key)
        if acknowledgement is None:
            unacknowledged_findings.append(finding)
            continue
        matched_acknowledgement_ids.add(acknowledgement["id"])
        acknowledged_findings.append({**finding, "acknowledgement_id": acknowledgement["id"], "classification": acknowledgement["classification"]})
    unused_acknowledgements = [
        {"id": item["id"], "pattern": item["pattern"], "path": item["path"], "fingerprint": item["fingerprint"]}
        for item in acknowledgements
        if item["id"] not in matched_acknowledgement_ids
    ]
    return {
        "schema_version": 1,
        "head": head,
        "scope": "all-fetched-refs-and-deduplicated-blobs",
        "ref_count": len(refs),
        "commit_count": commit_count,
        "scanned_blob_count": scanned_blobs,
        "bytes_scanned": bytes_scanned,
        "unscanned_blob_count": len(unscanned_blobs),
        "unscanned_blobs": unscanned_blobs,
        "raw_finding_count": len(raw_ordered),
        "acknowledged_finding_count": len(acknowledged_findings),
        "acknowledged_findings": acknowledged_findings,
        "unused_acknowledgement_count": len(unused_acknowledgements),
        "unused_acknowledgements": unused_acknowledgements,
        "finding_count": len(unacknowledged_findings),
        "findings": unacknowledged_findings,
        "redaction": "match material is never emitted; fingerprint is SHA-256",
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    report = build_report(args.root)
    write_report(args.output, report)
    print(
        json.dumps(
            {
                "head": report["head"],
                "raw_finding_count": report["raw_finding_count"],
                "acknowledged_finding_count": report["acknowledged_finding_count"],
                "finding_count": report["finding_count"],
                "unused_acknowledgement_count": report["unused_acknowledgement_count"],
                "scanned_blob_count": report["scanned_blob_count"],
                "unscanned_blob_count": report["unscanned_blob_count"],
            },
            separators=(",", ":"),
        )
    )
    if (report["finding_count"] or report["unscanned_blob_count"] or report["unused_acknowledgement_count"]) and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
