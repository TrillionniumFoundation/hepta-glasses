#!/usr/bin/env python3
"""Validate semantic handoff mapping against the flattened module registry."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .validate_source_coverage import load_registry
except ImportError:
    from validate_source_coverage import load_registry

ROOT = Path(__file__).resolve().parents[1]
MACHINE = "docs/MODULE_HANDOFF.json"
INDEX = "docs/development/MODULE_HANDOFF.md"
BASE_GUIDE = "docs/MODULE_DEVELOPMENT_GUIDE.md"
HANDOFF_MARKER = re.compile(r"<!-- handoff:([a-z0-9]+(?:-[a-z0-9]+)*) -->")
MODULE_MARKER = re.compile(r"<!-- module:([a-z0-9]+(?:-[a-z0-9]+)*) -->")
REQUIRED_DIMENSIONS = (
    "responsibility_and_api",
    "state_and_concurrency",
    "failure_and_recovery",
    "configuration_and_migration",
    "operations_and_verification",
    "platform_and_evidence",
)
MINIMUM_PRIMARY_DOCUMENT_CHARACTERS = 700
MINIMUM_STATUS_CHARACTERS = 24
PROHIBITED_PLACEHOLDERS = re.compile(
    r"\b(?:TBD|TODO|TO-DO|COMING SOON)\b",
    re.IGNORECASE,
)


class HandoffError(ValueError):
    pass


def fail(message: str) -> None:
    raise HandoffError(message)


def split_reference(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value.strip():
        fail("empty handoff reference")
    raw, separator, anchor = value.strip().partition("#")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or "\\" in raw
        or not pure.parts
        or any(part in {"", ".", ".."} for part in raw.split("/"))
    ):
        fail(f"non-canonical handoff reference: {value}")
    return raw, anchor if separator else None


def repository_path(reference: Any, *, file_only: bool) -> Path:
    raw, _ = split_reference(reference)
    path = ROOT.joinpath(*PurePosixPath(raw).parts)
    if not path.exists():
        fail(f"missing handoff reference: {reference}")
    current = ROOT
    for component in path.relative_to(ROOT).parts:
        current /= component
        if current.is_symlink():
            fail(f"linked handoff reference: {reference}")
    if file_only and not path.is_file():
        fail(f"handoff reference must be a file: {reference}")
    return path


def marked_sections(
    text: str,
    pattern: re.Pattern[str],
) -> tuple[list[str], dict[str, str]]:
    matches = list(pattern.finditer(text))
    if not matches:
        fail("handoff document contains no module markers")
    order: list[str] = []
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        identifier = match.group(1)
        if identifier in sections:
            fail(f"duplicate module marker: {identifier}")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        order.append(identifier)
        sections[identifier] = text[match.end():end].strip()
    return order, sections


def require_status(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value.strip()) < MINIMUM_STATUS_CHARACTERS:
        fail(f"{label} lacks substantive status")
    if PROHIBITED_PLACEHOLDERS.search(value):
        fail(f"{label} contains a placeholder")
    return value.strip()


def primary_text(
    reference: str,
    base_sections: dict[str, str],
    module_id: str,
) -> str:
    raw, anchor = split_reference(reference)
    path = repository_path(reference, file_only=True)
    if raw == BASE_GUIDE:
        if anchor != module_id or module_id not in base_sections:
            fail(f"{module_id} must cite its exact base-guide module section")
        text = base_sections[module_id]
    else:
        if anchor is not None:
            fail(f"{module_id} non-base primary document uses an unsupported anchor")
        text = path.read_text(encoding="utf-8")
    if len(text.strip()) < MINIMUM_PRIMARY_DOCUMENT_CHARACTERS:
        fail(f"{module_id} primary document is not substantive")
    if PROHIBITED_PLACEHOLDERS.search(text):
        fail(f"{module_id} primary document contains an unfinished placeholder")
    return text


def validate(root: Path = ROOT) -> dict[str, int]:
    global ROOT
    previous = ROOT
    ROOT = root
    try:
        registry = load_registry(root)
        machine = json.loads(
            repository_path(MACHINE, file_only=True).read_text(encoding="utf-8")
        )
        if not isinstance(machine, dict) or machine.get("schema_version") != 1:
            fail("module handoff schema_version must be 1")
        if machine.get("extends_registry") != "docs/MODULE_COVERAGE.json":
            fail("module handoff does not extend the flattened registry")
        if machine.get("dimension_profile") != "engineering-handoff-v1":
            fail("module handoff dimension profile drifted")
        if tuple(machine.get("required_dimensions", ())) != REQUIRED_DIMENSIONS:
            fail("module handoff required dimensions drifted")

        base_order, base_sections = marked_sections(
            repository_path(BASE_GUIDE, file_only=True).read_text(encoding="utf-8"),
            MODULE_MARKER,
        )
        if not base_order:
            fail("base module guide is empty")
        index_order, index_sections = marked_sections(
            repository_path(INDEX, file_only=True).read_text(encoding="utf-8"),
            HANDOFF_MARKER,
        )

        rows = machine.get("modules")
        if not isinstance(rows, list) or not rows:
            fail("module handoff contains no modules")
        registry_ids = list(registry["modules"])
        declared: list[str] = []
        seen: set[str] = set()
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                fail(f"handoff row {position} is not an object")
            module_id = row.get("id")
            if not isinstance(module_id, str) or module_id not in registry["modules"]:
                fail(f"unknown handoff module: {module_id!r}")
            if module_id in seen:
                fail(f"duplicate handoff module: {module_id}")
            seen.add(module_id)
            declared.append(module_id)
            registry_module = registry["modules"][module_id]
            if row.get("lifecycle") != registry_module.get("lifecycle"):
                fail(f"handoff lifecycle drifted for {module_id}")
            if row.get("index_anchor") != f"{INDEX}#{module_id}":
                fail(f"handoff index anchor drifted for {module_id}")

            primary = row.get("primary_document")
            if not isinstance(primary, str):
                fail(f"{module_id} has no primary document")
            primary_text(primary, base_sections, module_id)
            if row.get("profile") != machine["dimension_profile"]:
                fail(f"{module_id} handoff dimension profile drifted")
            require_status(
                row.get("platform_status"),
                label=f"{module_id}.platform_status",
            )
            require_status(
                row.get("evidence_ceiling"),
                label=f"{module_id}.evidence_ceiling",
            )
            index_section = index_sections.get(module_id, "")
            if primary not in index_section:
                fail(f"{module_id} index section does not name its primary document")
            if (
                "Platform status:" not in index_section
                or "Evidence ceiling:" not in index_section
            ):
                fail(f"{module_id} index section lacks status/ceiling")

            for field in ("source_roots", "documentation", "tests", "contracts"):
                values = registry_module.get(field)
                if not isinstance(values, list) or not values:
                    fail(f"{module_id}.{field} is missing from the registry")
                for reference in values:
                    repository_path(reference, file_only=field != "source_roots")
            gates = registry_module.get("external_gates")
            if not isinstance(gates, list) or not gates:
                fail(f"{module_id}.external_gates is missing from the registry")

        if declared != registry_ids:
            fail(
                "handoff identity/order differs from flattened registry: "
                f"handoff={declared}, registry={registry_ids}"
            )
        if index_order != declared:
            fail("handoff index marker order differs from machine handoff")
        root_index = repository_path("README.md", file_only=True).read_text(
            encoding="utf-8"
        )
        for required in (MACHINE, INDEX, "contracts/conformance/canonical-json-v1.json"):
            if required not in root_index:
                fail(f"root README does not index {required}")
        return {
            "modules": len(declared),
            "primary_documents": len({row["primary_document"] for row in rows}),
        }
    finally:
        ROOT = previous


def main() -> int:
    try:
        result = validate()
    except (HandoffError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
