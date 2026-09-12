#!/usr/bin/env python3
"""Validate semantic consistency of the canonical per-module engineering handoff.

This validator is deliberately stronger than path-existence and minimum-length
checks. It binds every generated page to the complete canonical module record,
binds eleven canonical semantic dimensions to eight compact generated
handoff sections, verifies every source/document/test/contract reference, and
rejects compatibility-layer drift. It still does not
replace human module-owner or independent assurance review.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_module_docs import (  # noqa: E402
    CANONICAL,
    COMPATIBILITY,
    MODULE_INDEX,
    REQUIRED_MODULE_FIELDS,
    check_outputs,
    load_canonical,
    module_digest,
)

from services.qualification.module_document_links import (  # noqa: E402
    ModuleLinkError,
    validate_primary_fragment,
)

MODULE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER = re.compile(r"\b(?:TBD|TODO|TO-DO|COMING SOON|PLACEHOLDER)\b", re.I)
REQUIRED_HEADINGS = (
    "## 1. Purpose and authority boundary",
    "## 2. Public interfaces and contracts",
    "## 3. State, concurrency, and cancellation",
    "## 4. Failure, recovery, and idempotency",
    "## 5. Configuration, compatibility, and migration",
    "## 6. Operations, tests, observability, and SLO",
    "## 7. Security, privacy, and evidence ceiling",
    "## 8. Ownership and change protocol",
)
CANONICAL_SEMANTIC_HEADINGS = (
    "### 1.1 Purpose, responsibility and non-goals",
    "### 1.2 Component and source map",
    "### 1.3 Public interfaces and contracts",
    "### 1.4 State machine and invariants",
    "### 1.5 Concurrency and atomicity",
    "### 1.6 Failure, retry, reconciliation and recovery",
    "### 1.7 Configuration, compatibility, migration and rollback",
    "### 1.8 Operations, observability and SLOs",
    "### 1.9 Security, privacy and abuse cases",
    "### 1.10 Verification and acceptance",
    "### 1.11 Ownership and change protocol",
)
STANDARD = Path("docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md")
MINIMUM_PAGE_CHARACTERS = 2_000


class ModuleSemanticError(ValueError):
    """Stable module semantic-validation failure."""


def fail(message: str) -> None:
    raise ModuleSemanticError(message)


def _strict_json(path: Path) -> dict[str, Any]:
    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda value: fail(
                f"non-finite JSON number in {path}: {value}"
            ),
        )
    except ModuleSemanticError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def _reference(root: Path, value: Any, *, allow_directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        fail(f"invalid empty repository reference: {value!r}")
    raw = value.split("#", 1)[0]
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or "\\" in raw
        or not pure.parts
        or any(part in {"", ".", ".."} for part in raw.split("/"))
    ):
        fail(f"non-canonical repository reference: {value}")
    path = root.joinpath(*pure.parts)
    if not path.exists():
        fail(f"missing repository reference: {value}")
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            fail(f"linked repository reference: {value}")
    if not allow_directory and not path.is_file():
        fail(f"reference must be a regular file: {value}")
    if not path.resolve().is_relative_to(root.resolve()):
        fail(f"repository reference escapes root: {value}")
    return path


def _string(value: Any, *, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        fail(f"{label} is not substantive")
    if PLACEHOLDER.search(value):
        fail(f"{label} contains an unfinished placeholder")
    return value.strip()


def _string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _string(item, label=label)
        if text in seen:
            fail(f"{label} contains a duplicate reference: {text}")
        seen.add(text)
        result.append(text)
    return result


def _validate_compatibility_pointer(root: Path) -> None:
    pointer = _strict_json(root / COMPATIBILITY)
    expected = {
        "schema_version",
        "extends_registry",
        "scope",
        "module_extensions",
    }
    if set(pointer) != expected:
        fail("MODULE_COVERAGE compatibility pointer has additional active truth")
    if pointer["schema_version"] != 1:
        fail("MODULE_COVERAGE compatibility schema drifted")
    if pointer["extends_registry"] != str(CANONICAL):
        fail("MODULE_COVERAGE does not point to the canonical module registry")
    if pointer["module_extensions"] != []:
        fail("active module extensions must live in the canonical registry")
    _string(pointer["scope"], label="MODULE_COVERAGE scope", minimum=40)


def _validate_record(root: Path, module: dict[str, Any], seen: set[str]) -> None:
    missing = set(REQUIRED_MODULE_FIELDS) - set(module)
    if missing:
        fail(f"module record lacks required fields: {sorted(missing)}")
    identifier = _string(module["id"], label="module id")
    if not MODULE_ID.fullmatch(identifier) or identifier in seen:
        fail(f"duplicate or malformed module id: {identifier}")
    seen.add(identifier)
    _string(module["owner"], label=f"{identifier}.owner")
    if module["lifecycle"] not in {"source_candidate", "development_reference"}:
        fail(f"{identifier}.lifecycle is invalid")
    if module["profile"] != "engineering-handoff-v1":
        fail(f"{identifier}.profile drifted")
    _string(
        module["platform_status"],
        label=f"{identifier}.platform_status",
        minimum=24,
    )
    _string(
        module["evidence_ceiling"],
        label=f"{identifier}.evidence_ceiling",
        minimum=24,
    )

    references: dict[str, list[str]] = {}
    for field in ("source_roots", "documentation", "tests", "contracts"):
        references[field] = _string_list(module[field], label=f"{identifier}.{field}")
        for reference in references[field]:
            _reference(root, reference, allow_directory=field == "source_roots")
    _string_list(module["external_gates"], label=f"{identifier}.external_gates")
    primary = _string(
        module["primary_document"],
        label=f"{identifier}.primary_document",
    )
    primary_path = _reference(root, primary, allow_directory=False)
    try:
        validate_primary_fragment(primary_path, primary)
    except ModuleLinkError as error:
        fail(f"{identifier} primary document: {error}")
    if primary not in references["documentation"]:
        fail(f"{identifier} primary document is absent from documentation inventory")

    page = root / f"docs/modules/{identifier}/README.md"
    if page.is_symlink() or not page.is_file():
        fail(f"{identifier} generated handoff page is missing or linked")
    text = page.read_text(encoding="utf-8")
    if len(text) < MINIMUM_PAGE_CHARACTERS:
        fail(f"{identifier} generated handoff page is too small")
    if PLACEHOLDER.search(text):
        fail(f"{identifier} generated handoff page contains a placeholder")
    if text.count(f"Canonical registry digest: `{module_digest(module)}`") != 1:
        fail(f"{identifier} generated page is not bound to its complete record")
    positions = [text.find(heading) for heading in REQUIRED_HEADINGS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        fail(f"{identifier} generated page lacks ordered engineering dimensions")
    for field in ("source_roots", "documentation", "tests", "contracts"):
        for reference in references[field]:
            if text.count(f"`{reference}`") < 1:
                fail(f"{identifier} generated page omits {field} reference {reference}")
    for value in module["external_gates"]:
        if value not in text:
            fail(f"{identifier} generated page omits external gate {value}")
    for value in (
        module["owner"],
        module["lifecycle"],
        module["profile"],
        module["platform_status"],
        module["evidence_ceiling"],
    ):
        if str(value) not in text:
            fail(f"{identifier} generated page omits canonical status value")


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    standard_path = root / STANDARD
    if standard_path.is_symlink() or not standard_path.is_file():
        fail("module documentation completeness standard is missing or linked")
    standard_text = standard_path.read_text(encoding="utf-8")
    semantic_positions = [
        standard_text.find(heading) for heading in CANONICAL_SEMANTIC_HEADINGS
    ]
    if any(position < 0 for position in semantic_positions) or semantic_positions != sorted(semantic_positions):
        fail("canonical eleven module semantic dimensions drifted")
    registry = load_canonical(root)
    allowed_top = {
        "schema_version",
        "registry_kind",
        "scope",
        "required_module_fields",
        "modules",
        "ownership_overrides",
    }
    if set(registry) != allowed_top:
        fail("canonical module registry top-level shape is not closed")
    if "extends_registry" in registry:
        fail("canonical module registry must not inherit another active registry")
    _string(registry["scope"], label="canonical registry scope", minimum=80)
    if not isinstance(registry["ownership_overrides"], dict):
        fail("canonical ownership_overrides must be an object")
    modules = registry["modules"]
    if len(modules) != 26:
        fail(f"canonical module count drifted: {len(modules)} != 26")
    seen: set[str] = set()
    for module in modules:
        if not isinstance(module, dict):
            fail("canonical module entry is not an object")
        _validate_record(root, module, seen)

    check_outputs(registry, root)
    _validate_compatibility_pointer(root)
    index = root / MODULE_INDEX
    if index.is_symlink() or not index.is_file():
        fail("module documentation index is missing or linked")
    index_text = index.read_text(encoding="utf-8")
    for identifier in seen:
        if f"./{identifier}/README.md" not in index_text:
            fail(f"module index omits {identifier}")
    registry_digest = __import__("hashlib").sha256(
        json.dumps(
            registry,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "ok": True,
        "modules": len(modules),
        "registry_digest": registry_digest,
        "compatibility_pointer": str(COMPATIBILITY),
        "semantic_dimensions": len(CANONICAL_SEMANTIC_HEADINGS),
        "generated_handoff_sections": len(REQUIRED_HEADINGS),
    }


def main() -> int:
    try:
        result = validate(ROOT)
    except (ModuleSemanticError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())