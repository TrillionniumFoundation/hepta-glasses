#!/usr/bin/env python3
"""Apply or verify the canonical main-branch protection contract.

No token is stored. `--apply` requires HEPTA_REPO_ADMIN_TOKEN at invocation time.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.governance import evaluate_branch_protection


API_VERSION = "2022-11-28"


def request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            document = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError("github_governance_request_failed") from error
    if not isinstance(document, dict):
        raise RuntimeError("github_governance_response_invalid")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="TrillionniumFoundation/hepta-glasses")
    parser.add_argument("--branch", default="main")
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("contracts/main-branch-protection-v1.json"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise SystemExit("invalid protection contract")
    token = os.environ.get("HEPTA_REPO_ADMIN_TOKEN", "")
    url = f"https://api.github.com/repos/{args.repo}/branches/{args.branch}/protection"

    if args.apply:
        if not token:
            print(json.dumps({"ok": False, "error": "admin_token_required"}))
            return 2
        request_json(url, token=token, method="PUT", payload=contract)

    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    else:
        if not token:
            print(json.dumps({"ok": False, "error": "admin_token_required"}))
            return 2
        snapshot = request_json(url, token=token)
    if not isinstance(snapshot, dict):
        print(json.dumps({"ok": False, "error": "snapshot_invalid"}))
        return 2
    result = evaluate_branch_protection(snapshot, contract)
    print(
        json.dumps(
            {"ok": result.passed, "checks": result.checks, "missing": result.missing},
            separators=(",", ":"),
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
