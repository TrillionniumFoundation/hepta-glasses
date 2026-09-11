from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_JSON_CONTRACT = ROOT / "contracts/conformance/canonical-json-v1.json"

class ContractError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON value is forbidden: {value}")


def _reject_duplicate_members(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def strict_json_loads(source: str) -> Any:
    try:
        return json.loads(
            source,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


def strict_json_file(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read {path.relative_to(ROOT)}: {exc}") from exc
    if not raw or raw.startswith(b"\xef\xbb\xbf"):
        raise ContractError("contract must be non-empty UTF-8 without BOM")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"contract is not strict UTF-8: {exc}") from exc
    return strict_json_loads(source)


def _closed_object(
    value: Any,
    fields: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        observed = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise ContractError(
            f"{label} must use exact closed fields; observed={observed}"
        )
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{label} keys must be strings")
    return value


def _exact_ids(
    values: list[dict[str, Any]],
    expected: list[str],
    label: str,
) -> None:
    identifiers = [value.get("id") for value in values]
    if identifiers != expected or len(identifiers) != len(set(identifiers)):
        raise ContractError(
            f"{label} identity/order drift: observed={identifiers}"
        )


def _integer(
    value: Any,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ContractError(f"{label} is outside [{minimum}, {maximum}]")
    return value


def _hex(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be lowercase hexadecimal text")
    if len(value) % 2 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{label} must be lowercase hexadecimal text")
    return bytes.fromhex(value)


def _hex_list(value: Any, label: str, *, allow_empty: bool = False) -> list[bytes]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) for item in value)
    ):
        raise ContractError(f"{label} must be an array of hex strings")
    return [_hex(item, label) for item in value]


def canonical_json(value: object) -> str:
    if isinstance(value, dict) and any(not isinstance(key, str) for key in value):
        raise TypeError("canonical JSON object keys must be strings")
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


