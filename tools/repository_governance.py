#!/usr/bin/env python3
"""Apply or verify the canonical main-branch protection contract.

No token is stored. ``--apply`` requires ``HEPTA_REPO_ADMIN_TOKEN`` at
invocation time. Applying always performs a fresh API readback; an offline
snapshot can never be used to authorize an apply operation.
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification.governance import (
    evaluate_branch_protection,
    is_canonical_branch_protection_contract,
)


API_VERSION = "2022-11-28"
CANONICAL_REPOSITORY = "TrillionniumFoundation/hepta-glasses"
CANONICAL_BRANCH = "main"
MAX_JSON_BYTES = 1024 * 1024


class GovernanceInputError(ValueError):
    """Stable fail-closed error for local or remote governance JSON."""


def _reject_json_constant(value: str) -> None:
    raise GovernanceInputError(f"non_finite_json_number:{value}")


def _reject_duplicate_object(
    pairs: Iterable[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GovernanceInputError(f"duplicate_json_member:{key}")
        result[key] = value
    return result


def decode_json_object(
    raw: bytes,
    label: str,
    *,
    maximum_bytes: int = MAX_JSON_BYTES,
) -> dict[str, Any]:
    """Decode one bounded, BOM-free, duplicate-free UTF-8 JSON object."""

    if len(raw) > maximum_bytes:
        raise GovernanceInputError(f"{label}_too_large")
    if raw.startswith(codecs.BOM_UTF8):
        raise GovernanceInputError(f"{label}_utf8_bom_prohibited")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except GovernanceInputError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise GovernanceInputError(f"{label}_invalid_json") from error
    if not isinstance(value, dict):
        raise GovernanceInputError(f"{label}_must_be_object")
    return value


def read_json_object(
    path: Path,
    label: str,
    *,
    maximum_bytes: int = MAX_JSON_BYTES,
) -> dict[str, Any]:
    """Read one bounded regular JSON file without following a symlink."""

    try:
        if path.is_symlink() or not path.is_file():
            raise GovernanceInputError(f"{label}_must_be_regular_file")
        size = path.stat().st_size
        if size > maximum_bytes:
            raise GovernanceInputError(f"{label}_too_large")
        raw = path.read_bytes()
    except GovernanceInputError:
        raise
    except OSError as error:
        raise GovernanceInputError(f"{label}_unreadable") from error
    return decode_json_object(raw, label, maximum_bytes=maximum_bytes)


def branch_protection_payload(contract: dict[str, Any]) -> dict[str, Any]:
    """Project the closed repository contract onto GitHub's PUT payload."""

    if not is_canonical_branch_protection_contract(contract):
        raise GovernanceInputError("protection_contract_noncanonical")
    payload = json.loads(
        json.dumps(
            contract,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    status = payload.get("required_status_checks")
    if not isinstance(status, dict):
        raise GovernanceInputError("protection_contract_status_invalid")
    status.pop("contexts", None)
    return payload


def request_json(
    url: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform one authenticated GitHub request and strictly decode the object."""

    data = None
    if payload is not None:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
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
            raw = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"github_governance_http_status_{error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError("github_governance_request_failed") from error

    try:
        return decode_json_object(raw, "github_governance_response")
    except GovernanceInputError as error:
        raise RuntimeError("github_governance_response_invalid") from error


def _emit(document: dict[str, Any], *, stderr: bool = False) -> None:
    print(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ),
        file=sys.stderr if stderr else sys.stdout,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=CANONICAL_REPOSITORY)
    parser.add_argument("--branch", default=CANONICAL_BRANCH)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("contracts/main-branch-protection-v1.json"),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()

    if args.apply and args.snapshot is not None:
        parser.error("--apply cannot be combined with --snapshot")
    if (
        args.repo != CANONICAL_REPOSITORY
        or args.branch != CANONICAL_BRANCH
    ):
        _emit({"ok": False, "error": "canonical_target_required"}, stderr=True)
        return 2

    try:
        contract = read_json_object(args.contract, "protection_contract")
    except GovernanceInputError as error:
        _emit({"ok": False, "error": str(error)}, stderr=True)
        return 2
    if not is_canonical_branch_protection_contract(contract):
        _emit(
            {"ok": False, "error": "protection_contract_noncanonical"},
            stderr=True,
        )
        return 2

    token = os.environ.get("HEPTA_REPO_ADMIN_TOKEN", "")
    url = (
        f"https://api.github.com/repos/{args.repo}/branches/"
        f"{args.branch}/protection"
    )

    try:
        if args.apply:
            if not token:
                _emit({"ok": False, "error": "admin_token_required"})
                return 2
            request_json(
                url,
                token=token,
                method="PUT",
                payload=branch_protection_payload(contract),
            )

        if args.snapshot is not None:
            snapshot = read_json_object(
                args.snapshot,
                "protection_snapshot",
            )
        else:
            if not token:
                _emit({"ok": False, "error": "admin_token_required"})
                return 2
            snapshot = request_json(url, token=token)
    except GovernanceInputError as error:
        _emit({"ok": False, "error": str(error)}, stderr=True)
        return 2
    except RuntimeError as error:
        _emit({"ok": False, "error": str(error)}, stderr=True)
        return 2

    result = evaluate_branch_protection(snapshot, contract)
    _emit(
        {
            "ok": result.passed,
            "checks": result.checks,
            "missing": result.missing,
        }
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
