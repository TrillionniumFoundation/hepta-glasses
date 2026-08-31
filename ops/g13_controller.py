#!/usr/bin/env python3
"""Single-authority terminal source-convergence controller for Hepta Glasses.

The controller is deliberately fail-closed:
- legacy orchestration runs are cancelled before source selection;
- every source/tree change is qualified on an isolated branch by the repository's
  registered CI workflow;
- only an unchanged expected candidate head may be advanced;
- historical refs are deleted only after their tips are ancestors of the final
  candidate;
- physical, production, vendor, independent-assurance, signing, pilot, rollout,
  rollback, and store gates remain external evidence obligations;
- success and failure both publish durable, machine-readable orphan evidence.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path.cwd()
BUILD = ROOT / "build" / "g13"
TARGET = Path("/tmp/hepta-g13-target")
MIGRATOR = Path("/tmp/hepta-g13-migrate.py")

REPOSITORY = os.environ["GITHUB_REPOSITORY"]
CANDIDATE_BRANCH = "codex/hepta-glasses-gap-closure-g8"
VALIDATION_BRANCH = "codex/hepta-glasses-terminal-validation"
PR_NUMBER = 23
WORKFLOW_ID = 345531045
SELF_BRANCH = "ops/hepta-g13-terminal-source-convergence"
EVIDENCE_BRANCH = "evidence/hepta-g11-final-source-audit"
FAILURE_BRANCH = "evidence/hepta-terminal-source-failure"
CURRENT_RUN_ID = int(os.environ.get("GITHUB_RUN_ID", "0"))

REQUIRED_JOBS = {
    "repository-contracts",
    "flutter",
    "android-native",
    "ios-native",
    "native-sanitizers",
    "secret-and-boundary-scan",
    "source-evidence",
}

EXTERNAL_GAP_IDS = {
    "HG-0015",
    "HG-0016",
    "HG-0017",
    "HG-0018",
    "HG-0019",
    "HG-0020",
}

HISTORICAL_BRANCHES = [
    "bootstrap/hepta-glasses-g7-format",
    "bootstrap/hepta-glasses-g7",
    "codex/hepta-glasses-ai-native-foundation-v1",
    "codex/hepta-glasses-audit-closure-g5",
    "codex/hepta-glasses-g7-synthesis",
    "codex/hepta-glasses-gap-closure-g5",
    "codex/hepta-glasses-gap-closure-g6",
    "codex/hepta-glasses-gap-closure-g7",
    "codex/hepta-glasses-history-diagnostic-g7",
    "codex/hepta-glasses-runtime-hardening-g3",
    "codex/hepta-glasses-source-closure-g4",
    "work/hepta-glasses-gap-closure-g7-staging",
]

SOURCE_RECOVERY_BRANCHES = [
    "codex/hepta-glasses-gap-closure-g10a-validation",
    "codex/hepta-glasses-gap-closure-g9-validation-v2",
    "codex/hepta-glasses-gap-closure-g9-validation",
    "codex/hepta-glasses-gap-closure-g8-validation",
    "work/hepta-glasses-gap-closure-g8-materialize",
]

TEMP_SOURCE_BRANCHES = [
    VALIDATION_BRANCH,
    "codex/hepta-glasses-gap-closure-g10a-validation",
    "codex/hepta-glasses-gap-closure-g9-validation-v2",
    "codex/hepta-glasses-gap-closure-g9-validation",
    "codex/hepta-glasses-gap-closure-g8-validation",
    "work/hepta-glasses-gap-closure-g8-materialize",
    "work/hepta-glasses-gap-closure-g8-diagnostics",
]

OLD_ORCHESTRATION_BRANCHES = [
    "ops/hepta-glasses-g8-source-closure-orchestrator",
    "ops/hepta-g8-terminal-finalizer",
    "ops/hepta-g9-identity-docs-orchestrator",
    "ops/hepta-g9-identity-docs-orchestrator-v2",
    "ops/hepta-g9-dispatch-promote-fallback",
    "ops/hepta-g10-branch-governance",
    "ops/hepta-g10-branch-governance-v2",
    "ops/hepta-g10a-history-ancestry",
    "ops/hepta-g10b-final-ref-cleanup",
    "ops/hepta-g10c-final-authority-cleanup",
    "ops/hepta-g11-final-source-audit",
    "ops/hepta-g11-final-source-audit-v2",
    "ops/hepta-g11-final-source-audit-v3",
    "ops/hepta-g12-evidence-export",
    "ops/hepta-g12-evidence-export-v2",
    "ops/hepta-g12-evidence-export-v3",
]

SOURCE_MARKER = "contracts/history-scan-acknowledgements-v1.json"
PATCH_PAYLOAD = ".github/g8-fix.patch.gz.b64"
MATERIALIZER_WORKFLOW = ".github/workflows/g8-materialize.yml"


class ConvergenceError(RuntimeError):
    """Raised when a truth or promotion gate does not hold."""


@dataclass(frozen=True)
class CiEvidence:
    run_id: int
    run_attempt: int
    branch: str
    head_sha: str
    jobs: dict[str, str]
    artifact_id: int
    artifact_name: str
    artifact_digest: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def set_stage(name: str, **details: Any) -> None:
    payload = {"stage": name, "updated_at": now_iso(), **details}
    write_json(BUILD / "stage.json", payload)
    print(f"::notice::G13 stage: {name}", flush=True)


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        list(command),
        cwd=str(cwd or ROOT),
        env=merged_env,
        input=input_text,
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        if capture:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise ConvergenceError(
            f"command failed ({result.returncode}): {' '.join(command)}"
        )
    return result


def run_logged(command: Sequence[str], name: str, *, cwd: Path) -> None:
    log_path = BUILD / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"::group::{name}", flush=True)
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            handle.write(line)
        code = process.wait()
    print("::endgroup::", flush=True)
    if code != 0:
        raise ConvergenceError(f"qualification command failed ({code}): {name}")


def output(command: Sequence[str], *, cwd: Path | None = None) -> str:
    return run(command, cwd=cwd, capture=True).stdout.strip()


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = run(["git", *args], cwd=cwd, capture=True, check=check)
    return result.stdout.strip()


def api(
    endpoint: str,
    *,
    method: str = "GET",
    fields: dict[str, str] | None = None,
    input_value: Any | None = None,
    check: bool = True,
) -> Any:
    command = ["gh", "api"]
    if method != "GET":
        command.extend(["--method", method])
    command.append(endpoint)
    if fields:
        for key, value in fields.items():
            command.extend(["-f", f"{key}={value}"])
    input_text = None
    if input_value is not None:
        command.extend(["--input", "-"])
        input_text = json.dumps(input_value)
    result = run(command, capture=True, input_text=input_text, check=check)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        if check:
            raise ConvergenceError(f"non-JSON GitHub API response: {endpoint}") from error
        return None


def branch_sha(branch: str) -> str | None:
    value = api(
        f"repos/{REPOSITORY}/branches/{urllib.parse.quote(branch, safe='')}",
        check=False,
    )
    if not isinstance(value, dict):
        return None
    return ((value.get("commit") or {}).get("sha"))


def ref_exists(ref: str, *, cwd: Path = ROOT) -> bool:
    result = run(["git", "show-ref", "--verify", "--quiet", ref], cwd=cwd, check=False)
    return result.returncode == 0


def object_path_exists(ref: str, path: str, *, cwd: Path = ROOT) -> bool:
    result = run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0


def is_ancestor(ancestor: str, descendant: str, *, cwd: Path = ROOT) -> bool:
    result = run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0


def cancel_legacy_orchestration() -> None:
    set_stage("cancel_legacy_orchestration")
    runs = api(f"repos/{REPOSITORY}/actions/runs?per_page=100") or {}
    cancelled: list[dict[str, Any]] = []
    for item in runs.get("workflow_runs", []):
        branch = item.get("head_branch")
        status = item.get("status")
        run_id = int(item.get("id", 0))
        if run_id == CURRENT_RUN_ID:
            continue
        if branch not in set(OLD_ORCHESTRATION_BRANCHES):
            continue
        if status not in {"queued", "in_progress", "waiting", "pending", "requested"}:
            continue
        api(
            f"repos/{REPOSITORY}/actions/runs/{run_id}/cancel",
            method="POST",
            check=False,
        )
        cancelled.append({"id": run_id, "branch": branch, "status": status})
    write_json(BUILD / "cancelled-runs.json", cancelled)
    if cancelled:
        time.sleep(20)

    # Remove obsolete orchestration authority after preserving run records.
    for branch in OLD_ORCHESTRATION_BRANCHES:
        if branch_sha(branch) is None:
            continue
        run(["git", "push", "origin", "--delete", branch], check=False)


def fetch_all_refs() -> None:
    run(
        [
            "git",
            "fetch",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            "+refs/tags/*:refs/tags/*",
            "--prune",
            "--no-recurse-submodules",
        ]
    )


def preserve_migrator() -> None:
    source = ROOT / "ops" / "g13_migrate.py"
    if not source.is_file():
        raise ConvergenceError("G13 migration program is missing")
    shutil.copy2(source, MIGRATOR)
    MIGRATOR.chmod(0o755)


def choose_source_base(current_sha: str) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []
    references = [(CANDIDATE_BRANCH, f"refs/remotes/origin/{CANDIDATE_BRANCH}")]
    references.extend((branch, f"refs/remotes/origin/{branch}") for branch in SOURCE_RECOVERY_BRANCHES)

    for label, ref in references:
        if not ref_exists(ref):
            continue
        sha = git("rev-parse", ref)
        if not is_ancestor(current_sha, sha):
            continue
        has_marker = object_path_exists(ref, SOURCE_MARKER)
        has_identity = object_path_exists(ref, "contracts/product-identity-v1.json")
        has_patch = object_path_exists(ref, PATCH_PAYLOAD)
        workflows_ok = False
        try:
            tree = git("ls-tree", "--name-only", f"{ref}:.github/workflows")
            workflows_ok = tree.splitlines() == ["ci.yml"]
        except ConvergenceError:
            workflows_ok = False
        score = (
            (200 if has_identity else 0)
            + (100 if has_marker else 0)
            + (25 if workflows_ok else 0)
            + (10 if has_patch else 0)
        )
        timestamp = int(git("show", "-s", "--format=%ct", sha))
        candidates.append((score, timestamp, label, sha))

    if not candidates:
        raise ConvergenceError("no descendant source base is available")
    candidates.sort(reverse=True)
    _, _, label, sha = candidates[0]
    write_json(
        BUILD / "source-base-selection.json",
        {
            "current_candidate": current_sha,
            "selected_branch": label,
            "selected_sha": sha,
            "candidates": [
                {"score": score, "timestamp": ts, "branch": name, "sha": value}
                for score, ts, name, value in sorted(candidates, reverse=True)
            ],
        },
    )
    return label, sha


def find_preserved_history_acknowledgements() -> bytes | None:
    priority = [
        f"refs/remotes/origin/codex/hepta-glasses-gap-closure-g8-validation",
        f"refs/remotes/origin/work/hepta-glasses-gap-closure-g8-materialize",
        f"refs/remotes/origin/{CANDIDATE_BRANCH}",
    ]
    for ref in priority:
        if not ref_exists(ref) or not object_path_exists(ref, SOURCE_MARKER):
            continue
        result = run(["git", "show", f"{ref}:{SOURCE_MARKER}"], capture=True)
        data = result.stdout.encode("utf-8")
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return data
    return None


def apply_g8_patch_if_needed(worktree: Path) -> None:
    marker = worktree / SOURCE_MARKER
    if marker.is_file():
        return

    payload_text: str | None = None
    local_payload = worktree / PATCH_PAYLOAD
    if local_payload.is_file():
        payload_text = local_payload.read_text(encoding="utf-8")
    else:
        remote = "refs/remotes/origin/work/hepta-glasses-gap-closure-g8-materialize"
        if ref_exists(remote) and object_path_exists(remote, PATCH_PAYLOAD):
            payload_text = git("show", f"{remote}:{PATCH_PAYLOAD}")

    if not payload_text:
        raise ConvergenceError("G8 source marker is absent and no exact patch payload exists")

    try:
        compressed = base64.b64decode("".join(payload_text.split()), validate=True)
        patch = gzip.decompress(compressed)
    except Exception as error:  # noqa: BLE001 - surfaced as a gate failure
        raise ConvergenceError("G8 patch payload failed integrity decoding") from error

    patch_path = BUILD / "g8-recovery.patch"
    patch_path.write_bytes(patch)
    run(["git", "apply", "--check", str(patch_path)], cwd=worktree)
    run(["git", "apply", str(patch_path)], cwd=worktree)
    if not marker.is_file():
        raise ConvergenceError("G8 patch applied without producing its source marker")


def prepare_target(current_sha: str) -> tuple[str, str]:
    set_stage("prepare_target", current_candidate=current_sha)
    fetch_all_refs()
    selected_branch, selected_sha = choose_source_base(current_sha)
    preserved_ack = find_preserved_history_acknowledgements()

    if TARGET.exists():
        run(["git", "worktree", "remove", "--force", str(TARGET)], check=False)
        shutil.rmtree(TARGET, ignore_errors=True)
    run(["git", "worktree", "add", "--force", "--detach", str(TARGET), selected_sha])

    apply_g8_patch_if_needed(TARGET)
    for relative in (PATCH_PAYLOAD, MATERIALIZER_WORKFLOW):
        path = TARGET / relative
        if path.exists():
            path.unlink()

    if preserved_ack is not None:
        target_ack = TARGET / SOURCE_MARKER
        target_ack.parent.mkdir(parents=True, exist_ok=True)
        target_ack.write_bytes(preserved_ack)

    run([sys.executable, str(MIGRATOR), str(TARGET)], cwd=TARGET)

    workflows = sorted(
        path.name for path in (TARGET / ".github" / "workflows").glob("*") if path.is_file()
    )
    if workflows != ["ci.yml"]:
        raise ConvergenceError(f"candidate workflow authority is not singular: {workflows}")

    qualification = [
        (["flutter", "pub", "get"], "flutter-pub-get"),
        (["dart", "format", "lib", "test"], "dart-format"),
        ([sys.executable, "tools/validate_repository.py"], "repository-contracts"),
        ([sys.executable, "tools/validate_product_identity.py"], "product-identity"),
        (
            [sys.executable, "-m", "unittest", "discover", "-s", "services", "-p", "test_*.py"],
            "service-tests",
        ),
        (
            [sys.executable, "-m", "unittest", "discover", "-s", "adapters", "-p", "test_*.py"],
            "adapter-tests",
        ),
        ([sys.executable, "-m", "compileall", "-q", "services", "adapters", "tools"], "python-compileall"),
        (["flutter", "analyze", "--no-fatal-infos"], "flutter-analyze"),
        (["flutter", "test"], "flutter-test"),
        (["flutter", "build", "apk", "--debug"], "android-debug-build"),
        (["./gradlew", "testDebugUnitTest"], "android-unit-tests"),
    ]
    for command, name in qualification:
        cwd = TARGET / "android" if command[0] == "./gradlew" else TARGET
        run_logged(command, name, cwd=cwd)

    run(["git", "diff", "--check"], cwd=TARGET)
    run(["git", "config", "user.name", "hepta-g13-source[bot]"], cwd=TARGET)
    run(
        [
            "git",
            "config",
            "user.email",
            "hepta-g13-source[bot]@users.noreply.github.com",
        ],
        cwd=TARGET,
    )
    run(["git", "add", "-A"], cwd=TARGET)
    if run(["git", "diff", "--cached", "--quiet"], cwd=TARGET, check=False).returncode != 0:
        run(
            [
                "git",
                "commit",
                "-s",
                "-m",
                "fix(g13): close terminal source and identity blockers",
            ],
            cwd=TARGET,
        )
    target_sha = git("rev-parse", "HEAD", cwd=TARGET)
    if not is_ancestor(current_sha, target_sha, cwd=TARGET):
        raise ConvergenceError("prepared source commit is not a fast-forward descendant")
    write_json(
        BUILD / "prepared-target.json",
        {
            "candidate_base": current_sha,
            "selected_branch": selected_branch,
            "selected_sha": selected_sha,
            "prepared_sha": target_sha,
            "tree_sha": git("rev-parse", f"{target_sha}^{{tree}}", cwd=TARGET),
            "local_qualification": "success",
        },
    )
    return current_sha, target_sha


def push_ref(sha: str, branch: str, *, force: bool = False) -> None:
    command = ["git", "push"]
    if force:
        command.append("--force")
    command.extend(["origin", f"{sha}:refs/heads/{branch}"])
    run(command, cwd=TARGET)


def download_failed_ci(run_id: int, label: str) -> None:
    directory = BUILD / "failed-ci" / f"{label}-{run_id}"
    directory.mkdir(parents=True, exist_ok=True)
    run_data = api(f"repos/{REPOSITORY}/actions/runs/{run_id}", check=False)
    jobs_data = api(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100",
        check=False,
    )
    if run_data is not None:
        write_json(directory / "run.json", run_data)
    if jobs_data is not None:
        write_json(directory / "jobs.json", jobs_data)
        for job in jobs_data.get("jobs", []):
            if job.get("conclusion") == "success":
                continue
            job_id = int(job.get("id", 0))
            if not job_id:
                continue
            safe = "".join(
                character if character.isalnum() or character in "._-" else "_"
                for character in str(job.get("name", "job"))
            )
            path = directory / f"{job_id}-{safe}.log"
            command = [
                "gh",
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{REPOSITORY}/actions/jobs/{job_id}/logs",
            ]
            with path.open("wb") as handle:
                subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, check=False)


def validate_ci_run(run_id: int, branch: str, sha: str) -> CiEvidence:
    run_data = api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if run_data.get("head_sha") != sha:
        raise ConvergenceError("CI run head identity mismatch")
    if run_data.get("status") != "completed" or run_data.get("conclusion") != "success":
        raise ConvergenceError("CI run is not successfully completed")

    jobs_data = api(f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = {
        str(item.get("name")): str(item.get("conclusion"))
        for item in jobs_data.get("jobs", [])
        if item.get("name") in REQUIRED_JOBS
    }
    if set(jobs) != REQUIRED_JOBS or set(jobs.values()) != {"success"}:
        raise ConvergenceError(f"required CI job set is incomplete or unsuccessful: {jobs}")

    artifacts_data = api(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"
    )
    expected_name = f"hepta-source-evidence-{sha}"
    matching = [
        item
        for item in artifacts_data.get("artifacts", [])
        if item.get("name") == expected_name and not item.get("expired")
    ]
    if not matching:
        raise ConvergenceError("exact-head Source Evidence artifact is missing")
    artifact = matching[-1]

    evidence = CiEvidence(
        run_id=run_id,
        run_attempt=int(run_data.get("run_attempt", 1)),
        branch=branch,
        head_sha=sha,
        jobs=jobs,
        artifact_id=int(artifact["id"]),
        artifact_name=expected_name,
        artifact_digest=artifact.get("digest"),
    )
    write_json(
        BUILD / "ci" / f"{branch.replace('/', '_')}-{sha}.json",
        {
            "run": run_data,
            "jobs": jobs_data,
            "artifacts": artifacts_data,
            "normalized": evidence.__dict__,
        },
    )
    return evidence


def wait_for_ci(branch: str, sha: str, label: str, timeout_seconds: int = 6000) -> CiEvidence:
    set_stage("wait_for_ci", branch=branch, sha=sha, label=label)
    encoded_branch = urllib.parse.quote(branch, safe="")
    start = time.monotonic()
    dispatched = False
    rerun_run_id: int | None = None

    while time.monotonic() - start < timeout_seconds:
        data = api(
            f"repos/{REPOSITORY}/actions/runs?branch={encoded_branch}&per_page=100"
        ) or {}
        runs = [
            item
            for item in data.get("workflow_runs", [])
            if int(item.get("workflow_id", 0)) == WORKFLOW_ID
            and item.get("head_sha") == sha
        ]
        runs.sort(key=lambda item: item.get("created_at", ""), reverse=True)

        for item in runs:
            if item.get("status") == "completed" and item.get("conclusion") == "success":
                return validate_ci_run(int(item["id"]), branch, sha)

        active = [
            item
            for item in runs
            if item.get("status") in {"queued", "in_progress", "waiting", "pending", "requested"}
        ]
        if active:
            time.sleep(20)
            continue

        failures = [item for item in runs if item.get("status") == "completed"]
        if failures:
            failed = failures[0]
            failed_id = int(failed["id"])
            if rerun_run_id != failed_id:
                api(
                    f"repos/{REPOSITORY}/actions/runs/{failed_id}/rerun-failed-jobs",
                    method="POST",
                    check=False,
                )
                rerun_run_id = failed_id
                time.sleep(20)
                continue
            download_failed_ci(failed_id, label)
            raise ConvergenceError(
                f"exact-head CI failed after one failed-job rerun: {failed_id}"
            )

        if not dispatched and time.monotonic() - start >= 15:
            api(
                f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW_ID}/dispatches",
                method="POST",
                fields={"ref": branch},
            )
            dispatched = True
            time.sleep(20)
            continue

        time.sleep(10)

    raise ConvergenceError(f"exact-head CI timed out for {branch}@{sha}")


def promote(expected_old: str, new_sha: str) -> None:
    set_stage("promote_candidate", expected_old=expected_old, new_sha=new_sha)
    current = branch_sha(CANDIDATE_BRANCH)
    if current not in {expected_old, new_sha}:
        raise ConvergenceError(
            f"candidate moved independently: expected {expected_old}, observed {current}"
        )
    if current != new_sha:
        push_ref(new_sha, CANDIDATE_BRANCH)
    observed = branch_sha(CANDIDATE_BRANCH)
    if observed != new_sha:
        raise ConvergenceError("candidate ref did not advance to the qualified commit")


def existing_remote_ref(branch: str) -> str | None:
    ref = f"refs/remotes/origin/{branch}"
    if not ref_exists(ref):
        return None
    return git("rev-parse", ref)


def create_ancestry_commit(base_sha: str) -> tuple[str, list[dict[str, str]]]:
    set_stage("converge_history_ancestry", base_sha=base_sha)
    fetch_all_refs()
    missing: list[dict[str, str]] = []
    for branch in HISTORICAL_BRANCHES:
        tip = existing_remote_ref(branch)
        if tip is None or is_ancestor(tip, base_sha):
            continue
        missing.append({"branch": branch, "sha": tip})

    if not missing:
        write_json(BUILD / "history-ancestry.json", {"changed": False, "base": base_sha})
        return base_sha, []

    tips = [item["sha"] for item in missing]
    minimal: list[str] = []
    for candidate in tips:
        if any(
            candidate != other and is_ancestor(candidate, other)
            for other in tips
        ):
            continue
        minimal.append(candidate)

    tree_sha = git("rev-parse", f"{base_sha}^{{tree}}", cwd=TARGET)
    command = ["git", "commit-tree", tree_sha, "-p", base_sha]
    for parent in minimal:
        command.extend(["-p", parent])
    message = (
        "chore(g13): preserve all candidate histories without tree drift\n\n"
        "Signed-off-by: hepta-g13-history[bot] "
        "<hepta-g13-history[bot]@users.noreply.github.com>\n"
    )
    env = {
        "GIT_AUTHOR_NAME": "hepta-g13-history[bot]",
        "GIT_AUTHOR_EMAIL": "hepta-g13-history[bot]@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "hepta-g13-history[bot]",
        "GIT_COMMITTER_EMAIL": "hepta-g13-history[bot]@users.noreply.github.com",
    }
    result = run(command, cwd=TARGET, capture=True, input_text=message, env=env)
    merge_sha = result.stdout.strip()
    if git("rev-parse", f"{merge_sha}^{{tree}}", cwd=TARGET) != tree_sha:
        raise ConvergenceError("unchanged-tree ancestry commit changed the tree")
    run(["git", "diff", "--exit-code", base_sha, merge_sha], cwd=TARGET)
    for item in missing:
        if not is_ancestor(item["sha"], merge_sha, cwd=TARGET):
            raise ConvergenceError(f"history tip was not absorbed: {item}")
    write_json(
        BUILD / "history-ancestry.json",
        {
            "changed": True,
            "base": base_sha,
            "commit": merge_sha,
            "tree": tree_sha,
            "missing_tips": missing,
            "minimal_additional_parents": minimal,
        },
    )
    return merge_sha, missing


def delete_branch(branch: str, *, check: bool = True) -> bool:
    if branch_sha(branch) is None:
        return False
    result = run(
        ["git", "push", "origin", "--delete", branch],
        cwd=TARGET,
        check=False,
        capture=True,
    )
    if result.returncode != 0 and check:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise ConvergenceError(f"failed to delete branch: {branch}")
    return result.returncode == 0


def cleanup_source_authority(final_sha: str) -> dict[str, Any]:
    set_stage("cleanup_source_authority", final_sha=final_sha)
    fetch_all_refs()
    deleted_historical: list[dict[str, str]] = []
    absent_historical: list[str] = []
    for branch in HISTORICAL_BRANCHES:
        tip = existing_remote_ref(branch)
        if tip is None:
            absent_historical.append(branch)
            continue
        if not is_ancestor(tip, final_sha):
            raise ConvergenceError(f"ref cleanup refused unabsorbed history: {branch}@{tip}")
        if delete_branch(branch):
            deleted_historical.append({"branch": branch, "tip": tip})

    deleted_temporary: list[dict[str, str]] = []
    for branch in TEMP_SOURCE_BRANCHES:
        tip = branch_sha(branch)
        if tip is None:
            continue
        # Temporary validation and diagnostics refs are not release history, but
        # equality/ancestry is recorded whenever it holds.
        relation = "equal" if tip == final_sha else "ancestor" if is_ancestor(tip, final_sha) else "ephemeral"
        if delete_branch(branch):
            deleted_temporary.append({"branch": branch, "tip": tip, "relation": relation})

    for branch in OLD_ORCHESTRATION_BRANCHES:
        delete_branch(branch, check=False)

    fetch_all_refs()
    active_candidates: list[str] = []
    branches = api(f"repos/{REPOSITORY}/branches?per_page=100") or []
    for item in branches:
        name = str(item.get("name"))
        if name.startswith("codex/hepta-glasses-gap-closure-g"):
            active_candidates.append(name)
    active_candidates.sort()
    if active_candidates != [CANDIDATE_BRANCH]:
        raise ConvergenceError(
            f"source candidate authority is not unique: {active_candidates}"
        )

    workflow_listing = api(
        f"repos/{REPOSITORY}/contents/.github/workflows?ref={final_sha}"
    ) or []
    workflow_names = sorted(item.get("name") for item in workflow_listing)
    if workflow_names != ["ci.yml"]:
        raise ConvergenceError(f"candidate workflow authority drift: {workflow_names}")

    result = {
        "deleted_historical": deleted_historical,
        "already_absent_historical": absent_historical,
        "deleted_temporary": deleted_temporary,
        "active_candidate_branches": active_candidates,
        "candidate_workflow_files": workflow_names,
    }
    write_json(BUILD / "source-authority-cleanup.json", result)
    return result


def detached_source_revalidation(final_sha: str) -> None:
    set_stage("detached_source_revalidation", final_sha=final_sha)
    run(["git", "checkout", "--detach", final_sha], cwd=TARGET)
    commands = [
        ([sys.executable, "tools/validate_repository.py"], "terminal-repository-contracts"),
        ([sys.executable, "tools/validate_product_identity.py"], "terminal-product-identity"),
        (
            [sys.executable, "-m", "unittest", "discover", "-s", "services", "-p", "test_*.py"],
            "terminal-service-tests",
        ),
        (
            [sys.executable, "-m", "unittest", "discover", "-s", "adapters", "-p", "test_*.py"],
            "terminal-adapter-tests",
        ),
        ([sys.executable, "-m", "compileall", "-q", "services", "adapters", "tools"], "terminal-compileall"),
    ]
    for command, name in commands:
        run_logged(command, name, cwd=TARGET)
    run(["git", "diff", "--exit-code"], cwd=TARGET)


def collect_gap_records(value: Any, records: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and isinstance(value.get("status"), str):
            records.append(value)
        for child in value.values():
            collect_gap_records(child, records)
    elif isinstance(value, list):
        for child in value:
            collect_gap_records(child, records)


def audit_gap_ledger() -> dict[str, Any]:
    data = json.loads((TARGET / "docs" / "GAP_LEDGER.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    collect_gap_records(data, records)
    by_id = {item["id"]: item for item in records}
    external_words = (
        "EXTERNAL",
        "DEVICE",
        "UPSTREAM",
        "VENDOR",
        "ADMIN",
        "REVIEW",
        "PRODUCTION",
        "SIGNING",
        "PILOT",
        "STORE",
        "DEPLOY",
        "BLOCKED",
    )
    closed_words = ("CLOSED", "VERIFIED", "RELEASED", "SUPERSEDED", "REJECTED")
    closed: list[dict[str, str]] = []
    external: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []

    for identifier in sorted(by_id):
        item = by_id[identifier]
        status = str(item["status"])
        upper = status.upper()
        row = {
            "id": identifier,
            "status": status,
            "title": str(item.get("title") or item.get("summary") or ""),
            "owner": str(item.get("owner") or item.get("responsible") or ""),
        }
        if identifier in EXTERNAL_GAP_IDS or any(word in upper for word in external_words):
            external.append(row)
        elif any(word in upper for word in closed_words):
            closed.append(row)
        else:
            unresolved.append(row)

    missing_external = sorted(EXTERNAL_GAP_IDS - set(by_id))
    report = {
        "schema_version": 4,
        "record_count": len(by_id),
        "closed_or_superseded": closed,
        "blocked_external": external,
        "repository_actionable_unresolved": unresolved,
        "missing_required_external_records": missing_external,
    }
    write_json(BUILD / "gap-audit.json", report)
    if unresolved:
        raise ConvergenceError(
            "repository-actionable or unknown Gap Ledger states remain: "
            + ", ".join(item["id"] for item in unresolved)
        )
    if missing_external:
        raise ConvergenceError(
            "required external evidence records are missing: " + ", ".join(missing_external)
        )
    return report


def mark_pr_ready_and_request_review(final_sha: str) -> None:
    pr = api(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if ((pr.get("head") or {}).get("sha")) != final_sha:
        raise ConvergenceError("PR head moved before review handoff")
    if pr.get("merged_at") is not None:
        raise ConvergenceError("PR was merged before terminal source audit")
    if pr.get("draft"):
        node_id = pr.get("node_id")
        query = (
            "mutation($id:ID!){markPullRequestReadyForReview("
            "input:{pullRequestId:$id}){pullRequest{isDraft}}}"
        )
        run(
            ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"id={node_id}"],
            check=False,
        )
    api(
        f"repos/{REPOSITORY}/pulls/{PR_NUMBER}/requested_reviewers",
        method="POST",
        input_value={"reviewers": ["ProfHepta"]},
        check=False,
    )


def governance_observation() -> dict[str, Any]:
    main_branch = api(f"repos/{REPOSITORY}/branches/main", check=False)
    protection = api(f"repos/{REPOSITORY}/branches/main/protection", check=False)
    rulesets = api(
        f"repos/{REPOSITORY}/rulesets?includes_parents=true&per_page=100",
        check=False,
    )
    result = {
        "main_branch": main_branch,
        "main_protection": protection,
        "main_protection_readable": protection is not None,
        "rulesets": rulesets if rulesets is not None else [],
        "claim": (
            "observed_api_configuration"
            if protection is not None
            else "admin_evidence_not_readable_by_workflow_token"
        ),
    }
    write_json(BUILD / "governance-observation.json", result)
    return result


def current_branches() -> list[dict[str, Any]]:
    value = api(f"repos/{REPOSITORY}/branches?per_page=100")
    if not isinstance(value, list):
        raise ConvergenceError("failed to enumerate branches")
    return value


def build_terminal_report(
    final_sha: str,
    ci: CiEvidence,
    cleanup: dict[str, Any],
    gap: dict[str, Any],
    history: list[dict[str, str]],
) -> dict[str, Any]:
    set_stage("build_terminal_report", final_sha=final_sha)
    mark_pr_ready_and_request_review(final_sha)
    pr = api(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    reviews = api(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}/reviews?per_page=100") or []
    requested = api(
        f"repos/{REPOSITORY}/pulls/{PR_NUMBER}/requested_reviewers",
        check=False,
    ) or {}
    governance = governance_observation()
    branches = current_branches()

    author = ((pr.get("user") or {}).get("login"))
    approvals = [item for item in reviews if item.get("state") == "APPROVED"]
    self_approvals = [
        item for item in approvals if ((item.get("user") or {}).get("login")) == author
    ]
    independent = [
        item
        for item in approvals
        if ((item.get("user") or {}).get("login")) not in {None, author}
    ]
    artifact = api(f"repos/{REPOSITORY}/actions/artifacts/{ci.artifact_id}")
    commit = api(f"repos/{REPOSITORY}/commits/{final_sha}")
    tree_sha = (((commit.get("commit") or {}).get("tree") or {}).get("sha"))

    active_candidates = sorted(
        item["name"]
        for item in branches
        if str(item.get("name", "")).startswith("codex/hepta-glasses-gap-closure-g")
    )
    report = {
        "schema_version": 4,
        "generated_at": now_iso(),
        "repository": REPOSITORY,
        "candidate_branch": CANDIDATE_BRANCH,
        "candidate_sha": final_sha,
        "candidate_tree_sha": tree_sha,
        "pull_request": PR_NUMBER,
        "pull_request_author": author,
        "pull_request_state": pr.get("state"),
        "pull_request_draft": pr.get("draft"),
        "merged": pr.get("merged_at") is not None,
        "ci_run_id": ci.run_id,
        "ci_run_attempt": ci.run_attempt,
        "source_evidence_artifact_id": ci.artifact_id,
        "source_evidence_artifact_name": ci.artifact_name,
        "source_evidence_artifact_digest": artifact.get("digest") or ci.artifact_digest,
        "required_jobs": ci.jobs,
        "local_source_qualification": "success",
        "source_contracts_reverified_from_detached_head": True,
        "current_workflow_files": cleanup["candidate_workflow_files"],
        "active_candidate_branches": active_candidates,
        "historical_ancestry_added": history,
        "source_authority_cleanup": cleanup,
        "repository_actionable_unresolved": gap["repository_actionable_unresolved"],
        "blocked_external": gap["blocked_external"],
        "missing_required_external_records": gap["missing_required_external_records"],
        "self_approval_detected": bool(self_approvals),
        "self_approval_records": [
            {
                "user": ((item.get("user") or {}).get("login")),
                "commit_id": item.get("commit_id"),
            }
            for item in self_approvals
        ],
        "independent_approval_records": [
            {
                "user": ((item.get("user") or {}).get("login")),
                "commit_id": item.get("commit_id"),
            }
            for item in independent
        ],
        "requested_reviewers": [
            item.get("login") for item in requested.get("users", [])
        ],
        "governance_observation": {
            "main_protection_readable": governance["main_protection_readable"],
            "claim": governance["claim"],
            "main_protected_flag": (
                governance["main_branch"].get("protected")
                if isinstance(governance["main_branch"], dict)
                else None
            ),
            "ruleset_count": len(governance["rulesets"]),
        },
        "claim_ceiling": "source_and_exact_head_ci_only",
        "product_release_authorized": False,
    }

    if report["repository_actionable_unresolved"]:
        raise ConvergenceError("terminal report contains unresolved source gaps")
    if report["missing_required_external_records"]:
        raise ConvergenceError("terminal report is missing external-gate truth")
    if set(report["required_jobs"]) != REQUIRED_JOBS:
        raise ConvergenceError("terminal report required-job set is incomplete")
    if set(report["required_jobs"].values()) != {"success"}:
        raise ConvergenceError("terminal report includes unsuccessful required jobs")
    if report["current_workflow_files"] != ["ci.yml"]:
        raise ConvergenceError("terminal report workflow authority is not singular")
    if report["active_candidate_branches"] != [CANDIDATE_BRANCH]:
        raise ConvergenceError("terminal report source authority is not unique")
    if report["merged"]:
        raise ConvergenceError("terminal report observed premature merge")
    if report["self_approval_detected"]:
        raise ConvergenceError("terminal report observed self-approval")

    write_json(BUILD / "final-source-audit.json", report)
    encoded = (BUILD / "final-source-audit.json").read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    (BUILD / "final-source-audit.sha256").write_text(
        f"{digest}  final-source-audit.json\n",
        encoding="utf-8",
    )
    return report


def create_orphan_commit(files: dict[str, bytes], message: str) -> str:
    entries: list[str] = []
    for name, data in sorted(files.items()):
        result = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=str(ROOT),
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        blob = result.stdout.decode().strip()
        entries.append(f"100644 blob {blob}\t{name}\n")
    tree = output(["git", "mktree"], cwd=ROOT) if False else None
    tree_result = subprocess.run(
        ["git", "mktree"],
        cwd=str(ROOT),
        input="".join(entries),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    tree_sha = tree_result.stdout.strip()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "hepta-g13-evidence[bot]",
            "GIT_AUTHOR_EMAIL": "hepta-g13-evidence[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "hepta-g13-evidence[bot]",
            "GIT_COMMITTER_EMAIL": "hepta-g13-evidence[bot]@users.noreply.github.com",
        }
    )
    signed_message = (
        f"{message}\n\nSigned-off-by: hepta-g13-evidence[bot] "
        "<hepta-g13-evidence[bot]@users.noreply.github.com>\n"
    )
    result = subprocess.run(
        ["git", "commit-tree", tree_sha],
        cwd=str(ROOT),
        env=env,
        input=signed_message,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def publish_success(report: dict[str, Any]) -> str:
    set_stage("publish_terminal_evidence", final_sha=report["candidate_sha"])
    readme = f"""# Hepta Glasses terminal source-audit evidence — schema v4

This orphan branch is a persistent evidence surface, not a source or release branch.

- candidate SHA: `{report['candidate_sha']}`
- candidate tree: `{report['candidate_tree_sha']}`
- exact-head CI run: `{report['ci_run_id']}`
- Source Evidence artifact ID: `{report['source_evidence_artifact_id']}`
- terminal schema: `4`
- repository-actionable unresolved entries: `0`

Verify with:

`sha256sum -c final-source-audit.sha256`

The claim ceiling is source and exact-head CI only. Physical-device, production,
vendor, independent-assurance, signing, pilot, rollout, rollback, and store gates
remain external until their own evidence exists.
"""
    files = {
        "README.md": readme.encode("utf-8"),
        "final-source-audit.json": (BUILD / "final-source-audit.json").read_bytes(),
        "final-source-audit.sha256": (BUILD / "final-source-audit.sha256").read_bytes(),
    }
    commit = create_orphan_commit(
        files,
        f"evidence: publish schema-v4 terminal audit for {report['candidate_sha']}",
    )
    run(
        ["git", "push", "--force", "origin", f"{commit}:refs/heads/{EVIDENCE_BRANCH}"]
    )

    content = api(
        f"repos/{REPOSITORY}/contents/final-source-audit.json?ref={urllib.parse.quote(EVIDENCE_BRANCH, safe='')}"
    )
    published = base64.b64decode("".join(str(content["content"]).split()))
    if published != files["final-source-audit.json"]:
        raise ConvergenceError("published terminal audit bytes differ from source")
    digest_content = api(
        f"repos/{REPOSITORY}/contents/final-source-audit.sha256?ref={urllib.parse.quote(EVIDENCE_BRANCH, safe='')}"
    )
    published_digest = base64.b64decode(
        "".join(str(digest_content["content"]).split())
    )
    if published_digest != files["final-source-audit.sha256"]:
        raise ConvergenceError("published terminal audit digest differs from source")

    delete_branch(FAILURE_BRANCH, check=False)
    (BUILD / "evidence-commit.txt").write_text(commit + "\n", encoding="utf-8")
    return commit


def add_pr_comment(body: str) -> None:
    api(
        f"repos/{REPOSITORY}/issues/{PR_NUMBER}/comments",
        method="POST",
        fields={"body": body},
        check=False,
    )


def publish_pr_success(report: dict[str, Any], evidence_commit: str) -> None:
    external_ids = ", ".join(item["id"] for item in report["blocked_external"])
    independent_count = len(report["independent_approval_records"])
    body = f"""## G13 terminal repository-source convergence passed

- exact candidate: `{report['candidate_sha']}`
- candidate tree: `{report['candidate_tree_sha']}`
- official exact-head CI: `{report['ci_run_id']}`
- required jobs: `7/7` successful
- Source Evidence artifact: `{report['source_evidence_artifact_id']}`
- current workflow authority: `ci.yml` only
- active source candidates: `1`
- repository-actionable unresolved Gap Ledger entries: `0`
- self-approval detected: `false`
- independent approvals currently observed: `{independent_count}`
- persistent evidence commit: `{evidence_commit}`
- persistent evidence branch: `{EVIDENCE_BRANCH}`
- external evidence gates preserved: {external_ids}

The terminal audit was regenerated from the detached exact Head and re-read
byte-for-byte after publication. No self-approval, self-merge, or promotion of
physical/production/vendor/independent evidence was performed.
"""
    add_pr_comment(body)


def publish_failure(error: BaseException) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    stage = {}
    if (BUILD / "stage.json").exists():
        try:
            stage = json.loads((BUILD / "stage.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            stage = {"stage": "unreadable"}
    candidate = branch_sha(CANDIDATE_BRANCH)
    pr = api(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}", check=False)
    failure = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "repository": REPOSITORY,
        "controller_run_id": CURRENT_RUN_ID,
        "controller_branch": SELF_BRANCH,
        "stage": stage,
        "candidate_sha": candidate,
        "pull_request_head": (((pr or {}).get("head") or {}).get("sha")),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
        "claim": "terminal_source_convergence_failed",
    }
    write_json(BUILD / "failure.json", failure)

    files: dict[str, bytes] = {
        "failure.json": (BUILD / "failure.json").read_bytes(),
        "README.md": (
            "# Hepta Glasses terminal source-convergence failure\n\n"
            "This orphan branch records the latest fail-closed G13 controller state.\n"
            f"\n- run: `{CURRENT_RUN_ID}`\n"
            f"- stage: `{stage.get('stage', 'unknown')}`\n"
            f"- candidate: `{candidate}`\n"
            "\nNo failed candidate was promoted by this evidence.\n"
        ).encode("utf-8"),
    }
    log_files = sorted((BUILD / "logs").glob("*.log")) if (BUILD / "logs").exists() else []
    for path in log_files[-5:]:
        data = path.read_bytes()
        files[f"logs/{path.name}"] = data[-200_000:]
    failed_ci = sorted((BUILD / "failed-ci").rglob("*.json")) if (BUILD / "failed-ci").exists() else []
    for path in failed_ci[-6:]:
        files[f"failed-ci/{path.name}"] = path.read_bytes()

    try:
        commit = create_orphan_commit(
            files,
            f"evidence: record G13 failure at {stage.get('stage', 'unknown')}",
        )
        run(
            ["git", "push", "--force", "origin", f"{commit}:refs/heads/{FAILURE_BRANCH}"],
            check=False,
        )
        add_pr_comment(
            "## G13 terminal convergence stopped fail-closed\n\n"
            f"- controller run: `{CURRENT_RUN_ID}`\n"
            f"- stage: `{stage.get('stage', 'unknown')}`\n"
            f"- candidate remained: `{candidate}`\n"
            f"- persistent failure evidence: `{FAILURE_BRANCH}`\n\n"
            "No failed validation result was promoted."
        )
    except Exception as publish_error:  # noqa: BLE001
        print(f"::error::failed to publish failure evidence: {publish_error}")


def cleanup_orchestration_refs() -> None:
    set_stage("cleanup_orchestration_refs")
    for branch in [*OLD_ORCHESTRATION_BRANCHES, SELF_BRANCH]:
        delete_branch(branch, check=False)


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    preserve_migrator()
    try:
        cancel_legacy_orchestration()
        fetch_all_refs()
        current_sha = branch_sha(CANDIDATE_BRANCH)
        if not current_sha:
            raise ConvergenceError("canonical candidate branch is missing")
        pr = api(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
        if ((pr.get("head") or {}).get("sha")) != current_sha:
            raise ConvergenceError("PR head and candidate branch are not identical")
        if pr.get("merged_at") is not None:
            raise ConvergenceError("PR is already merged before terminal convergence")

        expected_base, prepared_sha = prepare_target(current_sha)
        set_stage("push_source_validation", prepared_sha=prepared_sha)
        push_ref(prepared_sha, VALIDATION_BRANCH, force=True)
        source_validation = wait_for_ci(
            VALIDATION_BRANCH,
            prepared_sha,
            "source-validation",
        )
        promote(expected_base, prepared_sha)

        ancestry_sha, history_added = create_ancestry_commit(prepared_sha)
        if ancestry_sha != prepared_sha:
            set_stage("push_ancestry_validation", ancestry_sha=ancestry_sha)
            push_ref(ancestry_sha, VALIDATION_BRANCH, force=True)
            wait_for_ci(
                VALIDATION_BRANCH,
                ancestry_sha,
                "ancestry-validation",
            )
            promote(prepared_sha, ancestry_sha)

        final_sha = ancestry_sha
        final_ci = wait_for_ci(
            CANDIDATE_BRANCH,
            final_sha,
            "final-candidate",
        )
        cleanup = cleanup_source_authority(final_sha)
        detached_source_revalidation(final_sha)
        gap = audit_gap_ledger()
        report = build_terminal_report(
            final_sha,
            final_ci,
            cleanup,
            gap,
            history_added,
        )
        evidence_commit = publish_success(report)
        publish_pr_success(report, evidence_commit)
        cleanup_orchestration_refs()
        set_stage(
            "complete",
            candidate_sha=final_sha,
            ci_run_id=final_ci.run_id,
            source_evidence_artifact_id=final_ci.artifact_id,
            evidence_commit=evidence_commit,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except BaseException as error:  # noqa: BLE001
        publish_failure(error)
        raise
    finally:
        run(["git", "worktree", "remove", "--force", str(TARGET)], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
