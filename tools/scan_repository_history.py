#!/usr/bin/env python3
"""Secret-history scanner that emits fingerprints, never credential values."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


SCAN_PATHS = (
    "lib",
    "android",
    "ios",
    "services",
    "adapters",
    "plugins",
)
CANDIDATE_PATTERN = (
    r"-----BEGIN|gh[pousr]_|sk-|AKIA|AIza|Bearer|"
    r"[Aa][Pp][Ii][_-]?[Kk][Ee][Yy]|[Tt][Oo][Kk][Ee][Nn]"
)
SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ),
    (
        "provider_api_key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{24,}\b"),
    ),
    (
        "assigned_credential",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret)
            \s*[:=]\s*
            ["'][A-Za-z0-9._~+/=-]{24,}["']
            """
        ),
    ),
)


class HistoryScanError(RuntimeError):
    pass


def _git(
    root: Path,
    *arguments: str,
    allow_no_match: bool = False,
) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode == 0:
        return process.stdout
    if allow_no_match and process.returncode == 1:
        return ""
    message = process.stderr.strip() or process.stdout.strip() or "git failed"
    raise HistoryScanError(message)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _candidate_lines(root: Path, commit: str) -> Iterable[tuple[str, int, str]]:
    output = _git(
        root,
        "grep",
        "-I",
        "-n",
        "-E",
        "-e",
        CANDIDATE_PATTERN,
        commit,
        "--",
        *SCAN_PATHS,
        allow_no_match=True,
    )
    for raw in output.splitlines():
        parts = raw.split(":", 3)
        if len(parts) != 4:
            continue
        _, path, line_number, text = parts
        try:
            line = int(line_number)
        except ValueError:
            continue
        yield path, line, text


def _findings_for_commit(root: Path, commit: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for path, line, text in _candidate_lines(root, commit):
        for rule, pattern in SECRET_RULES:
            for match in pattern.finditer(text):
                fingerprint = _fingerprint(match.group(0))
                key = (path, line, rule, fingerprint)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    {
                        "commit": commit,
                        "fingerprint_sha256": fingerprint,
                        "line": line,
                        "path": path,
                        "rule": rule,
                    }
                )
    return findings


def build_history_report(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if _git(root, "rev-parse", "--is-inside-work-tree").strip() != "true":
        raise HistoryScanError("repository is not a Git work tree")
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise HistoryScanError("full Git history is required for credential scanning")

    head = _git(root, "rev-parse", "HEAD").strip()
    commits = [
        line.strip()
        for line in _git(root, "rev-list", "--all").splitlines()
        if line.strip()
    ]
    if head not in commits:
        commits.insert(0, head)

    findings: list[dict[str, Any]] = []
    for commit in commits:
        findings.extend(_findings_for_commit(root, commit))
        if len(findings) > 5000:
            raise HistoryScanError("credential history finding limit exceeded")

    current = [item for item in findings if item["commit"] == head]
    historical = [item for item in findings if item["commit"] != head]
    unique_fingerprints = sorted(
        {str(item["fingerprint_sha256"]) for item in historical}
    )
    return {
        "schema_version": 1,
        "repository": os.environ.get("GITHUB_REPOSITORY", root.name),
        "head": head,
        "scan_paths": list(SCAN_PATHS),
        "history_commit_count": len(commits),
        "current_tree_findings_count": len(current),
        "current_tree_findings": current,
        "historical_findings_count": len(historical),
        "historical_unique_fingerprint_count": len(unique_fingerprints),
        "historical_findings": historical,
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-current", action="store_true")
    parser.add_argument("--fail-on-history", action="store_true")
    args = parser.parse_args()

    try:
        report = build_history_report(args.root)
    except (OSError, HistoryScanError) as error:
        print(
            json.dumps(
                {"ok": False, "error": "history_scan_failed", "detail": str(error)},
                separators=(",", ":"),
            )
        )
        return 2

    if args.output is not None:
        output = args.output
        if not output.is_absolute():
            output = args.root.resolve() / output
        write_report(output, report)

    current = int(report["current_tree_findings_count"])
    historical = int(report["historical_findings_count"])
    passed = not (
        (args.fail_on_current and current > 0)
        or (args.fail_on_history and historical > 0)
    )
    print(
        json.dumps(
            {
                "ok": passed,
                "head": report["head"],
                "current_tree_findings": current,
                "historical_findings": historical,
                "historical_unique_fingerprints": report[
                    "historical_unique_fingerprint_count"
                ],
            },
            separators=(",", ":"),
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
