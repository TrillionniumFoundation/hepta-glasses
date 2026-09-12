#!/usr/bin/env python3
"""Deterministic coverage and semantic-mutation gates for critical Dart code."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "lib/runtime/packet_codec.dart"
TARGET_TEST = "test/runtime/packet_codec_test.dart"


class QualityGateError(RuntimeError):
    pass


def _reject_constant(value: str) -> None:
    raise QualityGateError(f"non-finite JSON value is forbidden: {value}")


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualityGateError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_closed_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityGateError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualityGateError(f"{path} must contain one JSON object")
    return value


def _repository_path(value: str) -> str:
    if not value or "\\" in value:
        raise QualityGateError(f"invalid source path: {value!r}")
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve(strict=False).relative_to(ROOT.resolve())
        except ValueError as exc:
            raise QualityGateError(f"coverage path escapes repository: {value}") from exc
    pure = PurePosixPath(candidate.as_posix())
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise QualityGateError(f"coverage path escapes repository: {value}")
    return pure.as_posix()


def parse_lcov(path: Path) -> dict[str, dict[int, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise QualityGateError(f"cannot read LCOV file {path}: {exc}") from exc

    records: dict[str, dict[int, int]] = {}
    current: str | None = None
    hits: dict[int, int] = {}
    for number, line in enumerate(lines, 1):
        if line.startswith("SF:"):
            if current is not None:
                raise QualityGateError(f"nested LCOV source record at line {number}")
            current = _repository_path(line[3:])
            if current in records:
                raise QualityGateError(f"duplicate LCOV source record: {current}")
            hits = {}
        elif line.startswith("DA:"):
            if current is None:
                raise QualityGateError(f"LCOV DA record outside source at line {number}")
            match = re.fullmatch(r"DA:([1-9][0-9]*),([0-9]+)(?:,[^,]+)?", line)
            if match is None:
                raise QualityGateError(f"invalid LCOV DA record at line {number}")
            source_line = int(match.group(1))
            if source_line in hits:
                raise QualityGateError(
                    f"duplicate LCOV line {source_line} for {current}"
                )
            hits[source_line] = int(match.group(2))
        elif line == "end_of_record":
            if current is None:
                raise QualityGateError(f"orphan LCOV terminator at line {number}")
            if not hits:
                raise QualityGateError(f"LCOV source has no instrumented lines: {current}")
            records[current] = hits
            current = None
            hits = {}
        elif line.startswith("TN:") or not line or re.fullmatch(
            r"(?:FN|FNDA|FNF|FNH|BRDA|BRF|BRH|LF|LH):.*", line
        ):
            continue
        else:
            raise QualityGateError(f"unsupported LCOV record at line {number}: {line}")
    if current is not None:
        raise QualityGateError(f"unterminated LCOV source record: {current}")
    if not records:
        raise QualityGateError("LCOV file contains no source records")
    return records


def load_coverage_contract(path: Path) -> list[dict[str, Any]]:
    contract = _load_json(path)
    expected = {"contract_id", "schema_version", "metric", "files"}
    if set(contract) != expected:
        raise QualityGateError(
            f"coverage contract fields differ: {sorted(set(contract) ^ expected)}"
        )
    if contract["contract_id"] != "hepta-critical-dart-line-coverage-v1":
        raise QualityGateError("unexpected coverage contract id")
    if contract["schema_version"] != 1:
        raise QualityGateError("coverage schema_version must be 1")
    if contract["metric"] != "instrumented_line_coverage_percent":
        raise QualityGateError("unsupported coverage metric")
    files = contract["files"]
    if not isinstance(files, list) or not files:
        raise QualityGateError("coverage files must be a non-empty array")

    normalized: list[dict[str, Any]] = []
    paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {
            "module_id",
            "path",
            "minimum_instrumented_lines",
            "minimum_percent",
        }:
            raise QualityGateError("coverage file entry uses an invalid shape")
        module_id = entry["module_id"]
        source_path = entry["path"]
        minimum_lines = entry["minimum_instrumented_lines"]
        minimum_percent = entry["minimum_percent"]
        if not isinstance(module_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,127}", module_id
        ):
            raise QualityGateError("coverage module_id is invalid")
        if not isinstance(source_path, str):
            raise QualityGateError("coverage path must be a string")
        source_path = _repository_path(source_path)
        if not source_path.startswith("lib/") or source_path in paths:
            raise QualityGateError(f"coverage path is invalid or duplicate: {source_path}")
        paths.add(source_path)
        if not (ROOT / source_path).is_file() or (ROOT / source_path).is_symlink():
            raise QualityGateError(f"coverage target is not a regular source file: {source_path}")
        if isinstance(minimum_lines, bool) or not isinstance(minimum_lines, int) or minimum_lines < 1:
            raise QualityGateError("minimum_instrumented_lines must be a positive integer")
        if isinstance(minimum_percent, bool) or not isinstance(
            minimum_percent, (int, float)
        ) or not math.isfinite(float(minimum_percent)) or not 0 <= float(minimum_percent) <= 100:
            raise QualityGateError("minimum_percent must be finite and between 0 and 100")
        normalized.append(
            {
                "module_id": module_id,
                "path": source_path,
                "minimum_instrumented_lines": minimum_lines,
                "minimum_percent": float(minimum_percent),
            }
        )
    return normalized


def evaluate_coverage(lcov_path: Path, contract_path: Path) -> dict[str, Any]:
    records = parse_lcov(lcov_path)
    requirements = load_coverage_contract(contract_path)
    results: list[dict[str, Any]] = []
    for requirement in requirements:
        source_path = requirement["path"]
        hits = records.get(source_path)
        if hits is None:
            raise QualityGateError(f"critical source is absent from LCOV: {source_path}")
        instrumented = len(hits)
        covered = sum(1 for count in hits.values() if count > 0)
        percent = 100.0 * covered / instrumented
        passed = (
            instrumented >= requirement["minimum_instrumented_lines"]
            and percent + 1e-9 >= requirement["minimum_percent"]
        )
        results.append(
            {
                **requirement,
                "instrumented_lines": instrumented,
                "covered_lines": covered,
                "percent": round(percent, 3),
                "passed": passed,
            }
        )
    if not all(result["passed"] for result in results):
        raise QualityGateError(
            "critical coverage threshold failed: "
            + json.dumps(results, sort_keys=True)
        )
    return {
        "schema_version": 1,
        "metric": "instrumented_line_coverage_percent",
        "files": results,
        "passed": True,
    }


MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "frame-count-upper-bound",
        "if (frameCount > 255) {",
        "if (frameCount > 256) {",
    ),
    (
        "expected-command-binding",
        "if (expectedCommand != null && command != expectedCommand) {",
        "if (false && expectedCommand != null && command != expectedCommand) {",
    ),
    (
        "metadata-frame-set-binding",
        "if (!_metadataMatches(frame, first, metadataLength)) {",
        "if (false && !_metadataMatches(frame, first, metadataLength)) {",
    ),
)


def run_mutations(flutter_command: str) -> dict[str, Any]:
    if not flutter_command or "\x00" in flutter_command:
        raise QualityGateError("flutter command is invalid")
    try:
        original = TARGET.read_bytes()
        source = original.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise QualityGateError(f"cannot read mutation target: {exc}") from exc
    original_digest = hashlib.sha256(original).hexdigest()

    baseline = subprocess.run(
        [flutter_command, "test", "--no-pub", TARGET_TEST],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        check=False,
        env={**os.environ, "CI": "true"},
    )
    if baseline.returncode != 0:
        raise QualityGateError("mutation baseline test failed before any source change")

    results: list[dict[str, Any]] = []
    try:
        for mutation_id, needle, replacement in MUTATIONS:
            if source.count(needle) != 1:
                raise QualityGateError(
                    f"mutation anchor {mutation_id} occurs {source.count(needle)} times"
                )
            if replacement in source:
                raise QualityGateError(f"mutation replacement already present: {mutation_id}")
            mutated = source.replace(needle, replacement, 1).encode("utf-8")
            TARGET.write_bytes(mutated)
            timed_out = False
            try:
                completed = subprocess.run(
                    [flutter_command, "test", "--no-pub", TARGET_TEST],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=300,
                    check=False,
                    env={**os.environ, "CI": "true"},
                )
                killed = completed.returncode != 0
                returncode: int | None = completed.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                killed = True
                returncode = None
            finally:
                TARGET.write_bytes(original)
            results.append(
                {
                    "id": mutation_id,
                    "killed": killed,
                    "timed_out": timed_out,
                    "returncode": returncode,
                }
            )
            if not killed:
                raise QualityGateError(f"semantic mutant survived: {mutation_id}")
    finally:
        TARGET.write_bytes(original)
    restored = TARGET.read_bytes()
    if restored != original or hashlib.sha256(restored).hexdigest() != original_digest:
        raise QualityGateError("mutation target was not restored byte-for-byte")
    return {
        "schema_version": 1,
        "target": TARGET.relative_to(ROOT).as_posix(),
        "test": TARGET_TEST,
        "baseline_passed": True,
        "mutants": results,
        "passed": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    coverage = subparsers.add_parser("coverage")
    coverage.add_argument("--lcov", required=True, type=Path)
    coverage.add_argument("--contract", required=True, type=Path)
    mutations = subparsers.add_parser("mutations")
    mutations.add_argument("--flutter-command", default="flutter")
    args = parser.parse_args(argv)

    try:
        if args.command == "coverage":
            result = evaluate_coverage(args.lcov, args.contract)
        else:
            result = run_mutations(args.flutter_command)
    except (QualityGateError, OSError, subprocess.SubprocessError) as exc:
        print(f"critical-quality-gate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
