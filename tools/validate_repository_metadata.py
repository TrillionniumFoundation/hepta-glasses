#!/usr/bin/env python3
"""Fail-closed validation for gap evidence and module documentation metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_REVISION = "2026-09-01-g8"
ALLOWED_GAP_STATUSES = {
    "OPEN",
    "CLOSED_SOURCE",
    "CLOSED_VERIFIED",
    "BLOCKED_EXTERNAL",
    "BLOCKED_ADMIN_SETTING",
    "BLOCKED_UPSTREAM",
}
ALLOWED_MODULE_LIFECYCLES = {
    "source_candidate",
    "development_reference",
}
MODULE_MARKER_RE = re.compile(r"<!-- module:([a-z0-9]+(?:-[a-z0-9]+)*) -->")
MINIMUM_MODULE_SECTION_CHARACTERS = 700


class MetadataValidationError(AssertionError):
    """Stable repository metadata validation failure."""


def fail(message: str) -> None:
    raise MetadataValidationError(message)


def read_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001 - stable fail-closed boundary
        fail(f"invalid JSON document {relative}: {error}")
    if not isinstance(value, dict):
        fail(f"{relative} must contain an object")
    return value


def split_reference(reference: str) -> tuple[str, str | None]:
    if not isinstance(reference, str) or not reference.strip():
        fail(f"invalid empty repository reference: {reference!r}")
    normalized = reference.strip()
    if "\\" in normalized:
        fail(f"repository reference must use POSIX separators: {reference}")
    raw_path, separator, anchor = normalized.partition("#")
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"repository reference escapes or is malformed: {reference}")
    return raw_path, anchor if separator else None


def require_reference(
    reference: str,
    *,
    label: str,
    allow_directory: bool,
) -> Path:
    relative, _ = split_reference(reference)
    path = ROOT / relative
    if not path.exists():
        fail(f"{label} references missing path: {reference}")
    if not allow_directory and not path.is_file():
        fail(f"{label} must reference a file: {reference}")
    return path


def require_string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            fail(f"{label} contains an invalid value: {item!r}")
        result.append(item.strip())
    return result


def validate_gap_ledger() -> tuple[int, int, int]:
    ledger = read_json("docs/GAP_LEDGER.yaml")
    schema_version = ledger.get("schema_version")
    if not isinstance(schema_version, int) or schema_version < 6:
        fail("Gap Ledger schema_version must be at least 6")
    if ledger.get("plan_revision") != CANONICAL_REVISION:
        fail("Gap Ledger is not bound to the canonical revision")

    declared_statuses = set(
        require_string_list(
            ledger.get("allowed_statuses"),
            label="Gap Ledger allowed_statuses",
        )
    )
    if declared_statuses != ALLOWED_GAP_STATUSES:
        fail("Gap Ledger allowed_statuses drifted from validator semantics")

    gaps = ledger.get("gaps")
    if not isinstance(gaps, list) or len(gaps) < 65:
        fail("Gap Ledger does not contain the complete source/external gate set")

    seen: set[str] = set()
    open_source: list[str] = []
    blocked = 0
    closed = 0
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            fail(f"Gap Ledger entry {index} is not an object")
        gap_id = gap.get("id")
        if not isinstance(gap_id, str) or not re.fullmatch(r"HG-[0-9]{4}", gap_id):
            fail(f"invalid gap id: {gap_id!r}")
        if gap_id in seen:
            fail(f"duplicate gap id: {gap_id}")
        seen.add(gap_id)

        owner = gap.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            fail(f"{gap_id} has no owner")
        status = gap.get("status")
        if status not in ALLOWED_GAP_STATUSES:
            fail(f"{gap_id} has invalid status {status!r}")

        if status in {"CLOSED_SOURCE", "CLOSED_VERIFIED"}:
            closed += 1
            evidence = require_string_list(
                gap.get("evidence"),
                label=f"{gap_id}.evidence",
            )
            for reference in evidence:
                require_reference(
                    reference,
                    label=f"{gap_id}.evidence",
                    allow_directory=False,
                )
            closure_kind = gap.get("closure_kind", "IMPLEMENTED")
            if closure_kind not in {"IMPLEMENTED", "REMOVED_FROM_PRODUCT_BOUNDARY"}:
                fail(f"{gap_id} has invalid closure_kind {closure_kind!r}")
            if closure_kind == "REMOVED_FROM_PRODUCT_BOUNDARY" and (
                "docs/PRODUCT_BOUNDARY.md" not in evidence
                or "docs/MODULES.json" not in evidence
            ):
                fail(
                    f"{gap_id} removal closure must cite PRODUCT_BOUNDARY and MODULES"
                )
            if status == "CLOSED_VERIFIED":
                verification = require_string_list(
                    gap.get("verification"),
                    label=f"{gap_id}.verification",
                )
                for reference in verification:
                    require_reference(
                        reference,
                        label=f"{gap_id}.verification",
                        allow_directory=False,
                    )
            continue

        preparation = require_string_list(
            gap.get("source_preparation"),
            label=f"{gap_id}.source_preparation",
        )
        for reference in preparation:
            require_reference(
                reference,
                label=f"{gap_id}.source_preparation",
                allow_directory=False,
            )

        if status == "OPEN":
            close_criteria = gap.get("close_criteria")
            if not isinstance(close_criteria, str) or not close_criteria.strip():
                fail(f"{gap_id} is OPEN without explicit close_criteria")
            open_source.append(gap_id)
        else:
            blocked += 1
            evidence_required = require_string_list(
                gap.get("evidence_required"),
                label=f"{gap_id}.evidence_required",
            )
            if not evidence_required:
                fail(f"{gap_id} has no external evidence requirement")
            unblock_condition = gap.get("unblock_condition")
            if not isinstance(unblock_condition, str) or not unblock_condition.strip():
                fail(f"{gap_id} has no concrete unblock_condition")

    if open_source:
        fail(f"repository-actionable gaps remain OPEN: {open_source}")
    return len(gaps), closed, blocked


def guide_sections(guide: str) -> tuple[list[str], dict[str, str]]:
    matches = list(MODULE_MARKER_RE.finditer(guide))
    if not matches:
        fail("module development guide contains no module markers")
    ordered: list[str] = []
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        module_id = match.group(1)
        if module_id in sections:
            fail(f"duplicate module guide marker: {module_id}")
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(guide)
        body = guide[start:end].strip()
        if len(body) < MINIMUM_MODULE_SECTION_CHARACTERS:
            fail(
                f"module guide section {module_id} is too small "
                f"({len(body)} < {MINIMUM_MODULE_SECTION_CHARACTERS})"
            )
        ordered.append(module_id)
        sections[module_id] = body
    return ordered, sections


def validate_modules() -> int:
    registry = read_json("docs/MODULES.json")
    if registry.get("schema_version") != 1:
        fail("MODULES.json schema_version drifted")
    if registry.get("plan_revision") != CANONICAL_REVISION:
        fail("MODULES.json is not bound to the canonical revision")

    modules = registry.get("modules")
    if not isinstance(modules, list) or len(modules) < 20:
        fail("MODULES.json must declare every major repository module")

    guide_path = ROOT / "docs/MODULE_DEVELOPMENT_GUIDE.md"
    guide = guide_path.read_text(encoding="utf-8")
    marker_order, sections = guide_sections(guide)
    declared_ids: list[str] = []
    seen: set[str] = set()

    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            fail(f"MODULES.json entry {index} is not an object")
        module_id = module.get("id")
        if not isinstance(module_id, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", module_id
        ):
            fail(f"invalid module id: {module_id!r}")
        if module_id in seen:
            fail(f"duplicate module id: {module_id}")
        seen.add(module_id)
        declared_ids.append(module_id)

        owner = module.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            fail(f"module {module_id} has no owner")
        lifecycle = module.get("lifecycle")
        if lifecycle not in ALLOWED_MODULE_LIFECYCLES:
            fail(f"module {module_id} has invalid lifecycle {lifecycle!r}")

        source_roots = require_string_list(
            module.get("source_roots"),
            label=f"module {module_id}.source_roots",
        )
        documentation = require_string_list(
            module.get("documentation"),
            label=f"module {module_id}.documentation",
        )
        tests = require_string_list(
            module.get("tests"),
            label=f"module {module_id}.tests",
        )
        contracts = require_string_list(
            module.get("contracts"),
            label=f"module {module_id}.contracts",
        )
        require_string_list(
            module.get("external_gates"),
            label=f"module {module_id}.external_gates",
        )

        for reference in source_roots:
            require_reference(
                reference,
                label=f"module {module_id}.source_roots",
                allow_directory=True,
            )
        for reference in documentation:
            path = require_reference(
                reference,
                label=f"module {module_id}.documentation",
                allow_directory=False,
            )
            relative, anchor = split_reference(reference)
            if relative == "docs/MODULE_DEVELOPMENT_GUIDE.md":
                if anchor != module_id:
                    fail(
                        f"module {module_id} must cite its exact guide anchor, "
                        f"not {reference}"
                    )
                if module_id not in sections:
                    fail(f"module {module_id} has no detailed guide section")
            elif anchor is not None:
                text = path.read_text(encoding="utf-8")
                if anchor not in text:
                    fail(
                        f"module {module_id} documentation anchor is absent: {reference}"
                    )
        for reference in tests:
            require_reference(
                reference,
                label=f"module {module_id}.tests",
                allow_directory=False,
            )
        for reference in contracts:
            require_reference(
                reference,
                label=f"module {module_id}.contracts",
                allow_directory=False,
            )

    if declared_ids != marker_order:
        fail(
            "MODULES.json order/identity differs from MODULE_DEVELOPMENT_GUIDE markers: "
            f"declared={declared_ids}, guide={marker_order}"
        )

    docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    for required in ("MODULES.json", "MODULE_DEVELOPMENT_GUIDE.md"):
        if required not in docs_index:
            fail(f"docs/README.md does not index {required}")

    evidence_index = (ROOT / "docs/EVIDENCE_INDEX.yaml").read_text(encoding="utf-8")
    if "MODULES.json" not in evidence_index or "validate_repository_metadata.py" not in evidence_index:
        fail("Evidence Index does not register module/metadata validation evidence")
    return len(modules)


def main() -> int:
    try:
        gap_count, closed_count, blocked_count = validate_gap_ledger()
        module_count = validate_modules()
    except MetadataValidationError as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "plan_revision": CANONICAL_REVISION,
                "gaps": gap_count,
                "closed_source_or_verified": closed_count,
                "blocked_external_admin_or_upstream": blocked_count,
                "modules": module_count,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
