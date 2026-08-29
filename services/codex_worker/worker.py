#!/usr/bin/env python3
"""Bounded non-interactive Codex worker for Hepta Glasses source tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

POLICY_PATH = Path(__file__).with_name("policy.json")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class WorkerError(ValueError):
    """Stable validation or execution failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkerPolicy:
    allowed_sandboxes: tuple[str, ...]
    maximum_prompt_characters: int
    maximum_timeout_seconds: int
    maximum_output_bytes: int
    executable: str

    @classmethod
    def load(cls, path: Path = POLICY_PATH) -> "WorkerPolicy":
        document = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            allowed_sandboxes=tuple(document["allowed_sandboxes"]),
            maximum_prompt_characters=int(document["maximum_prompt_characters"]),
            maximum_timeout_seconds=int(document["maximum_timeout_seconds"]),
            maximum_output_bytes=int(document["maximum_output_bytes"]),
            executable=str(document["executable"]),
        )


@dataclass(frozen=True)
class CodexTask:
    task_id: str
    prompt: str
    workspace: Path
    sandbox: str
    timeout_seconds: int


def _mapping(document: Any) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise WorkerError("task_must_be_object")
    return document


def validate_task(
    document: Any,
    *,
    workspace_root: Path,
    policy: WorkerPolicy,
) -> CodexTask:
    value = _mapping(document)
    unknown = set(value) - {
        "task_id",
        "prompt",
        "workspace",
        "sandbox",
        "timeout_seconds",
    }
    if unknown:
        raise WorkerError("unknown_task_fields")

    task_id = value.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        raise WorkerError("invalid_task_id")

    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkerError("prompt_required")
    prompt = prompt.strip()
    if len(prompt) > policy.maximum_prompt_characters:
        raise WorkerError("prompt_too_large")

    sandbox = value.get("sandbox", "read-only")
    if sandbox not in policy.allowed_sandboxes:
        raise WorkerError("sandbox_not_allowed")

    timeout_seconds = value.get("timeout_seconds", 900)
    if (
        not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or timeout_seconds > policy.maximum_timeout_seconds
    ):
        raise WorkerError("invalid_timeout")

    raw_workspace = value.get("workspace")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise WorkerError("workspace_required")
    root = workspace_root.resolve(strict=True)
    workspace = (root / raw_workspace).resolve(strict=True)
    if workspace != root and root not in workspace.parents:
        raise WorkerError("workspace_outside_root")
    if not workspace.is_dir():
        raise WorkerError("workspace_not_directory")

    return CodexTask(
        task_id=task_id,
        prompt=prompt,
        workspace=workspace,
        sandbox=sandbox,
        timeout_seconds=timeout_seconds,
    )


def build_command(
    task: CodexTask,
    *,
    policy: WorkerPolicy,
    output_path: Path,
) -> list[str]:
    return [
        policy.executable,
        "exec",
        "--ephemeral",
        "--json",
        "--sandbox",
        task.sandbox,
        "--cd",
        str(task.workspace),
        "--output-last-message",
        str(output_path),
        "-",
    ]


def bounded_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = source or os.environ
    allowed_names = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {name: source[name] for name in allowed_names if name in source}


def run_task(
    task: CodexTask,
    *,
    policy: WorkerPolicy,
    dry_run: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"hepta-codex-{task.task_id}-") as temp_dir:
        output_path = Path(temp_dir) / "last-message.txt"
        command = build_command(task, policy=policy, output_path=output_path)
        if dry_run:
            return {
                "task_id": task.task_id,
                "command": command,
                "workspace": str(task.workspace),
                "sandbox": task.sandbox,
            }

        try:
            completed = subprocess.run(
                command,
                input=task.prompt,
                text=True,
                cwd=task.workspace,
                env=bounded_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=task.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise WorkerError("codex_timeout") from error
        except OSError as error:
            raise WorkerError("codex_start_failed") from error

        stdout = completed.stdout.encode("utf-8", errors="replace")
        stderr = completed.stderr.encode("utf-8", errors="replace")
        if len(stdout) + len(stderr) > policy.maximum_output_bytes:
            raise WorkerError("codex_output_too_large")
        last_message = (
            output_path.read_text(encoding="utf-8", errors="replace")
            if output_path.is_file()
            else ""
        )
        return {
            "task_id": task.task_id,
            "return_code": completed.returncode,
            "last_message": last_message,
            "event_stream": completed.stdout,
            "diagnostic": completed.stderr,
        }


def load_document(path: Path | None) -> Any:
    if path is None:
        return json.load(os.sys.stdin)
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        policy = WorkerPolicy.load()
        task = validate_task(
            load_document(args.task),
            workspace_root=args.workspace_root,
            policy=policy,
        )
        result = run_task(task, policy=policy, dry_run=args.dry_run)
    except (WorkerError, json.JSONDecodeError, OSError) as error:
        code = error.code if isinstance(error, WorkerError) else "invalid_worker_input"
        print(json.dumps({"ok": False, "error": code}, separators=(",", ":")))
        return 2

    print(json.dumps({"ok": True, "result": result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
