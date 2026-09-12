#!/usr/bin/env python3
"""Reverse coverage of tracked code; not a claim of semantic test/doc completeness."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

SOURCE_ROOTS = frozenset({"lib", "android", "ios", "services", "adapters", "plugins",
    "tools", "contracts", "schemas", ".github", "third_party", "test"})


class CoverageError(ValueError):
    pass


def reference(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise CoverageError("empty reference")
    value = value.split("#", 1)[0]
    parts = PurePosixPath(value)
    if parts.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise CoverageError(f"non-canonical reference: {value}")
    path = root.joinpath(*parts.parts)
    if not path.exists() or any(item.is_symlink() for item in (path, *path.parents) if item != root.parent):
        raise CoverageError(f"missing or linked reference: {value}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise CoverageError(f"escaped reference: {value}")
    return path


def load_registry(root: Path, name: str = "docs/MODULE_COVERAGE.json", stack: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in stack:
        raise CoverageError("cyclic registry inheritance")
    value = json.loads(reference(root, name).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CoverageError("invalid registry schema")
    parent = value.get("extends_registry")
    loaded = load_registry(root, parent, (*stack, name)) if parent else {"modules": {}, "overrides": {}}
    for module in value.get("modules", []):
        module_id = module.get("id")
        if not isinstance(module_id, str) or not module_id or module_id in loaded["modules"]:
            raise CoverageError(f"duplicate or invalid module: {module_id}")
        if not isinstance(module.get("owner"), str) or not module["owner"].strip():
            raise CoverageError(f"missing owner: {module_id}")
        for field in ("source_roots", "documentation", "tests", "contracts", "external_gates"):
            items = module.get(field)
            if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items):
                raise CoverageError(f"invalid module field: {module_id}.{field}")
            if field != "external_gates":
                for item in items:
                    path = reference(root, item)
                    if field != "source_roots" and not path.is_file():
                        raise CoverageError(f"expected a file: {item}")
        loaded["modules"][module_id] = module
    for extension in value.get("module_extensions", []):
        module_id = extension.get("id")
        if module_id not in loaded["modules"]:
            raise CoverageError(f"extension of unknown module: {module_id}")
        if set(extension) - {"id", "source_roots", "documentation", "tests", "contracts"}:
            raise CoverageError("extension contains unsupported fields")
        module = loaded["modules"][module_id]
        for field, items in extension.items():
            if field == "id":
                continue
            if not isinstance(items, list) or not items:
                raise CoverageError("empty extension")
            for item in items:
                path = reference(root, item)
                if field != "source_roots" and not path.is_file():
                    raise CoverageError(f"expected a file: {item}")
            module[field] = list(dict.fromkeys([*module[field], *items]))
    for prefix, module_id in value.get("ownership_overrides", {}).items():
        reference(root, prefix)
        if module_id not in loaded["modules"]:
            raise CoverageError("ownership override names an unknown module")
        loaded["overrides"][prefix] = module_id
    return loaded


def matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def owners(path: str, registry: dict[str, Any]) -> list[str]:
    claims: list[tuple[int, str, str]] = []
    for module_id, module in registry["modules"].items():
        for prefix in module["source_roots"]:
            if matches(path, prefix):
                claims.append((len(prefix), module_id, "source"))
        for test in module["tests"]:
            if path == test:
                claims.append((len(test), module_id, "test"))
    if not claims:
        raise CoverageError(f"unowned tracked source: {path}")
    strongest = [claim for claim in claims if claim[0] == max(item[0] for item in claims)]
    source_claims = [claim for claim in strongest if claim[2] == "source"]
    candidates = sorted({claim[1] for claim in source_claims or strongest})
    overrides = [(len(prefix), owner) for prefix, owner in registry["overrides"].items() if matches(path, prefix)]
    if overrides:
        owner = max(overrides)[1]
        if owner not in candidates:
            raise CoverageError(f"invalid ownership override for {path}")
        return [owner]
    if len(candidates) > 1 and source_claims:
        raise CoverageError(f"ambiguous source ownership: {path}: {candidates}")
    return candidates  # Multiple equal-strength test references are explicitly shared.


def inspect_repository(root: Path) -> dict[str, Any]:
    registry = load_registry(root)
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    files = [value.decode("utf-8") for value in raw.split(b"\0") if value]
    inventory: dict[str, list[str]] = {}
    for path in files:
        if path.split("/", 1)[0] not in SOURCE_ROOTS:
            continue
        reference(root, path)
        inventory[path] = owners(path, registry)
    if not inventory:
        raise CoverageError("empty tracked source inventory")
    return {"schema_version": 1, "module_count": len(registry["modules"]),
        "tracked_source_count": len(inventory), "scope_roots": sorted(SOURCE_ROOTS),
        "ownership": inventory, "claim_ceiling": "path ownership and reference existence only; not semantic completeness, CI success or production readiness"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        report = inspect_repository(root)
    except (CoverageError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps({"ok": True, **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
