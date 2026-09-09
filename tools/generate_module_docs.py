#!/usr/bin/env python3
"""Generate the canonical module registry and per-module engineering handoff views.

The bootstrap operation is intentionally one-way: it flattens the currently
active layered coverage registry once, merges the machine handoff status, writes
`docs/modules/modules.json`, and replaces `docs/MODULE_COVERAGE.json` with a
compatibility pointer. Subsequent runs read only the canonical registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_source_coverage import load_registry  # noqa: E402

CANONICAL = Path("docs/modules/modules.json")
COMPATIBILITY = Path("docs/MODULE_COVERAGE.json")
HANDOFF = Path("docs/MODULE_HANDOFF.json")
MODULE_INDEX = Path("docs/modules/README.md")
ROOT_README = Path("README.md")
DOCS_README = Path("docs/README.md")
ROOT_SECTION_START = "<!-- module-controls:index:start -->"
ROOT_SECTION_END = "<!-- module-controls:index:end -->"
DOCS_SECTION_START = "<!-- module-controls:docs-index:start -->"
DOCS_SECTION_END = "<!-- module-controls:docs-index:end -->"
MODULE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_MODULE_FIELDS = (
    "id",
    "owner",
    "lifecycle",
    "profile",
    "primary_document",
    "platform_status",
    "evidence_ceiling",
    "source_roots",
    "documentation",
    "tests",
    "contracts",
    "external_gates",
)

# Files introduced by the canonical-registry and external-closure layers must be
# owned by the same registry they validate. These additions are applied during
# the one-way bootstrap before the compatibility pointer replaces the old stack.
BOOTSTRAP_ADDITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "repository-governance": {
        "source_roots": (
            "tools/generate_module_docs.py",
            "tools/validate_module_semantics.py",
        ),
        "documentation": (
            "docs/modules/README.md",
            "docs/modules/modules.json",
        ),
        "tests": (
            "services/qualification/test_module_semantic_docs.py",
        ),
    },
    "qualification-release": {
        "source_roots": (
            "tools/validate_external_closure_program.py",
        ),
        "documentation": (
            "docs/EXTERNAL_CLOSURE_PROGRAM.json",
            "docs/operations/EXTERNAL_CLOSURE_ORCHESTRATION.md",
        ),
        "tests": (
            "services/qualification/test_external_closure_program.py",
        ),
        "contracts": (
            "schemas/external-closure-program.schema.json",
        ),
    },
}


class ModuleGenerationError(ValueError):
    """Stable failure for canonical module generation."""


def fail(message: str) -> None:
    raise ModuleGenerationError(message)


def _unique_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: fail(
                f"non-finite JSON number is prohibited: {value}"
            ),
        )
    except ModuleGenerationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain a JSON object")
    return value


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        fail(f"cannot canonically encode module record: {error}")


def module_digest(module: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(module)).hexdigest()


def dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            fail(f"invalid empty module reference: {value!r}")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _handoff_rows(root: Path) -> dict[str, dict[str, Any]]:
    value = load_json(root / HANDOFF)
    rows = value.get("modules")
    if not isinstance(rows, list) or not rows:
        fail("module handoff contains no rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            fail("module handoff contains an invalid row")
        identifier = row["id"]
        if identifier in result:
            fail(f"duplicate module handoff row: {identifier}")
        result[identifier] = row
    return result


def bootstrap_registry(root: Path = ROOT) -> dict[str, Any]:
    canonical_path = root / CANONICAL
    if canonical_path.exists():
        fail("canonical module registry already exists; bootstrap is one-way")
    flattened = load_registry(root, str(COMPATIBILITY))
    handoff = _handoff_rows(root)
    if list(flattened["modules"]) != list(handoff):
        fail("coverage and handoff module identity/order differ before bootstrap")

    records: list[dict[str, Any]] = []
    for identifier, source in flattened["modules"].items():
        if not MODULE_ID.fullmatch(identifier):
            fail(f"invalid module identifier: {identifier}")
        row = handoff[identifier]
        record: dict[str, Any] = {
            "id": identifier,
            "owner": source["owner"],
            "lifecycle": source["lifecycle"],
            "profile": row["profile"],
            "primary_document": row["primary_document"],
            "platform_status": row["platform_status"],
            "evidence_ceiling": row["evidence_ceiling"],
            "source_roots": dedupe(source["source_roots"]),
            "documentation": dedupe(source["documentation"]),
            "tests": dedupe(source["tests"]),
            "contracts": dedupe(source["contracts"]),
            "external_gates": dedupe(source["external_gates"]),
        }
        additions = BOOTSTRAP_ADDITIONS.get(identifier, {})
        for field, values in additions.items():
            record[field] = dedupe([*record[field], *values])
        records.append(record)

    return {
        "schema_version": 1,
        "registry_kind": "canonical-active-module-registry",
        "scope": (
            "Single active module truth for ownership, implementation references, "
            "engineering handoff, platform status, and evidence ceilings. Historical "
            "G8/G9/G10 registries are retained only as lineage records."
        ),
        "required_module_fields": list(REQUIRED_MODULE_FIELDS),
        "modules": records,
        "ownership_overrides": dict(flattened["overrides"]),
    }


def load_canonical(root: Path = ROOT) -> dict[str, Any]:
    value = load_json(root / CANONICAL)
    if value.get("schema_version") != 1:
        fail("canonical module registry schema_version must be 1")
    if value.get("registry_kind") != "canonical-active-module-registry":
        fail("canonical module registry kind drifted")
    if tuple(value.get("required_module_fields", ())) != REQUIRED_MODULE_FIELDS:
        fail("canonical required module fields drifted")
    modules = value.get("modules")
    if not isinstance(modules, list) or not modules:
        fail("canonical module registry contains no modules")
    return value


def compatibility_pointer() -> str:
    value = {
        "schema_version": 1,
        "extends_registry": str(CANONICAL),
        "scope": (
            "Compatibility entry point only. The single active registry is "
            "docs/modules/modules.json; historical layered registries are not active truth."
        ),
        "module_extensions": [],
    }
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def quote_list(values: Iterable[str]) -> str:
    return "\n".join(f"- `{value}`" for value in values)


def render_module(module: dict[str, Any]) -> str:
    digest = module_digest(module)
    external = "\n".join(f"- {value}" for value in module["external_gates"])
    return f"""# `{module['id']}` module engineering handoff

Canonical registry digest: `{digest}`

Owner: `{module['owner']}`

Lifecycle: `{module['lifecycle']}`

Profile: `{module['profile']}`

This generated handoff is a module-specific navigation and consistency surface. It does not replace the owner-authored primary document `{module['primary_document']}` or manufacture deployment, physical-device, provider, signing, assurance, pilot, store, or release evidence.

## 1. Purpose and authority boundary

The module identifier is `{module['id']}` and its accountable owner is `{module['owner']}`. Its current platform state is:

> {module['platform_status']}

Implementation authority is limited to the source roots listed below. Anything outside those roots requires an explicit registry change and owner review. External gates remain non-source authorities and are never inferred from a green repository test.

### Source roots

{quote_list(module['source_roots'])}

## 2. Public interfaces and contracts

The primary engineering description is `{module['primary_document']}`. The following contracts are the machine-readable interface and compatibility boundary for this module:

{quote_list(module['contracts'])}

The following documentation forms the reviewed human interface. A contract, schema, command, channel, API, storage layout, or externally visible behavior change must update every affected reference in the same candidate:

{quote_list(module['documentation'])}

## 3. State, concurrency, and cancellation

State ownership, concurrency, cancellation, generation fencing, idempotency, and late-result behavior are defined jointly by the primary document, the registered source roots, and the contracts above. A change is inadmissible when those surfaces disagree. Unknown state, stale generation, expired authority, ambiguous ownership, or cancellation races must fail closed rather than silently commit a side effect.

## 4. Failure, recovery, and idempotency

The module must preserve explicit pre-effect failure, indeterminate-after-possible-effect, authoritative readback, retry, replay, and recovery semantics documented by its contracts. Recovery must not widen authority, restore revoked state, reuse a conflicting idempotency key, or convert missing evidence into success. Cross-module recovery changes require review from every affected owner.

## 5. Configuration, compatibility, and migration

Configuration and migration are source objects. Dependency, toolchain, schema, provider, platform, package identity, storage, policy, or firmware movement requires compatibility analysis and fresh qualification for the affected evidence axes. No historical Artifact, approval, physical report, provider receipt, signature, or release decision automatically transfers to a successor.

## 6. Operations, tests, observability, and SLO

The registered executable verification surfaces are:

{quote_list(module['tests'])}

Tests prove only their declared environment and assertions. Operational acceptance additionally requires bounded logs, privacy-safe traces, stable error classes, relevant SLO measurements, rollback/recovery procedures, and exact candidate identity. Module owners must record negative-path evidence, not only successful examples.

## 7. Security, privacy, and evidence ceiling

The current evidence ceiling is:

> {module['evidence_ceiling']}

The unresolved external or authority-owned boundaries are:

{external}

Secrets, raw credentials, signing material, unrestricted mutation authority, and sensitive user content must not be introduced into source, prompts, ordinary logs, generated documentation, test fixtures that escape their boundary, or repository evidence packages.

## 8. Ownership and change protocol

A change touching a listed source root, contract, test, or primary document must update the canonical module record when ownership, interfaces, platform state, evidence ceiling, or external gates change. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`; obtain the applicable Code Owner review; run all seven canonical CI jobs on one unchanged head; and bind any promotion to fresh exact-head evidence. Administrator bypass, self-review, stale evidence reuse, or generated prose alone cannot approve the change.
"""


def render_index(modules: list[dict[str, Any]]) -> str:
    rows = [
        "| Module | Owner | Lifecycle | Primary engineering document |",
        "|---|---|---|---|",
    ]
    for module in modules:
        rows.append(
            "| "
            f"[`{module['id']}`](./{module['id']}/README.md) | "
            f"`{module['owner']}` | `{module['lifecycle']}` | "
            f"`{module['primary_document']}` |"
        )
    return """# Active module engineering handoff

`docs/modules/modules.json` is the single active module registry. `docs/MODULE_COVERAGE.json` is a compatibility pointer, while G8/G9/G10 and date-stamped registries are retained as historical lineage only.

Every generated module page binds its complete canonical record with a SHA-256 digest and enumerates source roots, contracts, documentation, tests, platform status, evidence ceiling, and external gates. The generated pages improve reviewability; they do not replace owner-authored design documents or external evidence.

""" + "\n".join(rows) + "\n\n## Verification\n\n```bash\npython3 tools/generate_module_docs.py --check\npython3 tools/validate_module_semantics.py\n```\n"


def root_control_section() -> str:
    return f"""{ROOT_SECTION_START}
## Active module and closure controls

- `docs/modules/modules.json` — single active module ownership and handoff registry.
- `docs/modules/README.md` — per-module engineering documentation index.
- `docs/EXTERNAL_CLOSURE_PROGRAM.json` — machine-readable Administration, provider, device, assurance, firmware, signing, pilot, and store closure program.
- `docs/development/RELEASE_VERSIONING.md` — source-version and promotion authority.
- `docs/development/SOURCE_ARTIFACT_ARCHIVAL.md` — durable exact-head source-evidence custody.

Generated module pages and closure records do not elevate source into deployed, physical, independently assured, signed, piloted, store-approved, or released status.
{ROOT_SECTION_END}
"""


def docs_control_section() -> str:
    return f"""{DOCS_SECTION_START}
## Active module and closure controls

1. `modules/modules.json` — single active module registry; older layered registries are historical lineage.
2. `modules/README.md` — 26 module-specific engineering handoff pages.
3. `EXTERNAL_CLOSURE_PROGRAM.json` — authority-owned gate inventory and exact evidence requirements.
4. `operations/EXTERNAL_CLOSURE_ORCHESTRATION.md` — operator workflow for authentic E5–E7 closure.
5. `development/RELEASE_VERSIONING.md` — repository version and promotion contract.
6. `development/SOURCE_ARTIFACT_ARCHIVAL.md` — externally signed Artifact archival and revalidation.

Run the generator and semantic validator before proposing a registry, module, contract, or closure-program change.
{DOCS_SECTION_END}
"""


def upsert_section(
    text: str,
    *,
    start: str,
    end: str,
    section: str,
    before_heading: str,
) -> str:
    if start in text or end in text:
        if text.count(start) != 1 or text.count(end) != 1:
            fail(f"generated section markers are malformed: {start}")
        first = text.index(start)
        last = text.index(end, first) + len(end)
        return text[:first] + section.rstrip() + text[last:]
    marker = f"\n{before_heading}\n"
    if marker not in text:
        fail(f"cannot place generated section before {before_heading}")
    return text.replace(marker, "\n" + section.rstrip() + "\n" + marker, 1)


def expected_outputs(
    registry: dict[str, Any],
    root: Path = ROOT,
) -> dict[Path, str]:
    modules = registry["modules"]
    outputs: dict[Path, str] = {
        COMPATIBILITY: compatibility_pointer(),
        MODULE_INDEX: render_index(modules),
    }
    for module in modules:
        outputs[Path(f"docs/modules/{module['id']}/README.md")] = render_module(
            module
        )

    root_readme = (root / ROOT_README).read_text(encoding="utf-8")
    outputs[ROOT_README] = upsert_section(
        root_readme,
        start=ROOT_SECTION_START,
        end=ROOT_SECTION_END,
        section=root_control_section(),
        before_heading="## Architecture boundary",
    )
    docs_readme = (root / DOCS_README).read_text(encoding="utf-8")
    outputs[DOCS_README] = upsert_section(
        docs_readme,
        start=DOCS_SECTION_START,
        end=DOCS_SECTION_END,
        section=docs_control_section(),
        before_heading="## Layered machine truth",
    )
    return outputs


def write_outputs(registry: dict[str, Any], root: Path = ROOT) -> None:
    for relative, content in expected_outputs(registry, root).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def check_outputs(registry: dict[str, Any], root: Path = ROOT) -> None:
    expected = expected_outputs(registry, root)
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            fail(f"generated module output is missing or linked: {relative}")
        if path.read_text(encoding="utf-8") != content:
            fail(f"generated module output drifted: {relative}")

    expected_pages = {
        Path(f"docs/modules/{module['id']}/README.md")
        for module in registry["modules"]
    }
    actual_pages = {
        path.relative_to(root)
        for path in (root / "docs/modules").glob("*/README.md")
        if path.parent.name != "modules"
    }
    if actual_pages != expected_pages:
        fail(
            "generated module page inventory drifted; "
            f"missing={sorted(map(str, expected_pages - actual_pages))}, "
            f"extra={sorted(map(str, actual_pages - expected_pages))}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--bootstrap", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.bootstrap:
            registry = bootstrap_registry(ROOT)
            path = ROOT / CANONICAL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            write_outputs(registry, ROOT)
        else:
            registry = load_canonical(ROOT)
            if args.write:
                write_outputs(registry, ROOT)
            else:
                check_outputs(registry, ROOT)
    except (ModuleGenerationError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "bootstrap" if args.bootstrap else "write" if args.write else "check",
                "modules": len(registry["modules"]),
                "registry": str(CANONICAL),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
