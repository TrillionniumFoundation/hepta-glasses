#!/usr/bin/env python3
"""Stable documentation-truth entrypoint with closed-PR run projection handling.

GitHub's workflow-run ``pull_requests`` field is a mutable convenience
projection: it can become empty after the originating pull request is closed.
It is therefore not treated as an immutable authority. When, and only when,
that projection is exactly empty, this module derives the historical
association from the independently fetched frozen pull request together with
the run's exact event, branch, commit, tree, workflow and terminal result.
Malformed, conflicting, duplicated or ambiguous non-empty projections fail
closed.

The substantive local and live evidence verification remains in
``documentation_truth_core``. This entrypoint normalizes only the mutable
GitHub projection without weakening any commit, tree, job, Artifact, review,
CODEOWNERS or timestamp check.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import threading
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.qualification import documentation_truth_core as _core

# Preserve the historical module API, including deliberately private helpers
# patched by the live hostile tests. The two functions below override the core
# entrypoints after this export.
for _export_name in dir(_core):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_core, _export_name)

PINNED_BASELINE_HEAD_BRANCH = "work/hepta-g10-trusted-openssl-custody-20260902"
_LIVE_BRIDGE_LOCK = threading.RLock()


def _exact_projection_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    head = item.get("head")
    base = item.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        return False
    return (
        item.get("number") == PINNED_BASELINE["pull_request"]
        and head.get("sha") == PINNED_BASELINE["commit"]
        and base.get("sha") == PINNED_BASELINE["base_commit"]
    )


def _exact_closed_pull_request_anchor(
    run: dict[str, Any],
    pull: dict[str, Any] | None,
) -> bool:
    """Return whether an empty run projection has an exact independent anchor."""

    if not isinstance(pull, dict):
        return False
    pin = PINNED_BASELINE
    pull_head = pull.get("head")
    pull_base = pull.get("base")
    pull_user = pull.get("user")
    run_head = run.get("head_commit")
    if not all(
        isinstance(value, dict)
        for value in (pull_head, pull_base, pull_user, run_head)
    ):
        return False
    return (
        pull.get("number") == pin["pull_request"]
        and pull_head.get("sha") == pin["commit"]
        and pull_head.get("ref") == PINNED_BASELINE_HEAD_BRANCH
        and pull_base.get("sha") == pin["base_commit"]
        and pull_user.get("login") == pin["pull_request_author"]
        and run.get("id") == pin["workflow_run_id"]
        and run.get("workflow_id") == pin["workflow_id"]
        and run.get("name") == pin["workflow_name"]
        and run.get("run_number") == pin["workflow_run_number"]
        and run.get("run_attempt") == pin["workflow_run_attempt"]
        and run.get("event") == pin["workflow_event"]
        and run.get("head_branch") == PINNED_BASELINE_HEAD_BRANCH
        and run.get("head_sha") == pin["commit"]
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run_head.get("id") == pin["commit"]
        and run_head.get("tree_id") == pin["tree"]
    )


def _normalize_mutable_run_projection(
    run: dict[str, Any],
    pull: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate a live projection or derive only GitHub's exact empty form."""

    projection = run.get("pull_requests")
    if not isinstance(projection, list):
        fail("workflow run pull-request projection is not a list")
    if projection:
        if len(projection) != 1 or not _exact_projection_item(projection[0]):
            fail("workflow run pull-request projection is ambiguous or conflicting")
        return run
    if not _exact_closed_pull_request_anchor(run, pull):
        fail(
            "empty workflow pull-request projection lacks exact frozen run/PR anchors"
        )
    normalized = copy.deepcopy(run)
    normalized["pull_requests"] = [
        {
            "number": PINNED_BASELINE["pull_request"],
            "head": {"sha": PINNED_BASELINE["commit"]},
            "base": {"sha": PINNED_BASELINE["base_commit"]},
        }
    ]
    return normalized


def verify_github_baseline(token: str | None = None) -> dict[str, Any]:
    """Run the complete core verifier with a bounded mutable-field adapter."""

    owner_repo = EXPECTED_REPOSITORY
    pull_path = f"/repos/{owner_repo}/pulls/{PINNED_BASELINE['pull_request']}"
    run_path = (
        f"/repos/{owner_repo}/actions/runs/"
        f"{PINNED_BASELINE['workflow_run_id']}"
    )

    # Capture public functions before bridging. Existing hostile tests can
    # patch these names on this module and the core verifier will still use the
    # patched functions through this adapter.
    public_api = globals()["_stable_api_object"]
    public_artifact = globals()["_stable_artifact_zip"]
    public_artifact_verifier = globals()["_verify_artifact_zip"]
    observed_pull: dict[str, Any] | None = None

    def stable_api(path: str, *, token: str) -> dict[str, Any]:
        nonlocal observed_pull
        value = public_api(path, token=token)
        if path == pull_path:
            observed_pull = copy.deepcopy(value)
            return value
        if path == run_path:
            return _normalize_mutable_run_projection(value, observed_pull)
        return value

    def stable_artifact(path: str, *, token: str) -> bytes:
        return public_artifact(path, token=token)

    def verify_artifact(raw: bytes) -> list[str]:
        return public_artifact_verifier(raw)

    with _LIVE_BRIDGE_LOCK:
        original_api = _core._stable_api_object
        original_artifact = _core._stable_artifact_zip
        original_artifact_verifier = _core._verify_artifact_zip
        _core._stable_api_object = stable_api
        _core._stable_artifact_zip = stable_artifact
        _core._verify_artifact_zip = verify_artifact
        try:
            return _core.verify_github_baseline(token)
        finally:
            _core._stable_api_object = original_api
            _core._stable_artifact_zip = original_artifact
            _core._verify_artifact_zip = original_artifact_verifier


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
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
