#!/usr/bin/env python3
"""Fail-closed project-truth and qualified-baseline verification.

Local validation treats the previously reviewed qualification tuple as immutable
code constants rather than trusting repository-authored status values.  The
``--verify-github`` mode performs bounded, read-only, stable double reads of the
exact GitHub commit, pull request, workflow run, seven jobs, Artifact and review.
It downloads the Artifact twice, verifies the pinned ZIP digest and validates its
safe seven-member inventory and internal commit/tree/source-gate/SBOM bindings.

No mode can manufacture Repository Administration or E5-E7 evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PLAN_REVISION = "2026-09-01-g8"
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-glasses"
EXPECTED_REQUIRED_JOBS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
)
EXPECTED_HG0087_SLICES = {
    "identity",
    "model",
    "realtime",
    "capabilities",
    "speech",
    "skills",
    "memory",
}
EXPECTED_MATURITY_STAGES = (
    "design_draft",
    "source_implemented",
    "ci_qualified",
    "integration_qualified",
    "physical_device_qualified",
    "pilot_qualified",
    "released",
)
EXPECTED_EXTERNAL_GATES = {
    "independent_assurance": "blocked_external",
    "main_protection": "blocked_admin_setting_canonical_contract_incomplete_or_unverified",
    "physical_g1": "blocked_external",
    "production_capability_adapters": "blocked_external",
    "production_identity_and_attestation": "blocked_external",
    "production_model_provider": "blocked_external",
    "production_realtime_oauth": "blocked_external",
    "provider_credential_revocation": "blocked_external",
    "signing_pilot_release": "blocked_external",
    "vendor_firmware_ota": "blocked_upstream",
}
PINNED_BASELINE: dict[str, Any] = {
    "repository": EXPECTED_REPOSITORY,
    "repository_id": 1350829941,
    "pull_request": 101,
    "pull_request_author": "Franksudoman",
    "base_commit": "f30d12bd593e53e0d69196d28210f449d411c30b",
    "commit": "35f01329262d6a137bfa3c7e95302a397ed32676",
    "tree": "d585f78b8eddf4676bdee4d6f666a544f64a9f86",
    "source_pusher": "ProfHepta",
    "workflow_id": 345531045,
    "workflow_name": "hepta-glasses-ci",
    "workflow_run_id": 34139161340,
    "workflow_run_number": 847,
    "workflow_run_attempt": 1,
    "workflow_event": "pull_request",
    "required_jobs": list(EXPECTED_REQUIRED_JOBS),
    "artifact_id": 10025745282,
    "artifact_name": "hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676",
    "artifact_zip_sha256": "baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897",
    "artifact_member_count": 7,
    "source_gate_passed_checks": 17,
    "independent_artifact_passed_checks": 39,
    "code_owner_review_id": 5133811311,
    "code_owner_reviewer": "Tomasrgbsf",
    "code_owner_review_state": "APPROVED",
    "completed": True,
    "live_github_readback_required": True,
    "successor_requires_fresh_qualification": True,
}
EXPECTED_SUCCESSOR = {
    "identity_rule": "live_pull_request_head_and_tree",
    "maturity": "source_implemented",
    "qualified": False,
    "evidence_transfer_allowed": False,
    "ci_qualified": False,
    "integration_qualified": False,
    "physical_device_qualified": False,
    "pilot_qualified": False,
    "released": False,
}
PROJECT_KEYS = {
    "claim_ceiling",
    "external_gates",
    "plan_revision",
    "program_increment",
    "active_layers",
    "maturity_model",
    "productization_roadmap",
    "last_qualified_source",
    "current_successor",
    "repository_actionable_gate",
    "schema_version",
    "source_authority",
}
GATE_KEYS = {
    "active_open_gap_ids",
    "active_source_closed_gap_ids",
    "independent_latest_head_approval_required",
    "module_registry",
    "module_handoff",
    "module_guide",
    "base_gap_ledger",
    "active_gap_ledger",
    "metadata_validator",
    "source_coverage_validator",
    "module_handoff_validator",
    "documentation_truth_validator",
    "required_checks",
    "status",
}
SOURCE_AUTHORITY_KEYS = {
    "branch",
    "identity_rule",
    "pull_request",
    "repository",
    "required_artifact",
    "self_attested_sha_is_authoritative",
    "historical_artifact_does_not_attest_later_push",
    "main_remains_older_until_protected_adoption",
}
STALE_SOURCE_PHRASES = (
    "HG-0087 remains OPEN",
    "seven still-open production slices",
    "Speech source is unchanged by these increments",
    "HG-0087/model remains OPEN",
    "HG-0087/skills remains OPEN",
    "final unchanged head still requires a fresh complete seven-lane result",
)
PROHIBITED_PROMOTION_PATTERNS = (
    re.compile(
        r"(?:active|current) successor\s+(?:is|=|:)\s*`?"
        r"(?:ci_qualified|integration_qualified|physical_device_qualified|"
        r"pilot_qualified|released)`?",
        re.IGNORECASE,
    ),
    re.compile(r"product\s+(?:is|=|:)\s*`?released`?", re.IGNORECASE),
    re.compile(
        r"\bE[5-7]\s+(?:is|=|:)\s*(?:complete|closed|verified|passed)\b",
        re.IGNORECASE,
    ),
)
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_API_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class DocumentationTruthError(AssertionError):
    """Stable project-truth validation failure."""


def fail(message: str) -> None:
    raise DocumentationTruthError(message)


def _reject_json_constant(value: str) -> None:
    fail(f"non-finite JSON number is prohibited: {value}")


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON object member is prohibited: {key}")
        result[key] = value
    return result


def strict_json_loads(raw: bytes | str, *, label: str) -> Any:
    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(encoded) > MAX_JSON_BYTES:
        fail(f"{label} exceeds the bounded JSON size")
    try:
        return json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except DocumentationTruthError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"{label} is not strict UTF-8 JSON: {error}")


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        fail(f"value cannot be canonically encoded: {error}")


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        fail(f"missing or linked truth document: {relative}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read truth document {relative}: {error}")


def read_object(root: Path, relative: str) -> dict[str, Any]:
    value = strict_json_loads(read_text(root, relative), label=relative)
    if not isinstance(value, dict):
        fail(f"{relative} must contain an object")
    return value


def require_exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    keys = set(value)
    missing = expected - keys
    unknown = keys - expected
    if missing:
        fail(f"{label} is missing keys: {sorted(missing)}")
    if unknown:
        fail(f"{label} has unknown keys: {sorted(unknown)}")


def require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{label} must be boolean")
    return value


def require_int(value: Any, *, label: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(f"{label} must be an integer >= {minimum}")
    return value


def require_string(value: Any, *, label: str, maximum: int = 5000) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        fail(f"{label} must be a non-empty canonical string")
    if len(value) > maximum:
        fail(f"{label} exceeds {maximum} characters")
    return value


def require_sha(value: Any, *, label: str, width: int) -> str:
    text = require_string(value, label=label, maximum=width)
    pattern = SHA40 if width == 40 else SHA64
    if pattern.fullmatch(text) is None:
        fail(f"{label} must be a lowercase {width}-hex value")
    return text


def require_phrase(text: str, phrase: str, *, document: str) -> None:
    if phrase not in text:
        fail(f"{document} lacks required truth phrase: {phrase}")


def _validate_pinned_baseline(value: Any) -> None:
    if not isinstance(value, dict):
        fail("PROJECT_STATE.last_qualified_source must be an object")
    require_exact_keys(value, set(PINNED_BASELINE), label="last_qualified_source")
    for key in (
        "repository_id",
        "pull_request",
        "workflow_id",
        "workflow_run_id",
        "workflow_run_number",
        "workflow_run_attempt",
        "artifact_id",
        "artifact_member_count",
        "source_gate_passed_checks",
        "independent_artifact_passed_checks",
        "code_owner_review_id",
    ):
        require_int(value.get(key), label=f"last_qualified_source.{key}")
    for key in (
        "completed",
        "live_github_readback_required",
        "successor_requires_fresh_qualification",
    ):
        require_bool(value.get(key), label=f"last_qualified_source.{key}")
    require_sha(value.get("base_commit"), label="last_qualified_source.base_commit", width=40)
    require_sha(value.get("commit"), label="last_qualified_source.commit", width=40)
    require_sha(value.get("tree"), label="last_qualified_source.tree", width=40)
    require_sha(
        value.get("artifact_zip_sha256"),
        label="last_qualified_source.artifact_zip_sha256",
        width=64,
    )
    for key in (
        "repository",
        "pull_request_author",
        "source_pusher",
        "workflow_name",
        "workflow_event",
        "artifact_name",
        "code_owner_reviewer",
        "code_owner_review_state",
    ):
        require_string(value.get(key), label=f"last_qualified_source.{key}")
    if tuple(value.get("required_jobs", ())) != EXPECTED_REQUIRED_JOBS:
        fail("last_qualified_source.required_jobs drifted")
    if value != PINNED_BASELINE:
        changed = sorted(
            key for key in PINNED_BASELINE if value.get(key) != PINNED_BASELINE[key]
        )
        fail(f"last-qualified immutable tuple drifted: {changed}")


def _validate_successor(value: Any) -> None:
    if not isinstance(value, dict):
        fail("PROJECT_STATE.current_successor must be an object")
    require_exact_keys(value, set(EXPECTED_SUCCESSOR), label="current_successor")
    for key in (
        "qualified",
        "evidence_transfer_allowed",
        "ci_qualified",
        "integration_qualified",
        "physical_device_qualified",
        "pilot_qualified",
        "released",
    ):
        require_bool(value.get(key), label=f"current_successor.{key}")
    if value != EXPECTED_SUCCESSOR:
        fail("current successor is promoted beyond source_implemented")


def _validate_maturity_document(text: str) -> None:
    headings = re.findall(r"^###\s+(\d+)\.\s+`([^`]+)`\s*$", text, re.MULTILINE)
    expected = [
        (str(index), stage)
        for index, stage in enumerate(EXPECTED_MATURITY_STAGES, 1)
    ]
    if headings != expected:
        fail(f"maturity stage identity/order drifted: {headings}")
    for index, (_, stage) in enumerate(headings):
        marker = f"### {index + 1}. `{stage}`"
        start = text.index(marker) + len(marker)
        end = text.find("\n### ", start)
        if end < 0:
            end = text.find("\n## ", start)
        if end < 0:
            end = len(text)
        if len(text[start:end].strip()) < 120:
            fail(f"maturity stage {stage} lacks substantive semantics")
    require_phrase(
        text,
        "overall product maturity is bounded by the least mature required axis",
        document="docs/MATURITY_MODEL.md",
    )


def validate(root: Path = ROOT) -> dict[str, Any]:
    root_readme = read_text(root, "README.md")
    current_state = read_text(root, "docs/CURRENT_STATE.md")
    maturity = read_text(root, "docs/MATURITY_MODEL.md")
    roadmap = read_text(root, "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md")
    project = read_object(root, "docs/PROJECT_STATE.json")
    implementation = read_object(root, "docs/HG0087_IMPLEMENTATION_STATUS.json")
    remediation = read_object(root, "docs/REMEDIATION_GAP_LEDGER.json")

    require_exact_keys(project, PROJECT_KEYS, label="PROJECT_STATE")
    if project.get("schema_version") != 5:
        fail("PROJECT_STATE schema_version must be 5")
    if project.get("plan_revision") != EXPECTED_PLAN_REVISION:
        fail("PROJECT_STATE plan revision drifted")
    if project.get("program_increment") != "G8":
        fail("PROJECT_STATE program increment drifted")
    if project.get("external_gates") != EXPECTED_EXTERNAL_GATES:
        fail("PROJECT_STATE external gate truth drifted")
    if project.get("maturity_model") != "docs/MATURITY_MODEL.md":
        fail("PROJECT_STATE maturity model path drifted")
    if project.get("productization_roadmap") != (
        "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md"
    ):
        fail("PROJECT_STATE productization roadmap path drifted")
    _validate_pinned_baseline(project.get("last_qualified_source"))
    _validate_successor(project.get("current_successor"))

    gate = project.get("repository_actionable_gate")
    if not isinstance(gate, dict):
        fail("PROJECT_STATE lacks repository_actionable_gate")
    require_exact_keys(gate, GATE_KEYS, label="repository_actionable_gate")
    if gate.get("active_open_gap_ids") != []:
        fail("PROJECT_STATE reports repository-actionable OPEN gaps")
    if gate.get("documentation_truth_validator") != (
        "services/qualification/documentation_truth.py"
    ):
        fail("PROJECT_STATE does not register documentation truth")
    if tuple(gate.get("required_checks", ())) != EXPECTED_REQUIRED_JOBS:
        fail("PROJECT_STATE required check set drifted")
    status = gate.get("status")
    if not isinstance(status, str) or (
        "source_closed" not in status
        or "successor_source_implemented" not in status
        or "admin_and_external_authority" not in status
    ):
        fail("PROJECT_STATE gate status overclaims or omits remaining authority")

    source_authority = project.get("source_authority")
    if not isinstance(source_authority, dict):
        fail("PROJECT_STATE lacks source_authority")
    require_exact_keys(source_authority, SOURCE_AUTHORITY_KEYS, label="source_authority")
    if source_authority.get("repository") != EXPECTED_REPOSITORY:
        fail("source authority repository drifted")
    if source_authority.get("self_attested_sha_is_authoritative") is not False:
        fail("source authority permits self-attestation")
    if source_authority.get("historical_artifact_does_not_attest_later_push") is not True:
        fail("source authority permits historical evidence transfer")
    if source_authority.get("main_remains_older_until_protected_adoption") is not True:
        fail("source authority falsely promotes main")

    if implementation.get("aggregate_status") != "CLOSED_SOURCE":
        fail("HG0087 aggregate status is not CLOSED_SOURCE")
    slices = implementation.get("slices")
    if not isinstance(slices, list):
        fail("HG0087 slices are missing")
    rows: dict[str, dict[str, Any]] = {}
    for row in slices:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            fail("HG0087 contains an invalid slice")
        if row["id"] in rows:
            fail(f"HG0087 contains duplicate slice {row['id']}")
        rows[row["id"]] = row
    if set(rows) != EXPECTED_HG0087_SLICES:
        fail("HG0087 slice identity set drifted")
    for name, row in rows.items():
        if row.get("status") != "CLOSED_SOURCE":
            fail(f"HG0087 slice {name} is not CLOSED_SOURCE")
        remaining = row.get("remaining_external")
        if not isinstance(remaining, list) or not remaining:
            fail(f"HG0087 slice {name} lacks remaining external truth")
        if any(not isinstance(item, str) or not item.strip() for item in remaining):
            fail(f"HG0087 slice {name} has invalid external truth")

    gaps = remediation.get("gaps")
    if not isinstance(gaps, list):
        fail("remediation gap ledger lacks gaps")
    by_id: dict[str, dict[str, Any]] = {}
    for row in gaps:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            fail("remediation gap ledger contains an invalid row")
        if row["id"] in by_id:
            fail(f"remediation gap ledger contains duplicate {row['id']}")
        by_id[row["id"]] = row
    if by_id.get("HG-0087", {}).get("status") != "CLOSED_SOURCE":
        fail("remediation ledger disagrees on HG-0087")
    if by_id.get("HG-0089", {}).get("status") != "BLOCKED_ADMIN_SETTING":
        fail("remediation ledger does not preserve HG-0089 administration gate")
    open_rows = sorted(
        gap_id for gap_id, row in by_id.items() if row.get("status") == "OPEN"
    )
    if open_rows:
        fail(f"repository-actionable remediation rows remain OPEN: {open_rows}")

    require_phrase(
        current_state,
        f"Canonical plan revision: `{EXPECTED_PLAN_REVISION}`",
        document="docs/CURRENT_STATE.md",
    )
    for relative, text in (
        ("README.md", root_readme),
        ("docs/CURRENT_STATE.md", current_state),
    ):
        require_phrase(text, "HG-0087 is `CLOSED_SOURCE`", document=relative)
        require_phrase(text, PINNED_BASELINE["commit"], document=relative)
        require_phrase(text, PINNED_BASELINE["artifact_zip_sha256"], document=relative)
        for phrase in STALE_SOURCE_PHRASES:
            if phrase in text:
                fail(f"{relative} contains stale source-status phrase: {phrase}")
        for pattern in PROHIBITED_PROMOTION_PATTERNS:
            if pattern.search(text):
                fail(f"{relative} promotes an unqualified successor or product")

    for relative in (
        "docs/CURRENT_STATE.md",
        "docs/PROJECT_STATE.json",
        "docs/REMEDIATION_GAP_LEDGER.json",
        "docs/HG0087_IMPLEMENTATION_STATUS.json",
        "docs/MATURITY_MODEL.md",
        "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md",
        "docs/MODULE_COVERAGE.json",
        "docs/MODULE_HANDOFF.json",
        "docs/development/MODULE_HANDOFF.md",
        "contracts/conformance/canonical-json-v1.json",
    ):
        require_phrase(root_readme, relative, document="README.md")

    _validate_maturity_document(maturity)
    require_phrase(
        roadmap,
        "Source code, local tests, mocks, screenshots",
        document="productization roadmap",
    )

    return {
        "plan_revision": EXPECTED_PLAN_REVISION,
        "hg0087_status": "CLOSED_SOURCE",
        "hg0087_slices": len(rows),
        "repository_actionable_open": 0,
        "hg0089_status": "BLOCKED_ADMIN_SETTING",
        "maturity_stages": len(EXPECTED_MATURITY_STAGES),
        "last_qualified_commit": PINNED_BASELINE["commit"],
        "successor_maturity": EXPECTED_SUCCESSOR["maturity"],
        "required_jobs": len(EXPECTED_REQUIRED_JOBS),
    }


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Drop GitHub authorization before following a cross-host Artifact URL."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlsplit(request.full_url).hostname
        new_parts = urllib.parse.urlsplit(newurl)
        if new_parts.scheme != "https":
            fail("GitHub redirect attempted a non-HTTPS target")
        if old_host != new_parts.hostname:
            redirected.remove_header("Authorization")
        return redirected


_HTTP_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _api_url(path: str) -> str:
    if not path.startswith("/") or ".." in path:
        fail("invalid fixed GitHub API path")
    return "https://api.github.com" + path


def _read_url(path: str, *, token: str, maximum: int, accept: str) -> bytes:
    request = urllib.request.Request(
        _api_url(path),
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "User-Agent": "hepta-qualified-baseline-verifier/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with _HTTP_OPENER.open(request, timeout=30) as response:
            raw = response.read(maximum + 1)
    except DocumentationTruthError:
        raise
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        fail(f"GitHub evidence read failed for {path}: {error}")
    if len(raw) > maximum:
        fail(f"GitHub evidence response exceeds bound for {path}")
    return raw


def _stable_api_object(path: str, *, token: str) -> dict[str, Any]:
    first = strict_json_loads(
        _read_url(
            path,
            token=token,
            maximum=MAX_API_BYTES,
            accept="application/vnd.github+json",
        ),
        label=f"GitHub API {path}",
    )
    second = strict_json_loads(
        _read_url(
            path,
            token=token,
            maximum=MAX_API_BYTES,
            accept="application/vnd.github+json",
        ),
        label=f"GitHub API repeat {path}",
    )
    if not isinstance(first, dict) or not isinstance(second, dict):
        fail(f"GitHub API {path} must return an object")
    if canonical_bytes(first) != canonical_bytes(second):
        fail(f"GitHub API evidence changed between bounded reads: {path}")
    return first


def _stable_artifact_zip(path: str, *, token: str) -> bytes:
    first = _read_url(
        path,
        token=token,
        maximum=MAX_ARTIFACT_BYTES,
        accept="application/vnd.github+json",
    )
    second = _read_url(
        path,
        token=token,
        maximum=MAX_ARTIFACT_BYTES,
        accept="application/vnd.github+json",
    )
    if first != second:
        fail("Artifact bytes changed between bounded reads")
    return first


def _parse_time(value: Any, *, label: str) -> datetime:
    text = require_string(value, label=label, maximum=100)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        fail(f"{label} is not ISO-8601: {error}")
    if parsed.tzinfo is None:
        fail(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _contains_scalar(value: Any, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_contains_scalar(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_scalar(item, expected) for item in value)
    return False


def _checks_pass(checks: Any) -> bool:
    if isinstance(checks, dict) and len(checks) == 17:
        return all(
            item is True
            or (isinstance(item, dict) and item.get("passed") is True)
            for item in checks.values()
        )
    if isinstance(checks, list) and len(checks) == 17:
        return all(
            item is True
            or (isinstance(item, dict) and item.get("passed") is True)
            for item in checks
        )
    return False


def _has_source_gate(value: Any) -> bool:
    if isinstance(value, dict):
        if (
            value.get("passed") is True
            and value.get("missing") == []
            and _checks_pass(value.get("checks"))
        ):
            return True
        return any(_has_source_gate(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_source_gate(item) for item in value)
    return False


def _verify_artifact_zip(raw: bytes) -> list[str]:
    if hashlib.sha256(raw).hexdigest() != PINNED_BASELINE["artifact_zip_sha256"]:
        fail("Artifact ZIP digest does not match the pinned baseline")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as error:
        fail(f"qualified baseline Artifact is not a ZIP: {error}")
    names: list[str] = []
    parsed_objects: list[Any] = []
    total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) != PINNED_BASELINE["artifact_member_count"]:
            fail("qualified baseline Artifact member count drifted")
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or pure.is_absolute()
                or any(part in {"", ".", ".."} for part in pure.parts)
                or info.is_dir()
            ):
                fail(f"unsafe Artifact member path: {name!r}")
            mode = info.external_attr >> 16
            if mode and not stat.S_ISREG(mode):
                fail(f"Artifact member is not a regular file: {name}")
            if name in names:
                fail(f"duplicate Artifact member: {name}")
            total += info.file_size
            if total > MAX_ARTIFACT_BYTES:
                fail("Artifact uncompressed content exceeds bound")
            try:
                data = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                fail(f"Artifact member read/CRC failed for {name}: {error}")
            names.append(name)
            if name.endswith(".json"):
                parsed_objects.append(strict_json_loads(data, label=f"Artifact {name}"))
    if not parsed_objects:
        fail("Artifact contains no strict JSON evidence")
    commit = PINNED_BASELINE["commit"]
    tree = PINNED_BASELINE["tree"]
    if not any(_contains_scalar(value, commit) for value in parsed_objects):
        fail("Artifact members do not bind the pinned commit")
    if not any(_contains_scalar(value, tree) for value in parsed_objects):
        fail("Artifact members do not bind the pinned tree")
    if not any(_has_source_gate(value) for value in parsed_objects):
        fail("Artifact lacks the pinned 17-check passing source gate")
    if not any(
        isinstance(value, dict)
        and value.get("spdxVersion") == "SPDX-2.3"
        for value in parsed_objects
    ):
        fail("Artifact lacks an SPDX 2.3 SBOM")
    return sorted(names)


def _require_path(value: Any, path: tuple[str, ...], *, label: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            fail(f"{label} lacks {'.'.join(path)}")
        current = current[key]
    return current


def verify_github_baseline(token: str | None = None) -> dict[str, Any]:
    auth = token or os.environ.get("GITHUB_TOKEN")
    if not auth:
        fail("GITHUB_TOKEN is required for live qualified-baseline verification")
    if os.environ.get("GITHUB_REPOSITORY", EXPECTED_REPOSITORY) != EXPECTED_REPOSITORY:
        fail("live qualified-baseline verification ran in the wrong repository")

    owner_repo = EXPECTED_REPOSITORY
    commit_sha = PINNED_BASELINE["commit"]
    pr_number = PINNED_BASELINE["pull_request"]
    run_id = PINNED_BASELINE["workflow_run_id"]
    artifact_id = PINNED_BASELINE["artifact_id"]
    review_id = PINNED_BASELINE["code_owner_review_id"]

    commit = _stable_api_object(f"/repos/{owner_repo}/commits/{commit_sha}", token=auth)
    if commit.get("sha") != commit_sha:
        fail("GitHub commit identity drifted")
    if _require_path(commit, ("commit", "tree", "sha"), label="commit") != PINNED_BASELINE["tree"]:
        fail("GitHub commit no longer resolves to the pinned tree")
    commit_author = _require_path(commit, ("author", "login"), label="commit")
    if commit_author != PINNED_BASELINE["source_pusher"]:
        fail("GitHub commit source actor drifted")

    pull = _stable_api_object(f"/repos/{owner_repo}/pulls/{pr_number}", token=auth)
    if pull.get("number") != pr_number:
        fail("GitHub pull request identity drifted")
    if _require_path(pull, ("head", "sha"), label="pull request") != commit_sha:
        fail("qualified pull request head drifted")
    if _require_path(pull, ("base", "sha"), label="pull request") != PINNED_BASELINE["base_commit"]:
        fail("qualified pull request base drifted")
    pull_author = _require_path(pull, ("user", "login"), label="pull request")
    if pull_author != PINNED_BASELINE["pull_request_author"]:
        fail("qualified pull request author drifted")

    run = _stable_api_object(f"/repos/{owner_repo}/actions/runs/{run_id}", token=auth)
    exact_run_fields = {
        "id": run_id,
        "workflow_id": PINNED_BASELINE["workflow_id"],
        "name": PINNED_BASELINE["workflow_name"],
        "run_number": PINNED_BASELINE["workflow_run_number"],
        "run_attempt": PINNED_BASELINE["workflow_run_attempt"],
        "event": PINNED_BASELINE["workflow_event"],
        "head_sha": commit_sha,
        "status": "completed",
        "conclusion": "success",
    }
    for key, expected in exact_run_fields.items():
        if run.get(key) != expected:
            fail(f"qualified workflow run field drifted: {key}")
    if _require_path(run, ("head_commit", "id"), label="workflow run") != commit_sha:
        fail("workflow run head commit drifted")
    if _require_path(run, ("head_commit", "tree_id"), label="workflow run") != PINNED_BASELINE["tree"]:
        fail("workflow run tree drifted")
    run_prs = run.get("pull_requests")
    if not isinstance(run_prs, list) or not any(
        isinstance(item, dict)
        and item.get("number") == pr_number
        and _require_path(item, ("head", "sha"), label="workflow PR") == commit_sha
        and _require_path(item, ("base", "sha"), label="workflow PR") == PINNED_BASELINE["base_commit"]
        for item in run_prs
    ):
        fail("workflow run is not bound to the qualified pull request")

    jobs_payload = _stable_api_object(
        f"/repos/{owner_repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100",
        token=auth,
    )
    jobs = jobs_payload.get("jobs")
    if jobs_payload.get("total_count") != len(EXPECTED_REQUIRED_JOBS) or not isinstance(jobs, list):
        fail("qualified workflow does not contain exactly seven jobs")
    by_name: dict[str, dict[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            fail("qualified workflow contains an invalid job")
        if job["name"] in by_name:
            fail(f"qualified workflow contains duplicate job {job['name']}")
        by_name[job["name"]] = job
    if set(by_name) != set(EXPECTED_REQUIRED_JOBS):
        fail("qualified workflow job identity set drifted")
    for name in EXPECTED_REQUIRED_JOBS:
        job = by_name[name]
        if job.get("run_id") != run_id or job.get("head_sha") != commit_sha:
            fail(f"qualified job source binding drifted: {name}")
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            fail(f"qualified job is not successful: {name}")
        steps = job.get("steps")
        if not isinstance(steps, list) or len(steps) < 4:
            fail(f"qualified job is empty: {name}")
        identity_steps = [
            step
            for step in steps
            if isinstance(step, dict) and step.get("name") == "Verify exact source identity"
        ]
        if len(identity_steps) != 1 or identity_steps[0].get("conclusion") != "success":
            fail(f"qualified job lacks successful exact-source verification: {name}")
        substantive = [
            step
            for step in steps
            if isinstance(step, dict)
            and step.get("number", 0) > 3
            and step.get("status") == "completed"
            and step.get("conclusion") == "success"
            and not str(step.get("name", "")).startswith("Post ")
            and step.get("name") != "Complete job"
        ]
        if not substantive:
            fail(f"qualified job has no successful substantive step: {name}")

    artifacts_payload = _stable_api_object(
        f"/repos/{owner_repo}/actions/runs/{run_id}/artifacts?per_page=100",
        token=auth,
    )
    artifacts = artifacts_payload.get("artifacts")
    if not isinstance(artifacts, list):
        fail("qualified run artifact listing is invalid")
    selected = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("id") == artifact_id
    ]
    if len(selected) != 1:
        fail("qualified Artifact is missing or duplicated")
    artifact = selected[0]
    if artifact.get("name") != PINNED_BASELINE["artifact_name"]:
        fail("qualified Artifact name drifted")
    if artifact.get("digest") != f"sha256:{PINNED_BASELINE['artifact_zip_sha256']}":
        fail("qualified Artifact server digest drifted")
    if artifact.get("expired") is not False:
        fail("qualified Artifact is expired")
    artifact_run = artifact.get("workflow_run")
    if not isinstance(artifact_run, dict) or (
        artifact_run.get("id") != run_id
        or artifact_run.get("repository_id") != PINNED_BASELINE["repository_id"]
        or artifact_run.get("head_sha") != commit_sha
    ):
        fail("qualified Artifact workflow binding drifted")
    inventory = _verify_artifact_zip(
        _stable_artifact_zip(
            f"/repos/{owner_repo}/actions/artifacts/{artifact_id}/zip",
            token=auth,
        )
    )

    review = _stable_api_object(
        f"/repos/{owner_repo}/pulls/{pr_number}/reviews/{review_id}", token=auth
    )
    if review.get("id") != review_id:
        fail("qualified review identity drifted")
    if review.get("state") != PINNED_BASELINE["code_owner_review_state"]:
        fail("qualified review is no longer APPROVED")
    if review.get("commit_id") != commit_sha:
        fail("qualified review is not bound to the pinned commit")
    reviewer = _require_path(review, ("user", "login"), label="review")
    if reviewer != PINNED_BASELINE["code_owner_reviewer"]:
        fail("qualified reviewer identity drifted")
    if reviewer in {pull_author, commit_author}:
        fail("qualified reviewer is not independent of author/source actor")
    body = review.get("body")
    if not isinstance(body, str) or any(
        item not in body for item in (commit_sha, str(run_id), str(artifact_id))
    ):
        fail("qualified review body lacks exact source/run/Artifact binding")

    codeowners_payload = _stable_api_object(
        f"/repos/{owner_repo}/contents/.github/CODEOWNERS?ref={PINNED_BASELINE['base_commit']}",
        token=auth,
    )
    encoded = codeowners_payload.get("content")
    if codeowners_payload.get("encoding") != "base64" or not isinstance(encoded, str):
        fail("base CODEOWNERS response is invalid")
    try:
        codeowners = base64.b64decode(
            "".join(encoded.split()), validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeError) as error:
        fail(f"base CODEOWNERS cannot be decoded: {error}")
    wildcard_lines = [
        line.split("#", 1)[0].strip()
        for line in codeowners.splitlines()
        if line.split("#", 1)[0].strip().startswith("*")
    ]
    if not any(f"@{reviewer}" in line.split()[1:] for line in wildcard_lines):
        fail("qualified reviewer is not a base-branch wildcard Code Owner")

    run_completed = _parse_time(run.get("updated_at"), label="workflow updated_at")
    review_submitted = _parse_time(review.get("submitted_at"), label="review submitted_at")
    if review_submitted <= run_completed:
        fail("qualified review predates terminal workflow evidence")

    return {
        "repository": owner_repo,
        "commit": commit_sha,
        "tree": PINNED_BASELINE["tree"],
        "run_id": run_id,
        "jobs": len(by_name),
        "artifact_id": artifact_id,
        "artifact_members": inventory,
        "review_id": review_id,
        "reviewer": reviewer,
        "stable_double_reads": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-github",
        action="store_true",
        help="perform bounded read-only live GitHub verification of the pinned baseline",
    )
    arguments = parser.parse_args(argv)
    try:
        result: dict[str, Any] = validate()
        if arguments.verify_github:
            result["github_baseline"] = verify_github_baseline()
    except (DocumentationTruthError, OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
