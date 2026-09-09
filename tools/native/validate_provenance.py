#!/usr/bin/env python3
"""Validate exact Git-object custody for vendored native audio source.

The manifest binds imported subtrees/blobs that are present in this repository.
The external EvenDemoApp commit/root-tree observation is recorded separately and
must be revalidated through an authorized live source; it is not fabricated as a
locally available Git commit object.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("third_party/native-import-provenance.json")
INVENTORY = Path("third_party/native-components.json")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_TREE_UNITS = {
    "android-native-headers",
    "android-liblc3-source",
    "android-rnnoise-source",
    "ios-liblc3-source",
}
EXPECTED_INTEGRATION_PATHS = {
    "android/app/src/main/cpp/CMakeLists.txt",
    "android/app/src/main/cpp/liblc3.cpp",
    "ios/Runner/PcmConverter.h",
    "ios/Runner/PcmConverter.m",
    "ios/Runner/Runner-Bridging-Header.h",
}
EXPECTED_COMPONENTS = {"google-liblc3", "xiph-rnnoise"}


class NativeProvenanceError(ValueError):
    """Stable native provenance validation failure."""


def fail(message: str) -> None:
    raise NativeProvenanceError(message)


def strict_json(path: Path) -> dict[str, Any]:
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
    except NativeProvenanceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot parse {path}: {error}")
    if not isinstance(value, dict):
        fail(f"{path} must contain an object")
    return value


def closed_shape(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        fail(f"{label} shape mismatch: missing={missing!r}, extra={extra!r}")


def require_string(value: Any, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        fail(f"{label} must be a substantive string")
    return value.strip()


def require_hex40(value: Any, label: str) -> str:
    text = require_string(value, label)
    if not HEX40.fullmatch(text):
        fail(f"{label} must be a lowercase 40-hex Git object ID")
    return text


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        fail(f"{label} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        text = require_string(item, f"{label}[{index}]")
        if text in result:
            fail(f"{label} contains duplicate {text!r}")
        result.append(text)
    return result


def repository_path(root: Path, value: Any, label: str, *, directory: bool) -> Path:
    text = require_string(value, label)
    pure = PurePosixPath(text)
    if (
        pure.is_absolute()
        or "\\" in text
        or not pure.parts
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        fail(f"{label} is not a canonical repository path: {text}")
    path = root.joinpath(*pure.parts)
    if not path.exists() or (directory and not path.is_dir()) or (
        not directory and not path.is_file()
    ):
        fail(f"{label} does not identify the required repository object: {text}")
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            fail(f"{label} crosses a symbolic link: {text}")
    return path


def git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if process.returncode != 0:
        fail(
            f"git {' '.join(arguments)} failed with return code "
            f"{process.returncode}"
        )
    return process.stdout.strip()


def object_type(root: Path, object_id: str) -> str:
    return git(root, "cat-file", "-t", object_id)


def head_object(root: Path, path: str) -> str:
    return git(root, "rev-parse", f"HEAD:{path}")


def exact_tree_deltas(
    root: Path,
    imported_object: str,
    current_object: str,
) -> list[dict[str, str]]:
    output = git(
        root,
        "diff-tree",
        "--no-commit-id",
        "--no-renames",
        "--raw",
        "-r",
        "--abbrev=40",
        imported_object,
        current_object,
    )
    if not output:
        return []
    result: list[dict[str, str]] = []
    for line in output.splitlines():
        if "\t" not in line:
            fail("unexpected git diff-tree raw record")
        metadata, relative = line.split("\t", 1)
        fields = metadata.split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            fail("unexpected git diff-tree raw metadata")
        status = fields[4]
        if status not in {"A", "D", "M", "T"}:
            fail(f"unsupported native source delta status: {status}")
        result.append(
            {
                "path": relative,
                "status": status,
                "old_mode": fields[0][1:],
                "new_mode": fields[1],
                "imported_blob": fields[2],
                "current_blob": fields[3],
            }
        )
    return sorted(result, key=lambda item: item["path"])


def validate_inventory(root: Path, snapshot: Mapping[str, Any]) -> None:
    inventory = strict_json(root / INVENTORY)
    closed_shape(inventory, {"schema_version", "components"}, str(INVENTORY))
    if inventory["schema_version"] != 1:
        fail("unsupported native component inventory schema")
    components = inventory["components"]
    if not isinstance(components, list):
        fail("native component inventory components must be a list")
    observed: set[str] = set()
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            fail(f"native component {index} must be an object")
        required = {
            "id",
            "name",
            "version",
            "supplier",
            "license",
            "purl",
            "upstream_url",
            "revision",
            "source_paths",
            "import_snapshot",
            "provenance_manifest",
            "provenance_note",
        }
        closed_shape(component, required, f"native component {index}")
        identifier = require_string(component["id"], f"component[{index}].id")
        if identifier in observed:
            fail(f"duplicate native component id: {identifier}")
        observed.add(identifier)
        if component["version"] != "NOASSERTION" or component["revision"] != "NOASSERTION":
            fail(f"{identifier} must not invent an unavailable direct-upstream revision")
        if component["provenance_manifest"] != str(MANIFEST):
            fail(f"{identifier} does not bind the native provenance manifest")
        imported = component["import_snapshot"]
        if not isinstance(imported, dict):
            fail(f"{identifier}.import_snapshot must be an object")
        closed_shape(
            imported,
            {"repository", "commit", "tree"},
            f"{identifier}.import_snapshot",
        )
        for field in ("repository", "commit", "tree"):
            if imported[field] != snapshot[field]:
                fail(f"{identifier}.import_snapshot.{field} drifted")
        require_string_list(component["source_paths"], f"{identifier}.source_paths")
        require_string(component["provenance_note"], f"{identifier}.provenance_note", 80)
    if observed != EXPECTED_COMPONENTS:
        fail(f"native component inventory drifted: {sorted(observed)!r}")


def validate_document(root: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    closed_shape(
        document,
        {
            "schema_version",
            "manifest_kind",
            "repository",
            "import_snapshot",
            "direct_upstream_components",
            "tree_units",
            "integration_files",
            "claim_ceiling",
        },
        str(MANIFEST),
    )
    if document["schema_version"] != 1:
        fail("unsupported native provenance schema")
    if document["manifest_kind"] != "native-import-provenance":
        fail("native provenance manifest kind drifted")
    if document["repository"] != "TrillionniumFoundation/hepta-glasses":
        fail("native provenance repository identity drifted")
    require_string(document["claim_ceiling"], "claim_ceiling", 160)

    snapshot = document["import_snapshot"]
    if not isinstance(snapshot, dict):
        fail("import_snapshot must be an object")
    closed_shape(
        snapshot,
        {
            "repository",
            "commit",
            "tree",
            "committed_at",
            "commit_signature_verified",
            "observation_source",
            "commit_object_present_in_repository",
            "root_tree_object_present_in_repository",
            "external_observation_requires_live_revalidation",
            "source_record",
        },
        "import_snapshot",
    )
    if snapshot["repository"] != "even-realities/EvenDemoApp":
        fail("unexpected native import repository")
    require_hex40(snapshot["commit"], "import_snapshot.commit")
    require_hex40(snapshot["tree"], "import_snapshot.tree")
    if snapshot["committed_at"] != "2026-06-09T08:27:17Z":
        fail("native import snapshot timestamp drifted")
    if snapshot["commit_signature_verified"] is not False:
        fail("unsigned external import snapshot must remain truthfully unverified")
    if snapshot["observation_source"] != "GitHub Git Data API":
        fail("native external observation source drifted")
    if snapshot["commit_object_present_in_repository"] is not False:
        fail("external import commit must not be represented as a local object")
    if snapshot["root_tree_object_present_in_repository"] is not False:
        fail("external import root tree must not be represented as a local object")
    if snapshot["external_observation_requires_live_revalidation"] is not True:
        fail("external import observation must require live revalidation")
    source_record = repository_path(
        root,
        snapshot["source_record"],
        "import_snapshot.source_record",
        directory=False,
    )
    source_text = source_record.read_text(encoding="utf-8")
    for expected in (
        snapshot["repository"],
        snapshot["commit"],
        snapshot["tree"],
    ):
        if source_text.count(expected) != 1:
            fail(f"source record does not uniquely bind external observation {expected}")

    upstream = document["direct_upstream_components"]
    if not isinstance(upstream, list):
        fail("direct_upstream_components must be a list")
    upstream_ids: set[str] = set()
    for index, component in enumerate(upstream):
        if not isinstance(component, dict):
            fail(f"direct upstream component {index} must be an object")
        closed_shape(
            component,
            {
                "id",
                "repository",
                "version",
                "revision",
                "revision_status",
                "recovery_rule",
            },
            f"direct_upstream_components[{index}]",
        )
        identifier = require_string(component["id"], f"upstream[{index}].id")
        if identifier in upstream_ids:
            fail(f"duplicate direct upstream component: {identifier}")
        upstream_ids.add(identifier)
        if component["version"] != "NOASSERTION" or component["revision"] != "NOASSERTION":
            fail(f"{identifier} invents an unavailable direct-upstream revision")
        if component["revision_status"] != "not_preserved_in_import_snapshot":
            fail(f"{identifier} revision status drifted")
        require_string(component["repository"], f"{identifier}.repository")
        require_string(component["recovery_rule"], f"{identifier}.recovery_rule", 100)
    if upstream_ids != EXPECTED_COMPONENTS:
        fail(f"direct upstream component set drifted: {sorted(upstream_ids)!r}")

    units = document["tree_units"]
    if not isinstance(units, list):
        fail("tree_units must be a list")
    unit_ids: set[str] = set()
    tree_delta_count = 0
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            fail(f"tree unit {index} must be an object")
        closed_shape(
            unit,
            {
                "id",
                "component_ids",
                "path",
                "kind",
                "imported_object",
                "current_object",
                "status",
                "deltas",
            },
            f"tree_units[{index}]",
        )
        identifier = require_string(unit["id"], f"tree_units[{index}].id")
        if identifier in unit_ids:
            fail(f"duplicate native tree unit: {identifier}")
        unit_ids.add(identifier)
        component_ids = require_string_list(
            unit["component_ids"], f"{identifier}.component_ids"
        )
        if not set(component_ids).issubset(EXPECTED_COMPONENTS):
            fail(f"{identifier} references an unknown component")
        path = require_string(unit["path"], f"{identifier}.path")
        repository_path(root, path, f"{identifier}.path", directory=True)
        if unit["kind"] != "tree":
            fail(f"{identifier}.kind must be tree")
        imported_object = require_hex40(
            unit["imported_object"], f"{identifier}.imported_object"
        )
        current_object = require_hex40(
            unit["current_object"], f"{identifier}.current_object"
        )
        if object_type(root, imported_object) != "tree" or object_type(root, current_object) != "tree":
            fail(f"{identifier} must bind locally available tree objects")
        if head_object(root, path) != current_object:
            fail(f"{identifier} current tree does not match HEAD:{path}")
        observed = exact_tree_deltas(root, imported_object, current_object)
        declared = unit["deltas"]
        if not isinstance(declared, list):
            fail(f"{identifier}.deltas must be a list")
        normalized: list[dict[str, str]] = []
        for delta_index, delta in enumerate(declared):
            if not isinstance(delta, dict):
                fail(f"{identifier}.deltas[{delta_index}] must be an object")
            closed_shape(
                delta,
                {
                    "path",
                    "status",
                    "old_mode",
                    "new_mode",
                    "imported_blob",
                    "current_blob",
                },
                f"{identifier}.deltas[{delta_index}]",
            )
            normalized.append(
                {
                    "path": require_string(
                        delta["path"], f"{identifier}.deltas[{delta_index}].path"
                    ),
                    "status": require_string(
                        delta["status"], f"{identifier}.deltas[{delta_index}].status"
                    ),
                    "old_mode": require_string(
                        delta["old_mode"], f"{identifier}.deltas[{delta_index}].old_mode"
                    ),
                    "new_mode": require_string(
                        delta["new_mode"], f"{identifier}.deltas[{delta_index}].new_mode"
                    ),
                    "imported_blob": require_hex40(
                        delta["imported_blob"],
                        f"{identifier}.deltas[{delta_index}].imported_blob",
                    ),
                    "current_blob": require_hex40(
                        delta["current_blob"],
                        f"{identifier}.deltas[{delta_index}].current_blob",
                    ),
                }
            )
        normalized.sort(key=lambda item: item["path"])
        if normalized != observed:
            fail(f"{identifier} declared delta inventory does not match Git objects")
        expected_status = (
            "unchanged_from_import_snapshot" if not observed else "local_delta"
        )
        if unit["status"] != expected_status:
            fail(f"{identifier} status does not match its exact tree delta")
        tree_delta_count += len(observed)
    if unit_ids != EXPECTED_TREE_UNITS:
        fail(f"native tree unit set drifted: {sorted(unit_ids)!r}")

    files = document["integration_files"]
    if not isinstance(files, list):
        fail("integration_files must be a list")
    observed_paths: set[str] = set()
    changed_integration_count = 0
    for index, record in enumerate(files):
        if not isinstance(record, dict):
            fail(f"integration file {index} must be an object")
        closed_shape(
            record,
            {
                "path",
                "component_ids",
                "imported_blob",
                "current_blob",
                "status",
            },
            f"integration_files[{index}]",
        )
        path = require_string(record["path"], f"integration_files[{index}].path")
        if path in observed_paths:
            fail(f"duplicate native integration file: {path}")
        observed_paths.add(path)
        repository_path(root, path, f"integration_files[{index}].path", directory=False)
        component_ids = require_string_list(
            record["component_ids"], f"integration_files[{index}].component_ids"
        )
        if not set(component_ids).issubset(EXPECTED_COMPONENTS):
            fail(f"{path} references an unknown component")
        imported_blob = require_hex40(
            record["imported_blob"], f"integration_files[{index}].imported_blob"
        )
        current_blob = require_hex40(
            record["current_blob"], f"integration_files[{index}].current_blob"
        )
        if object_type(root, imported_blob) != "blob" or object_type(root, current_blob) != "blob":
            fail(f"{path} must bind locally available blob objects")
        if head_object(root, path) != current_blob:
            fail(f"integration file current blob does not match HEAD:{path}")
        changed = imported_blob != current_blob
        expected_status = (
            "local_integration_delta" if changed else "unchanged_from_import_snapshot"
        )
        if record["status"] != expected_status:
            fail(f"{path} status does not match its exact blob identity")
        changed_integration_count += int(changed)
    if observed_paths != EXPECTED_INTEGRATION_PATHS:
        fail(f"native integration file set drifted: {sorted(observed_paths)!r}")

    validate_inventory(root, snapshot)
    return {
        "ok": True,
        "external_import_commit": snapshot["commit"],
        "external_import_tree": snapshot["tree"],
        "external_observation_requires_live_revalidation": True,
        "tree_units": len(units),
        "tree_deltas": tree_delta_count,
        "integration_files": len(files),
        "integration_deltas": changed_integration_count,
        "direct_upstream_revision_known": False,
    }


def validate(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    document = strict_json(root / MANIFEST)
    return validate_document(root, document)


def main() -> int:
    try:
        result = validate(ROOT)
    except (NativeProvenanceError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
