#!/usr/bin/env python3
"""Fail closed when repository status prose or retained source evidence drifts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
PLAN = "2026-09-01-g8"
JOBS = (
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
)
SLICES = {"identity", "model", "realtime", "capabilities", "speech", "skills", "memory"}
STAGE_HEADINGS = (
    "### 1. `design_draft`",
    "### 2. `source_implemented`",
    "### 3. `ci_qualified`",
    "### 4. `integration_qualified`",
    "### 5. `physical_device_qualified`",
    "### 6. `pilot_qualified`",
    "### 7. `released`",
)
STALE = (
    "HG-0087 remains OPEN",
    "seven still-open production slices",
    "Speech source is unchanged by these increments",
    "HG-0087/model remains OPEN",
    "HG-0087/skills remains OPEN",
    "final unchanged head still requires a fresh complete seven-lane result",
)
FALSE_PROMOTIONS = (
    "current successor is `ci_qualified`",
    "successor status: `ci_qualified`",
    "successor embedded maturity: `ci_qualified`",
    "current successor is `released`",
    "successor status: `released`",
    "product status: `released`",
    "current qualified baseline is this successor",
    "this successor is the current qualified baseline",
    "e5-e7 complete",
    "all external gates are closed",
)
MANIFEST_PATH = "evidence/source-baselines/pr101-35f01329/manifest.json"
MANIFEST_SHA256 = "d7b1454f835e26789148e2e6f46e492f2ea85fac64e8cef10c7d2929208809d5"
ARCHIVE_REFERENCE = MANIFEST_PATH + "#artifact.archive_parts"
PIN = {
    "repository": "TrillionniumFoundation/hepta-glasses",
    "pull_request": 101,
    "base_commit": "f30d12bd593e53e0d69196d28210f449d411c30b",
    "source_commit": "35f01329262d6a137bfa3c7e95302a397ed32676",
    "source_tree": "d585f78b8eddf4676bdee4d6f666a544f64a9f86",
    "prospective_merge_commit": "ca05b315ef619b68574bb7e834ca0bfa49a48ab3",
    "workflow_run_id": 34139161340,
    "workflow_run_number": 847,
    "workflow_id": 345531045,
    "artifact_id": 10025745282,
    "artifact_name": "hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676",
    "artifact_sha256": "baa9c218a779adb4713e5985d4109b20db70087e93fca34f2a9ba08e157af897",
    "review_id": 5133811311,
    "reviewer": "Tomasrgbsf",
    "pr_author": "Franksudoman",
    "latest_pusher": "ProfHepta",
}
JOB_IDS = {
    "repository-contracts": 101796977371,
    "flutter": 101796977423,
    "android-native": 101796977405,
    "ios-native": 101796977428,
    "native-sanitizers": 101796977363,
    "secret-and-boundary-scan": 101796977247,
    "source-evidence": 101801522239,
}
MEMBERS = {
    "source-evidence-summary.json": (850, "15d61930b389f517cac137bf00a691a4ef74133a7124591b67312406c48ee8be"),
    "source-gate-result.json": (588, "68645fe9b446ea707a9b2622afc2eb3b208a9c5fe18c7314707807e592ae3e83"),
    "source-history-scan.json": (2907, "bc848193857e370a4f8d8e9b99ed470c2a36f8e49ca73b1cf8f570aa3cebeedf"),
    "source-native-sanitizer.json": (332, "6aeebca75e217dc0ea7642b82a43fa80037bd234a81968fdedc511a8b6ef8efe"),
    "source-provenance.json": (695, "02aba1f6a7036d22732e2bbdea4efbb2b4a8659e02b333ef1b3b754bb3c506bb"),
    "source-release-bundle.json": (1731, "c43f8083859b98036b901b0fd8c7dc8b1f4b15690b00823bfb782dbb67bd8a1a"),
    "source-sbom.spdx.json": (259441, "7ff5e31e53c5c1a7d283d0714089d28c0b8cf3784a33352cbc68826b40493b76"),
}
PARTS = {
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part01": (8192, "813614538199ef4166605ecaacbe0023150fb57ce5200b1450a17fc3761b23ad"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part02": (8192, "5c752600759c131c927402eddbbfe286aa697bda0282dde5e02bee096770b79f"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part03": (8192, "0ce241fc007844b6196726fd49e52942a0dd83d8411a54989b865ba376fefe14"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part04": (8192, "1a696afe2e52717103a19fcd3dcf3f93647d38d5ce33b0c60ce5c577a4003be2"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part05": (8192, "103fb81c8f15ca849f5e812b8ba2d14ceef14786724a07cf788512ad7247d171"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part06": (8192, "d7335f8b88ba75da765014a5849d2eef149c68da42d80142cd7e841110d5841e"),
    "evidence/source-baselines/pr101-35f01329/hepta-source-evidence-35f01329262d6a137bfa3c7e95302a397ed32676.zip.b64.part07": (7184, "e20db83a3e69a53aea545c95dc921b5089f815fc839dee876edf94775baf8e3a"),
}
GATE_CHECKS = {
    "artifact_history_content", "artifact_history_digest",
    "artifact_native_content", "artifact_native_digest",
    "artifact_provenance_digest", "artifact_sbom_digest",
    "audit_contract", "contracts_version", "exact_commit", "exact_tree",
    "history_scan", "native_sanitizer", "provenance", "provenance_type",
    "required_ci", "sbom", "sbom_ecosystems",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON = 2 * 1024 * 1024
MAX_ARCHIVE = 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024

PROJECT_KEYS = {
    "claim_ceiling", "external_gates", "plan_revision", "program_increment",
    "active_layers", "maturity_model", "productization_roadmap",
    "last_qualified_source", "active_successor", "repository_actionable_gate",
    "schema_version", "source_authority",
}
LAST_KEYS = {
    "repository", "pull_request", "commit", "tree", "workflow_run_id",
    "workflow_run_number", "required_jobs", "artifact_id", "artifact_name",
    "artifact_zip_sha256", "source_gate_checks",
    "independent_artifact_checks", "code_owner_review_id",
    "code_owner_reviewer", "completed",
    "successor_requires_fresh_qualification", "evidence_manifest",
    "evidence_manifest_sha256", "retained_artifact",
}
SUCCESSOR_KEYS = {
    "identity_rule", "embedded_maturity", "qualification_authority",
    "inherits_baseline_evidence", "released",
}
EXTERNAL_KEYS = {
    "independent_assurance", "main_protection", "physical_g1",
    "production_capability_adapters", "production_identity_and_attestation",
    "production_model_provider", "production_realtime_oauth",
    "provider_credential_revocation", "signing_pilot_release",
    "vendor_firmware_ota",
}
REPOSITORY_GATE_KEYS = {
    "active_open_gap_ids", "active_source_closed_gap_ids",
    "independent_latest_head_approval_required", "module_registry",
    "module_handoff", "module_guide", "base_gap_ledger", "active_gap_ledger",
    "metadata_validator", "source_coverage_validator",
    "module_handoff_validator", "documentation_truth_validator",
    "required_checks", "status",
}
SOURCE_AUTHORITY_KEYS = {
    "branch", "identity_rule", "pull_request", "repository",
    "required_artifact", "self_attested_sha_is_authoritative",
    "historical_artifact_does_not_attest_later_push",
    "main_remains_older_until_protected_adoption",
}
MANIFEST_KEYS = {
    "schema_version", "record_type", "evidence_scope", "repository",
    "pull_request", "base_commit", "source_commit", "source_tree",
    "prospective_merge_commit", "workflow", "artifact", "source_gate",
    "independent_review", "independent_artifact_verification", "claim_ceiling",
}


class DocumentationTruthError(AssertionError):
    pass


def fail(message: str) -> None:
    raise DocumentationTruthError(message)


def reject_constant(value: str) -> None:
    fail(f"non-finite JSON number is prohibited: {value}")


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON object member is prohibited: {key}")
        result[key] = value
    return result


def exact(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    missing, unknown = keys - set(value), set(value) - keys
    if missing:
        fail(f"{label} is missing keys: {sorted(missing)}")
    if unknown:
        fail(f"{label} has unknown keys: {sorted(unknown)}")


def string(value: Any, label: str, maximum: int = 5000) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        fail(f"{label} must be a non-empty trimmed string")
    if len(value) > maximum:
        fail(f"{label} exceeds {maximum} characters")
    return value


def integer(value: Any, label: str, maximum: int = 2**63 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        fail(f"{label} must be a bounded non-negative integer")
    return value


def sha(value: Any, label: str, width: int) -> str:
    text = string(value, label, width)
    if (SHA40 if width == 40 else SHA64).fullmatch(text) is None:
        fail(f"{label} must be lowercase {width}-hex")
    return text


def strings(value: Any, label: str, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= 256:
        fail(f"{label} must be a bounded string list")
    result = [string(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        fail(f"{label} contains duplicates")
    return result


def repo_file(root: Path, relative: str) -> Path:
    pure = PurePosixPath(string(relative, "repository path", 500))
    if pure.is_absolute() or "\\" in relative or any(p in {"", ".", ".."} for p in pure.parts):
        fail(f"repository path is non-canonical: {relative}")
    path = root
    for part in pure.parts:
        path /= part
        if path.is_symlink():
            fail(f"linked truth path is prohibited: {relative}")
    if not path.is_file():
        fail(f"missing truth file: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        fail(f"truth path escapes repository root: {relative}")
    return path


def raw_file(root: Path, relative: str, maximum: int = MAX_JSON) -> bytes:
    path = repo_file(root, relative)
    size = path.stat().st_size
    if size > maximum:
        fail(f"truth file exceeds {maximum} bytes: {relative}")
    raw = path.read_bytes()
    if len(raw) != size:
        fail(f"truth file changed while read: {relative}")
    return raw


def text_file(root: Path, relative: str) -> str:
    try:
        return raw_file(root, relative).decode("utf-8")
    except UnicodeDecodeError as error:
        fail(f"{relative} is not UTF-8: {error}")


def object_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicates,
        )
    except DocumentationTruthError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"invalid truth JSON {label}: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must contain an object")
    return value


def object_file(root: Path, relative: str) -> dict[str, Any]:
    return object_bytes(raw_file(root, relative), relative)


def phrase(text: str, expected: str, label: str) -> None:
    if expected not in text:
        fail(f"{label} lacks required phrase: {expected}")


def git(root: Path, *args: str) -> str:
    binary = Path("/usr/bin/git")
    if not binary.is_file():
        fail("trusted git executable /usr/bin/git is unavailable")
    result = subprocess.run(
        [str(binary), *args],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": os.devnull,
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        fail(f"git {' '.join(args)} failed: {(result.stderr or result.stdout)[:500]}")
    return result.stdout


HistoryVerifier = Callable[[Path, Mapping[str, Any]], None]


def verify_history(root: Path, manifest: Mapping[str, Any]) -> None:
    commit, tree = manifest["source_commit"], manifest["source_tree"]
    lines = git(root, "cat-file", "-p", commit).splitlines()
    if not lines or lines[0] != f"tree {tree}":
        fail("baseline source commit does not resolve to the pinned tree")
    git(root, "merge-base", "--is-ancestor", commit, "HEAD")
    reviewer = manifest["independent_review"]["reviewer"]
    if f"@{reviewer}" not in git(root, "show", f"{commit}:.github/CODEOWNERS"):
        fail("baseline reviewer is absent from reviewed-commit CODEOWNERS")


def load_manifest(root: Path, expected_digest: str) -> dict[str, Any]:
    raw = raw_file(root, MANIFEST_PATH, 64 * 1024)
    value = object_bytes(raw, MANIFEST_PATH)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        fail("pinned baseline manifest digest mismatch")
    return value


def validate_manifest(
    root: Path,
    manifest: Mapping[str, Any],
    history_verifier: HistoryVerifier,
) -> dict[str, bytes]:
    exact(manifest, MANIFEST_KEYS, "baseline manifest")
    if manifest["schema_version"] != 1:
        fail("baseline manifest schema_version drifted")
    if manifest["record_type"] != "independently-reviewed-source-baseline-v1":
        fail("baseline manifest record_type drifted")
    if manifest["evidence_scope"] != "historical_repository_source_qualification_only":
        fail("baseline manifest evidence_scope drifted")
    for key in ("base_commit", "source_commit", "source_tree", "prospective_merge_commit"):
        sha(manifest[key], f"baseline.{key}", 40)
    for key in ("repository", "pull_request", "base_commit", "source_commit",
                "source_tree", "prospective_merge_commit"):
        if manifest[key] != PIN[key]:
            fail(f"baseline {key} differs from immutable pin")

    workflow = manifest["workflow"]
    if not isinstance(workflow, dict):
        fail("baseline.workflow must be an object")
    exact(workflow, {
        "id", "run_number", "attempt", "workflow_id", "name", "event",
        "status", "conclusion", "head_branch", "head_commit", "head_tree", "jobs",
    }, "baseline.workflow")
    expected_workflow = {
        "id": PIN["workflow_run_id"], "run_number": PIN["workflow_run_number"],
        "attempt": 1, "workflow_id": PIN["workflow_id"], "name": "hepta-glasses-ci",
        "event": "pull_request", "status": "completed", "conclusion": "success",
        "head_branch": "work/hepta-g10-trusted-openssl-custody-20260902",
        "head_commit": PIN["source_commit"], "head_tree": PIN["source_tree"],
    }
    for key, expected in expected_workflow.items():
        if workflow[key] != expected:
            fail(f"baseline workflow {key} differs from immutable pin")
    jobs = workflow["jobs"]
    if not isinstance(jobs, list) or len(jobs) != 7:
        fail("baseline workflow must contain seven jobs")
    seen: list[str] = []
    for index, row in enumerate(jobs):
        if not isinstance(row, dict):
            fail(f"baseline job {index} must be an object")
        exact(row, {"id", "name", "status", "conclusion", "substantive_steps"},
              f"baseline job {index}")
        name = string(row["name"], f"baseline job {index}.name")
        if row["id"] != JOB_IDS.get(name):
            fail(f"baseline job ID mismatch: {name}")
        if row["status"] != "completed" or row["conclusion"] != "success":
            fail(f"baseline job is not terminal-success: {name}")
        if "Verify exact source identity" not in strings(
            row["substantive_steps"], f"baseline job {name}.steps", 1
        ):
            fail(f"baseline job lacks exact-head verification: {name}")
        seen.append(name)
    if tuple(seen) != JOBS:
        fail("baseline job identity/order drifted")

    artifact = manifest["artifact"]
    if not isinstance(artifact, dict):
        fail("baseline.artifact must be an object")
    exact(artifact, {
        "id", "name", "size_in_bytes", "zip_sha256", "archive_encoding",
        "encoded_size", "archive_parts", "workflow_run_id", "head_commit",
        "members",
    }, "baseline.artifact")
    expected_artifact = {
        "id": PIN["artifact_id"], "name": PIN["artifact_name"],
        "zip_sha256": PIN["artifact_sha256"],
        "archive_encoding": "base64-parts-v1",
        "encoded_size": 56336,
        "workflow_run_id": PIN["workflow_run_id"],
        "head_commit": PIN["source_commit"],
    }
    for key, expected in expected_artifact.items():
        if artifact[key] != expected:
            fail(f"baseline artifact {key} differs from immutable pin")
    size = integer(artifact["size_in_bytes"], "baseline artifact size", MAX_ARCHIVE)
    sha(artifact["zip_sha256"], "baseline artifact digest", 64)
    encoded_size = integer(
        artifact["encoded_size"], "baseline artifact encoded size", MAX_ARCHIVE * 2
    )
    part_rows = artifact["archive_parts"]
    if not isinstance(part_rows, list) or len(part_rows) != len(PARTS):
        fail("baseline artifact archive parts are incomplete")
    listed_parts: dict[str, tuple[int, str]] = {}
    for index, row in enumerate(part_rows):
        if not isinstance(row, dict):
            fail(f"baseline archive part {index} must be an object")
        exact(
            row,
            {"path", "encoded_size", "sha256"},
            f"baseline archive part {index}",
        )
        path = string(row["path"], f"baseline archive part {index}.path", 500)
        if path in listed_parts:
            fail(f"baseline archive part is duplicated: {path}")
        listed_parts[path] = (
            integer(
                row["encoded_size"],
                f"baseline archive part {index}.encoded_size",
                MAX_ARCHIVE,
            ),
            sha(row["sha256"], f"baseline archive part {index}.sha256", 64),
        )
    if listed_parts != PARTS or sum(value[0] for value in PARTS.values()) != encoded_size:
        fail("baseline artifact archive parts differ from immutable pins")

    listed: dict[str, tuple[int, str]] = {}
    if not isinstance(artifact["members"], list):
        fail("baseline artifact members must be a list")
    for index, row in enumerate(artifact["members"]):
        if not isinstance(row, dict):
            fail(f"baseline member {index} must be an object")
        exact(row, {"name", "size", "sha256"}, f"baseline member {index}")
        name = string(row["name"], f"baseline member {index}.name", 200)
        if name in listed:
            fail(f"baseline artifact member is duplicated: {name}")
        listed[name] = (
            integer(row["size"], f"baseline member {index}.size", MAX_EXPANDED),
            sha(row["sha256"], f"baseline member {index}.sha256", 64),
        )
    if len(artifact["members"]) != len(MEMBERS) or listed != MEMBERS:
        fail("baseline artifact members differ from immutable pins")

    source_gate = manifest["source_gate"]
    if not isinstance(source_gate, dict):
        fail("baseline.source_gate must be an object")
    exact(source_gate, {"passed", "check_count", "missing"}, "baseline.source_gate")
    if source_gate != {"passed": True, "check_count": 17, "missing": []}:
        fail("baseline source gate summary drifted")

    review = manifest["independent_review"]
    if not isinstance(review, dict):
        fail("baseline.independent_review must be an object")
    exact(review, {
        "review_id", "state", "reviewer", "reviewed_commit", "submitted_at",
        "author_association", "pull_request_author", "latest_source_pusher",
        "code_owner_at_reviewed_commit", "reviewer_is_pull_request_author",
        "reviewer_is_latest_source_pusher",
    }, "baseline.independent_review")
    expected_review = {
        "review_id": PIN["review_id"], "state": "APPROVED",
        "reviewer": PIN["reviewer"], "reviewed_commit": PIN["source_commit"],
        "submitted_at": "2026-09-07T16:00:09Z", "author_association": "MEMBER",
        "pull_request_author": PIN["pr_author"],
        "latest_source_pusher": PIN["latest_pusher"],
        "code_owner_at_reviewed_commit": True,
        "reviewer_is_pull_request_author": False,
        "reviewer_is_latest_source_pusher": False,
    }
    if review != expected_review:
        fail("baseline independent review differs from immutable pin")
    if review["reviewer"] in {review["pull_request_author"], review["latest_source_pusher"]}:
        fail("baseline reviewer is not independent")

    verification = manifest["independent_artifact_verification"]
    if not isinstance(verification, dict):
        fail("baseline.independent_artifact_verification must be an object")
    exact(verification, {"review_id", "passed", "check_count"},
          "baseline.independent_artifact_verification")
    if verification != {"review_id": PIN["review_id"], "passed": True, "check_count": 39}:
        fail("baseline independent artifact verification drifted")
    if "never attests a successor" not in string(
        manifest["claim_ceiling"], "baseline.claim_ceiling", 1000
    ):
        fail("baseline claim ceiling permits successor transfer")

    archive = read_archive_parts(root, listed_parts, encoded_size)
    if len(archive) != size or hashlib.sha256(archive).hexdigest() != PIN["artifact_sha256"]:
        fail("retained baseline archive size or digest mismatch")
    payloads = validate_archive(archive, listed)
    validate_payloads(payloads, manifest)
    history_verifier(root, manifest)
    return payloads


def read_archive_parts(
    root: Path,
    expected: Mapping[str, tuple[int, str]],
    encoded_size: int,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for relative, (expected_size, expected_digest) in expected.items():
        raw = raw_file(root, relative, MAX_ARCHIVE)
        if (
            len(raw) != expected_size
            or hashlib.sha256(raw).hexdigest() != expected_digest
        ):
            fail(f"retained archive part size or digest mismatch: {relative}")
        if any(byte not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for byte in raw):
            fail(f"retained archive part is not strict base64: {relative}")
        total += len(raw)
        if total > MAX_ARCHIVE * 2:
            fail("retained archive base64 exceeds bounded size")
        chunks.append(raw)
    if total != encoded_size:
        fail("retained archive encoded size mismatch")
    try:
        return base64.b64decode(b"".join(chunks), validate=True)
    except (ValueError, binascii.Error) as error:
        fail(f"retained archive base64 is invalid: {error}")


def validate_archive(raw: bytes, expected: Mapping[str, tuple[int, str]]) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as error:
        fail(f"retained baseline archive is invalid: {error}")
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or set(names) != set(expected):
            fail("retained baseline archive inventory mismatch")
        if archive.testzip() is not None:
            fail("retained baseline archive CRC failure")
        total, payloads = 0, {}
        for info in infos:
            pure = PurePosixPath(info.filename)
            mode = info.external_attr >> 16
            if (
                "\\" in info.filename or pure.is_absolute() or len(pure.parts) != 1
                or any(part in {"", ".", ".."} for part in pure.parts)
                or info.is_dir() or info.flag_bits & 1
                or (mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG})
            ):
                fail(f"unsafe retained archive member: {info.filename}")
            expected_size, expected_digest = expected[info.filename]
            total += info.file_size
            if total > MAX_EXPANDED or info.file_size != expected_size:
                fail(f"retained archive member size mismatch: {info.filename}")
            data = archive.read(info)
            if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_digest:
                fail(f"retained archive member digest mismatch: {info.filename}")
            payloads[info.filename] = data
        return payloads


def validate_payloads(payloads: Mapping[str, bytes], manifest: Mapping[str, Any]) -> None:
    docs = {
        name: object_bytes(data, name)
        for name, data in payloads.items()
        if name.endswith(".json")
    }
    summary = docs["source-evidence-summary.json"]
    gate = docs["source-gate-result.json"]
    history = docs["source-history-scan.json"]
    native = docs["source-native-sanitizer.json"]
    provenance = docs["source-provenance.json"]
    release = docs["source-release-bundle.json"]
    sbom = docs["source-sbom.spdx.json"]
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}

    if summary.get("commit") != PIN["source_commit"] or summary.get("tree") != PIN["source_tree"]:
        fail("source evidence summary commit/tree mismatch")
    if summary.get("contracts_version") != PLAN:
        fail("source evidence summary revision drifted")
    for field, member in {
        "native_sanitizer_digest": "source-native-sanitizer.json",
        "provenance_digest": "source-provenance.json",
        "sbom_digest": "source-sbom.spdx.json",
    }.items():
        if summary.get(field) != digests[member]:
            fail(f"source evidence summary {field} mismatch")

    checks = gate.get("checks")
    if (
        not isinstance(checks, dict) or set(checks) != GATE_CHECKS
        or any(value is not True for value in checks.values())
        or gate.get("passed") is not True or gate.get("missing") != []
        or gate.get("mode") != "source"
    ):
        fail("source gate payload is incomplete or ambiguous")
    if len(checks) != manifest["source_gate"]["check_count"]:
        fail("source gate payload count differs from manifest")

    if history.get("head") != PIN["source_commit"]:
        fail("history scan head mismatch")
    for field in ("finding_count", "unscanned_blob_count", "unused_acknowledgement_count"):
        if history.get(field) != 0:
            fail(f"history scan reports {field}")
    if native.get("passed") is not True or native.get("lc3_cross_platform_parity") is not True:
        fail("native sanitizer payload is not passed")
    if (
        provenance.get("repository") != PIN["repository"]
        or provenance.get("commit") != PIN["source_commit"]
        or provenance.get("tree") != PIN["source_tree"]
        or provenance.get("type") != "unsigned-source-provenance-v1"
    ):
        fail("source provenance identity/type mismatch")
    for field, member in {
        "history_scan_digest": "source-history-scan.json",
        "native_sanitizer_digest": "source-native-sanitizer.json",
        "sbom_digest": "source-sbom.spdx.json",
    }.items():
        if provenance.get(field) != digests[member]:
            fail(f"source provenance {field} mismatch")

    source = release.get("source")
    if not isinstance(source, dict):
        fail("source release bundle lacks source object")
    if source.get("commit") != PIN["source_commit"] or source.get("tree") != PIN["source_tree"]:
        fail("source release bundle commit/tree mismatch")
    ci = source.get("ci_checks")
    if (
        not isinstance(ci, list)
        or tuple(row.get("name") for row in ci if isinstance(row, dict)) != JOBS[:-1]
        or any(not isinstance(row, dict) or row.get("conclusion") != "success" for row in ci)
    ):
        fail("source release bundle CI identity/result drifted")
    for section, member in {
        "history_scan": "source-history-scan.json",
        "native_sanitizer": "source-native-sanitizer.json",
        "provenance": "source-provenance.json",
        "sbom": "source-sbom.spdx.json",
    }.items():
        value = source.get(section)
        if not isinstance(value, dict) or value.get("sha256") != digests[member]:
            fail(f"source release bundle {section} digest mismatch")
    if (
        not isinstance(sbom.get("packages"), list)
        or len(sbom["packages"]) != summary.get("package_count")
        or not isinstance(sbom.get("files"), list)
        or len(sbom["files"]) != summary.get("file_count")
    ):
        fail("SBOM counts differ from source evidence summary")


def validate_project(
    project: Mapping[str, Any],
    implementation: Mapping[str, Any],
    remediation: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    exact(project, PROJECT_KEYS, "PROJECT_STATE")
    if project["schema_version"] != 4 or project["plan_revision"] != PLAN:
        fail("PROJECT_STATE schema/revision drifted")
    external = project["external_gates"]
    if not isinstance(external, dict):
        fail("PROJECT_STATE.external_gates must be an object")
    exact(external, EXTERNAL_KEYS, "PROJECT_STATE.external_gates")
    if external.get("main_protection") != (
        "blocked_admin_setting_canonical_contract_incomplete_or_unverified"
    ):
        fail("PROJECT_STATE falsely promotes main protection")
    for name, value in external.items():
        expected = "blocked_upstream" if name == "vendor_firmware_ota" else (
            value if name == "main_protection" else "blocked_external"
        )
        if value != expected:
            fail(f"PROJECT_STATE falsely promotes external gate {name}")

    successor = project["active_successor"]
    if not isinstance(successor, dict):
        fail("PROJECT_STATE.active_successor must be an object")
    exact(successor, SUCCESSOR_KEYS, "PROJECT_STATE.active_successor")
    if successor != {
        "identity_rule": "live_pull_request_head_and_tree",
        "embedded_maturity": "source_implemented",
        "qualification_authority": "live_exact_head_ci_artifact_and_eligible_review_only",
        "inherits_baseline_evidence": False,
        "released": False,
    }:
        fail("PROJECT_STATE active successor is self-promoted or malformed")

    qualified = project["last_qualified_source"]
    if not isinstance(qualified, dict):
        fail("PROJECT_STATE.last_qualified_source must be an object")
    exact(qualified, LAST_KEYS, "PROJECT_STATE.last_qualified_source")
    sha(qualified["commit"], "last-qualified commit", 40)
    sha(qualified["tree"], "last-qualified tree", 40)
    sha(qualified["artifact_zip_sha256"], "last-qualified artifact digest", 64)
    expected = {
        "repository": PIN["repository"], "pull_request": PIN["pull_request"],
        "commit": manifest["source_commit"], "tree": manifest["source_tree"],
        "workflow_run_id": manifest["workflow"]["id"],
        "workflow_run_number": manifest["workflow"]["run_number"],
        "required_jobs": list(JOBS), "artifact_id": manifest["artifact"]["id"],
        "artifact_name": manifest["artifact"]["name"],
        "artifact_zip_sha256": manifest["artifact"]["zip_sha256"],
        "source_gate_checks": "17/17", "independent_artifact_checks": "39/39",
        "code_owner_review_id": manifest["independent_review"]["review_id"],
        "code_owner_reviewer": manifest["independent_review"]["reviewer"],
        "completed": True, "successor_requires_fresh_qualification": True,
        "evidence_manifest": MANIFEST_PATH,
        "evidence_manifest_sha256": MANIFEST_SHA256,
        "retained_artifact": ARCHIVE_REFERENCE,
    }
    for key, value in expected.items():
        if qualified[key] != value:
            category = {
                "commit": "commit substitution", "tree": "commit/tree mismatch",
                "workflow_run_id": "workflow run substitution",
                "artifact_id": "artifact substitution",
                "artifact_zip_sha256": "artifact digest substitution",
                "code_owner_review_id": "review substitution",
            }.get(key, f"{key} drift")
            fail(f"last-qualified {category} detected")
    gate = project["repository_actionable_gate"]
    if not isinstance(gate, dict):
        fail("PROJECT_STATE repository gate must be an object")
    exact(gate, REPOSITORY_GATE_KEYS, "PROJECT_STATE.repository_actionable_gate")
    if gate.get("active_open_gap_ids") != []:
        fail("PROJECT_STATE reports repository-actionable OPEN gaps")
    if tuple(gate.get("required_checks", ())) != JOBS:
        fail("PROJECT_STATE required check set drifted")
    if gate.get("documentation_truth_validator") != (
        "services/qualification/documentation_truth.py"
    ):
        fail("PROJECT_STATE does not register documentation truth")
    status = gate.get("status")
    if not isinstance(status, str) or "source_closed" not in status or (
        "admin_and_external_authority" not in status
    ):
        fail("PROJECT_STATE gate status overclaims")
    authority = project["source_authority"]
    if not isinstance(authority, dict):
        fail("PROJECT_STATE.source_authority must be an object")
    exact(authority, SOURCE_AUTHORITY_KEYS, "PROJECT_STATE.source_authority")
    if authority.get("self_attested_sha_is_authoritative") is not False or authority.get(
        "historical_artifact_does_not_attest_later_push"
    ) is not True:
        fail("PROJECT_STATE source authority permits self/stale evidence")

    if set(implementation) != {
        "schema_version", "parent_gap", "aggregate_status", "plan", "claim_ceiling",
        "slices", "unchanged_authority_owned_gap_ids", "administrative_adoption_gap",
        "implementation_scope", "validation_scope", "source_closure_evidence",
    }:
        fail("HG0087 implementation top-level fields drifted")
    if implementation["aggregate_status"] != "CLOSED_SOURCE":
        fail("HG0087 aggregate status is not CLOSED_SOURCE")
    rows = implementation.get("slices")
    if not isinstance(rows, list):
        fail("HG0087 slices are missing")
    by_name: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            fail("HG0087 contains a malformed slice")
        if row["id"] in by_name:
            fail(f"duplicate HG0087 slice: {row['id']}")
        by_name[row["id"]] = row
    if set(by_name) != SLICES:
        fail("HG0087 slice identity set drifted")
    for name, row in by_name.items():
        if row.get("status") != "CLOSED_SOURCE" or not strings(
            row.get("remaining_external"), f"HG0087 {name}.remaining_external", 1
        ):
            fail(f"HG0087 slice {name} status/external boundary drifted")

    if set(remediation) != {"schema_version", "plan", "status_semantics", "gaps"}:
        fail("remediation ledger top-level fields drifted")
    gaps = remediation.get("gaps")
    if not isinstance(gaps, list):
        fail("remediation ledger lacks gaps")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in gaps:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            fail("remediation ledger contains a malformed gap")
        if row["id"] in by_id:
            fail(f"duplicate remediation gap: {row['id']}")
        by_id[row["id"]] = row
    if by_id.get("HG-0087", {}).get("status") != "CLOSED_SOURCE":
        fail("remediation ledger disagrees on HG-0087")
    if by_id.get("HG-0089", {}).get("status") != "BLOCKED_ADMIN_SETTING":
        fail("remediation ledger falsely promotes HG-0089")
    open_rows = sorted(
        gap_id for gap_id, row in by_id.items() if row.get("status") == "OPEN"
    )
    if open_rows:
        fail(f"repository-actionable remediation rows remain OPEN: {open_rows}")


def validate_maturity(text: str) -> None:
    positions = []
    for heading in STAGE_HEADINGS:
        if text.count(heading) != 1:
            fail(f"maturity heading must occur exactly once: {heading}")
        positions.append(text.index(heading))
    if positions != sorted(positions):
        fail("maturity stage order drifted")
    for expected in (
        "The overall product maturity is bounded by the least mature required axis.",
        "A later source or base change returns the successor to `source_implemented`",
        "Evidence levels never auto-promote a scope outside the identities",
    ):
        phrase(text, expected, "docs/MATURITY_MODEL.md")


def validate(
    root: Path = ROOT,
    *,
    _history_verifier: HistoryVerifier = verify_history,
    _manifest_digest: str = MANIFEST_SHA256,
) -> dict[str, Any]:
    readme = text_file(root, "README.md")
    current = text_file(root, "docs/CURRENT_STATE.md")
    maturity = text_file(root, "docs/MATURITY_MODEL.md")
    roadmap = text_file(root, "docs/development/2026-09-08_PRODUCTIZATION_ROADMAP.md")
    project = object_file(root, "docs/PROJECT_STATE.json")
    implementation = object_file(root, "docs/HG0087_IMPLEMENTATION_STATUS.json")
    remediation = object_file(root, "docs/REMEDIATION_GAP_LEDGER.json")
    manifest = load_manifest(root, _manifest_digest)
    payloads = validate_manifest(root, manifest, _history_verifier)
    validate_project(project, implementation, remediation, manifest)

    phrase(current, f"Canonical plan revision: `{PLAN}`", "docs/CURRENT_STATE.md")
    for label, text in (("README.md", readme), ("docs/CURRENT_STATE.md", current)):
        phrase(text, "HG-0087 is `CLOSED_SOURCE`", label)
        for stale in STALE:
            if stale in text:
                fail(f"{label} contains stale source status: {stale}")
        folded = text.casefold()
        for promotion in FALSE_PROMOTIONS:
            if promotion.casefold() in folded:
                fail(f"{label} contains prohibited successor promotion: {promotion}")
    phrase(
        readme,
        "Any successor commit—including documentation-only changes—must run all seven canonical jobs",
        "README.md",
    )
    phrase(
        current,
        "A later commit must obtain its own complete seven-job result",
        "docs/CURRENT_STATE.md",
    )
    validate_maturity(maturity)
    phrase(roadmap, "Source code, local tests, mocks, screenshots", "productization roadmap")
    return {
        "plan_revision": PLAN,
        "hg0087_status": "CLOSED_SOURCE",
        "hg0087_slices": len(SLICES),
        "repository_actionable_open": 0,
        "hg0089_status": "BLOCKED_ADMIN_SETTING",
        "maturity_stages": len(STAGE_HEADINGS),
        "last_qualified_commit": PIN["source_commit"],
        "required_jobs": len(JOBS),
        "baseline_manifest_sha256": MANIFEST_SHA256,
        "baseline_archive_sha256": PIN["artifact_sha256"],
        "baseline_members": len(payloads),
    }


def main() -> int:
    try:
        result = validate()
    except (DocumentationTruthError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
