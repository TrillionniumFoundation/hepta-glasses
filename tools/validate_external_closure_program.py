#!/usr/bin/env python3
"""Validate the complete external-authority closure program.

The program is a source-side execution contract. Validation proves that every
remaining Administration, external, and upstream gate has a real authority,
source preparation, evidence requirements, acceptance rules, prohibited
substitutes, and reopening conditions. It never promotes a blocked gate to
closed merely because this validator passes.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = Path("docs/EXTERNAL_CLOSURE_PROGRAM.json")
SCHEMA = Path("schemas/external-closure-program.schema.json")
RUNBOOK = Path("docs/operations/EXTERNAL_CLOSURE_ORCHESTRATION.md")
MAX_PROGRAM_BYTES = 512 * 1024
MAX_SCHEMA_BYTES = 128 * 1024
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AUTHORITY = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
GAP_ID = re.compile(r"^(?:HG-[0-9]{4}|G10-TRUST-REGISTRY)$")
ALLOWED_STATUSES = (
    "BLOCKED_ADMIN_SETTING",
    "BLOCKED_EXTERNAL",
    "BLOCKED_UPSTREAM",
)
TOP_LEVEL_KEYS = {
    "schema_version",
    "program_id",
    "candidate_identity_rule",
    "claim_ceiling",
    "terminal_blocking_statuses",
    "gates",
}
GATE_KEYS = {
    "id",
    "gap_ids",
    "issue_numbers",
    "authority_class",
    "status",
    "owner",
    "source_preparation",
    "evidence_required",
    "acceptance",
    "prohibited_substitutes",
    "reopens_on",
}
EXPECTED_GATES: tuple[
    tuple[str, tuple[str, ...], tuple[int, ...], str], ...
] = (
    (
        "main-protection-and-adoption",
        ("HG-0017", "HG-0089"),
        (84, 102),
        "BLOCKED_ADMIN_SETTING",
    ),
    (
        "out-of-band-authority-registry",
        ("G10-TRUST-REGISTRY",),
        (96,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "authenticated-independent-review",
        ("HG-0044",),
        (85,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "provider-credential-incident",
        ("HG-0013",),
        (86,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "production-model-provider",
        ("HG-0014",),
        (87,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "production-identity-kms-attestation",
        ("HG-0015",),
        (88,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "production-realtime-oauth",
        ("HG-0021",),
        (89,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "production-capability-adapters",
        ("HG-0022",),
        (90,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "physical-g1-qualification",
        ("HG-0010",),
        (91,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "production-speech-qualification",
        ("HG-0018",),
        (92,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "independent-assurance",
        ("HG-0011",),
        (93,),
        "BLOCKED_EXTERNAL",
    ),
    (
        "vendor-firmware-authority",
        ("HG-0016",),
        (94,),
        "BLOCKED_UPSTREAM",
    ),
    (
        "signed-release-pilot-and-stores",
        ("HG-0012",),
        (95,),
        "BLOCKED_EXTERNAL",
    ),
)
EXPECTED_ISSUES = frozenset(
    {84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 102}
)
REQUIRED_CLAIM_CEILING_PHRASES = (
    "does not close",
    "without evidence issued and accepted by the named external authority",
)
REQUIRED_IDENTITY_PHRASES = (
    "live convergence pull-request head commit",
    "Any movement reopens the affected gate",
)
REQUIRED_RUNBOOK_PHRASES = (
    "cannot issue its own external authority",
    "synthetic=false",
    "no override",
    "A GitHub issue closes only when",
    "do not prove that an external transaction has occurred",
)
PROHIBITED_FALSE_CLOSURE_PHRASES = (
    "all external gates are closed",
    "synthetic evidence is accepted",
    "screenshots close",
    "self-review is sufficient",
    "administrator bypass is permitted",
)


class ExternalClosureProgramError(ValueError):
    """Stable validation failure for the closure-program boundary."""


def fail(message: str) -> None:
    raise ExternalClosureProgramError(message)


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        fail(f"required JSON file is missing or linked: {path}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        fail(f"cannot read {path}: {error}")
    if not raw or len(raw) > maximum_bytes:
        fail(f"JSON file has invalid bounded size: {path}")
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"JSON file contains a UTF-8 BOM: {path}")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: fail(
                f"non-finite JSON number is prohibited: {token}"
            ),
        )
    except ExternalClosureProgramError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(
            f"{label} is not closed; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _string(value: Any, *, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        fail(f"{label} is not substantive")
    text = value.strip()
    if any(character in text for character in ("\x00", "\r")):
        fail(f"{label} contains a prohibited control character")
    return text


def _strings(
    value: Any,
    *,
    label: str,
    minimum_items: int = 1,
    minimum_characters: int = 12,
) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum_items:
        fail(f"{label} must contain at least {minimum_items} entries")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _string(
            item,
            label=f"{label} entry",
            minimum=minimum_characters,
        )
        if text in seen:
            fail(f"{label} contains a duplicate entry: {text}")
        seen.add(text)
        result.append(text)
    return result


def _repository_reference(root: Path, value: str) -> Path:
    raw = value.split("#", 1)[0]
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or "\\" in raw
        or not pure.parts
        or any(part in {"", ".", ".."} for part in raw.split("/"))
    ):
        fail(f"non-canonical source-preparation reference: {value}")
    path = root.joinpath(*pure.parts)
    if not path.exists():
        fail(f"source-preparation reference is missing: {value}")
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            fail(f"source-preparation reference is linked: {value}")
    if not path.is_file():
        fail(f"source-preparation reference must be a file: {value}")
    if not path.resolve().is_relative_to(root.resolve()):
        fail(f"source-preparation reference escapes the repository: {value}")
    return path


def _validate_schema(root: Path) -> None:
    schema = _strict_json(root / SCHEMA, maximum_bytes=MAX_SCHEMA_BYTES)
    required_top = {
        "$schema",
        "$id",
        "title",
        "type",
        "additionalProperties",
        "required",
        "properties",
        "$defs",
    }
    _exact_keys(schema, required_top, "external closure JSON Schema")
    if schema["$schema"] != "https://json-schema.org/draft/2020-12/schema":
        fail("external closure schema draft drifted")
    if schema["$id"] != (
        "https://trillionnium.org/schemas/external-closure-program.schema.json"
    ):
        fail("external closure schema identifier drifted")
    if schema["type"] != "object" or schema["additionalProperties"] is not False:
        fail("external closure schema must remain a closed object")
    if set(schema["required"]) != TOP_LEVEL_KEYS:
        fail("external closure schema required top-level fields drifted")
    properties = schema["properties"]
    if not isinstance(properties, dict) or set(properties) != TOP_LEVEL_KEYS:
        fail("external closure schema property inventory drifted")
    if properties["schema_version"] != {"const": 1}:
        fail("external closure schema version constraint drifted")
    if properties["program_id"] != {
        "const": "hepta-glasses-external-closure-v1"
    }:
        fail("external closure program identity constraint drifted")
    if properties["terminal_blocking_statuses"] != {
        "const": list(ALLOWED_STATUSES)
    }:
        fail("external closure terminal-status constraint drifted")
    gates = properties["gates"]
    if gates.get("minItems") != 13 or gates.get("maxItems") != 13:
        fail("external closure schema must require exactly thirteen gates")
    gate = schema["$defs"].get("gate")
    if not isinstance(gate, dict):
        fail("external closure schema lacks the gate definition")
    if gate.get("additionalProperties") is not False:
        fail("external closure gate schema must reject additional properties")
    if set(gate.get("required", ())) != GATE_KEYS:
        fail("external closure gate schema required fields drifted")
    status = gate.get("properties", {}).get("status", {})
    if tuple(status.get("enum", ())) != ALLOWED_STATUSES:
        fail("external closure gate status enum drifted")


def _validate_runbook(root: Path, gate_ids: Iterable[str]) -> None:
    path = root / RUNBOOK
    if path.is_symlink() or not path.is_file():
        fail("external closure orchestration runbook is missing or linked")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read external closure runbook: {error}")
    if len(text) < 8_000:
        fail("external closure runbook is not operationally substantive")
    for phrase in REQUIRED_RUNBOOK_PHRASES:
        if phrase not in text:
            fail(f"external closure runbook lacks required semantic: {phrase}")
    lowered = text.lower()
    for phrase in PROHIBITED_FALSE_CLOSURE_PHRASES:
        if phrase in lowered:
            fail(f"external closure runbook contains false-closure text: {phrase}")
    # The runbook groups gates by operation rather than repeating machine IDs, but
    # must name the canonical program and validator that carry those identities.
    for reference in (
        "docs/EXTERNAL_CLOSURE_PROGRAM.json",
        "tools/validate_external_closure_program.py",
        "tools/validate_external_evidence.py",
        "contracts/main-branch-protection-v1.json",
    ):
        if reference not in text:
            fail(f"external closure runbook omits required reference: {reference}")
    if len(tuple(gate_ids)) != 13:
        fail("external closure runbook validation received incomplete gate inventory")


def validate(
    root: Path = ROOT,
    *,
    program_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    _validate_schema(root)
    selected = program_path or root / PROGRAM
    program = _strict_json(selected, maximum_bytes=MAX_PROGRAM_BYTES)
    _exact_keys(program, TOP_LEVEL_KEYS, "external closure program")
    if program["schema_version"] != 1:
        fail("external closure program schema_version must be 1")
    if program["program_id"] != "hepta-glasses-external-closure-v1":
        fail("external closure program identity drifted")

    identity_rule = _string(
        program["candidate_identity_rule"],
        label="candidate identity rule",
        minimum=120,
    )
    for phrase in REQUIRED_IDENTITY_PHRASES:
        if phrase not in identity_rule:
            fail(f"candidate identity rule lacks required semantic: {phrase}")
    claim_ceiling = _string(
        program["claim_ceiling"],
        label="claim ceiling",
        minimum=160,
    )
    for phrase in REQUIRED_CLAIM_CEILING_PHRASES:
        if phrase not in claim_ceiling:
            fail(f"claim ceiling lacks required semantic: {phrase}")
    lowered_ceiling = claim_ceiling.lower()
    for phrase in PROHIBITED_FALSE_CLOSURE_PHRASES:
        if phrase in lowered_ceiling:
            fail(f"claim ceiling contains false-closure text: {phrase}")

    if tuple(program["terminal_blocking_statuses"]) != ALLOWED_STATUSES:
        fail("terminal blocking-status identity or order drifted")
    gates = program["gates"]
    if not isinstance(gates, list) or len(gates) != len(EXPECTED_GATES):
        fail("external closure program must contain exactly thirteen gates")

    seen_ids: set[str] = set()
    seen_gaps: set[str] = set()
    seen_issues: set[int] = set()
    seen_authorities: set[str] = set()
    status_counts = {status: 0 for status in ALLOWED_STATUSES}
    observed: list[tuple[str, tuple[str, ...], tuple[int, ...], str]] = []

    for position, raw in enumerate(gates):
        if not isinstance(raw, dict):
            fail(f"external closure gate {position} is not an object")
        _exact_keys(raw, GATE_KEYS, f"external closure gate {position}")
        identifier = _string(raw["id"], label=f"gate {position}.id")
        if not IDENTIFIER.fullmatch(identifier) or identifier in seen_ids:
            fail(f"duplicate or malformed gate id: {identifier}")
        seen_ids.add(identifier)

        gaps = raw["gap_ids"]
        if not isinstance(gaps, list) or not 1 <= len(gaps) <= 2:
            fail(f"{identifier}.gap_ids must contain one or two entries")
        gap_tuple: tuple[str, ...] = tuple(gaps)
        if len(set(gap_tuple)) != len(gap_tuple):
            fail(f"{identifier}.gap_ids contains a duplicate")
        for gap in gap_tuple:
            if not isinstance(gap, str) or not GAP_ID.fullmatch(gap):
                fail(f"{identifier} has malformed gap id: {gap!r}")
            if gap in seen_gaps:
                fail(f"gap id is assigned to multiple closure gates: {gap}")
            seen_gaps.add(gap)

        issues = raw["issue_numbers"]
        if not isinstance(issues, list) or not 1 <= len(issues) <= 2:
            fail(f"{identifier}.issue_numbers must contain one or two entries")
        issue_tuple: tuple[int, ...] = tuple(issues)
        if any(
            isinstance(issue, bool) or not isinstance(issue, int) or issue < 1
            for issue in issue_tuple
        ):
            fail(f"{identifier} has an invalid issue number")
        if len(set(issue_tuple)) != len(issue_tuple):
            fail(f"{identifier}.issue_numbers contains a duplicate")
        for issue in issue_tuple:
            if issue in seen_issues:
                fail(f"issue is assigned to multiple closure gates: #{issue}")
            seen_issues.add(issue)

        authority = _string(
            raw["authority_class"],
            label=f"{identifier}.authority_class",
            minimum=8,
        )
        if not AUTHORITY.fullmatch(authority) or authority in seen_authorities:
            fail(f"duplicate or malformed authority class: {authority}")
        seen_authorities.add(authority)
        status = raw["status"]
        if status not in ALLOWED_STATUSES:
            fail(f"{identifier} has unsupported or falsely promoted status: {status}")
        status_counts[status] += 1
        _string(raw["owner"], label=f"{identifier}.owner", minimum=16)

        preparations = _strings(
            raw["source_preparation"],
            label=f"{identifier}.source_preparation",
            minimum_items=3,
            minimum_characters=8,
        )
        for reference in preparations:
            _repository_reference(root, reference)
        evidence = _strings(
            raw["evidence_required"],
            label=f"{identifier}.evidence_required",
            minimum_items=3,
            minimum_characters=24,
        )
        acceptance = _strings(
            raw["acceptance"],
            label=f"{identifier}.acceptance",
            minimum_items=3,
            minimum_characters=24,
        )
        substitutes = _strings(
            raw["prohibited_substitutes"],
            label=f"{identifier}.prohibited_substitutes",
            minimum_items=4,
            minimum_characters=12,
        )
        reopening = _strings(
            raw["reopens_on"],
            label=f"{identifier}.reopens_on",
            minimum_items=1,
            minimum_characters=24,
        )
        combined = " ".join(
            [*evidence, *acceptance, *substitutes, *reopening]
        ).lower()
        if "evidence" not in combined and "receipt" not in combined:
            fail(f"{identifier} lacks an evidence or receipt boundary")
        if status == "BLOCKED_ADMIN_SETTING" and "api" not in combined:
            fail(f"{identifier} administrator gate lacks an API observation")
        if status == "BLOCKED_UPSTREAM" and "vendor" not in combined:
            fail(f"{identifier} upstream gate lacks vendor authority")

        observed.append((identifier, gap_tuple, issue_tuple, status))

    if tuple(observed) != EXPECTED_GATES:
        fail(
            "external closure gate identity, order, gap mapping, issue mapping, "
            "or status drifted"
        )
    if seen_issues != EXPECTED_ISSUES:
        fail(
            "external closure issue inventory drifted; "
            f"missing={sorted(EXPECTED_ISSUES - seen_issues)}, "
            f"extra={sorted(seen_issues - EXPECTED_ISSUES)}"
        )
    expected_counts = {
        "BLOCKED_ADMIN_SETTING": 1,
        "BLOCKED_EXTERNAL": 11,
        "BLOCKED_UPSTREAM": 1,
    }
    if status_counts != expected_counts:
        fail(f"external closure status distribution drifted: {status_counts}")

    _validate_runbook(root, seen_ids)
    return {
        "ok": True,
        "program_id": program["program_id"],
        "gates": len(gates),
        "issues": len(seen_issues),
        "gap_ids": len(seen_gaps),
        "status_counts": status_counts,
        "claim_ceiling": "source_preparation_only_no_external_gate_closed",
    }


def main() -> int:
    try:
        result = validate(ROOT)
    except (ExternalClosureProgramError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
