#!/usr/bin/env python3
"""Bounded non-interactive Codex worker for Hepta Glasses source tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

POLICY_PATH = Path(__file__).with_name("policy.json")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)


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
    maximum_workspace_entries: int
    executable: str
    network_access_default: bool
    network_isolation_command: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = POLICY_PATH) -> "WorkerPolicy":
        document = json.loads(path.read_text(encoding="utf-8"))
        policy = cls(
            allowed_sandboxes=tuple(document["allowed_sandboxes"]),
            maximum_prompt_characters=int(document["maximum_prompt_characters"]),
            maximum_timeout_seconds=int(document["maximum_timeout_seconds"]),
            maximum_output_bytes=int(document["maximum_output_bytes"]),
            maximum_workspace_entries=int(document["maximum_workspace_entries"]),
            executable=str(document["executable"]),
            network_access_default=bool(document["network_access_default"]),
            network_isolation_command=tuple(
                str(value) for value in document["network_isolation_command"]
            ),
        )
        if not policy.allowed_sandboxes:
            raise WorkerError("worker_policy_sandbox_empty")
        if policy.maximum_prompt_characters < 1:
            raise WorkerError("worker_policy_prompt_limit_invalid")
        if policy.maximum_timeout_seconds < 1:
            raise WorkerError("worker_policy_timeout_limit_invalid")
        if policy.maximum_output_bytes < 1:
            raise WorkerError("worker_policy_output_limit_invalid")
        if policy.maximum_workspace_entries < 1:
            raise WorkerError("worker_policy_workspace_limit_invalid")
        if not policy.executable:
            raise WorkerError("worker_policy_executable_invalid")
        if (
            not policy.network_access_default
            and not policy.network_isolation_command
        ):
            raise WorkerError("network_isolation_required")
        return policy


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


def _validate_workspace_tree(
    workspace: Path,
    *,
    root: Path,
    maximum_entries: int,
) -> None:
    count = 0
    for path in workspace.rglob("*"):
        count += 1
        if count > maximum_entries:
            raise WorkerError("workspace_entry_limit_exceeded")
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise WorkerError("workspace_symlink_invalid") from error
        if resolved != root and root not in resolved.parents:
            raise WorkerError("workspace_symlink_escape")


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
    _validate_workspace_tree(
        workspace,
        root=workspace,
        maximum_entries=policy.maximum_workspace_entries,
    )

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
    codex_command = [
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
    if policy.network_access_default:
        return codex_command
    if not policy.network_isolation_command:
        raise WorkerError("network_isolation_required")
    return [*policy.network_isolation_command, *codex_command]


def bounded_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    source = source or os.environ
    allowed_names = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {name: source[name] for name in allowed_names if name in source}


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _read_bounded_process(
    process: subprocess.Popen[bytes],
    *,
    prompt: bytes,
    timeout_seconds: int,
    maximum_output_bytes: int,
) -> tuple[int, bytes, bytes]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _terminate(process)
        raise WorkerError("codex_pipe_setup_failed")

    try:
        process.stdin.write(prompt)
        process.stdin.close()
    except BrokenPipeError:
        process.stdin.close()

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_seconds

    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate(process)
                raise WorkerError("codex_timeout")
            events = selector.select(timeout=min(0.1, remaining))
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                output[key.data].extend(chunk)
                if sum(len(value) for value in output.values()) > maximum_output_bytes:
                    _terminate(process)
                    raise WorkerError("codex_output_too_large")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate(process)
            raise WorkerError("codex_timeout")
        return_code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        _terminate(process)
        raise WorkerError("codex_timeout") from error
    finally:
        for stream in (process.stdout, process.stderr):
            if stream.closed:
                continue
            try:
                selector.unregister(stream)
            except (KeyError, ValueError):
                pass
            stream.close()
        selector.close()

    return return_code, bytes(output["stdout"]), bytes(output["stderr"])


def _redact(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def run_task(
    task: CodexTask,
    *,
    policy: WorkerPolicy,
    dry_run: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=f"hepta-codex-{task.task_id}-"
    ) as temp_dir:
        temporary_root = Path(temp_dir)
        output_path = temporary_root / "last-message.txt"
        command = build_command(task, policy=policy, output_path=output_path)
        if dry_run:
            return {
                "task_id": task.task_id,
                "command": command,
                "workspace": str(task.workspace),
                "sandbox": task.sandbox,
            }

        if shutil.which(policy.executable) is None:
            raise WorkerError("codex_start_failed")
        if (
            not policy.network_access_default
            and shutil.which(policy.network_isolation_command[0]) is None
        ):
            raise WorkerError("network_isolator_unavailable")

        environment = bounded_environment()
        home = temporary_root / "home"
        codex_home = temporary_root / "codex-home"
        home.mkdir(mode=0o700)
        codex_home.mkdir(mode=0o700)
        environment["HOME"] = str(home)
        environment["CODEX_HOME"] = str(codex_home)
        try:
            process = subprocess.Popen(
                command,
                cwd=task.workspace,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            raise WorkerError("codex_start_failed") from error

        return_code, stdout, stderr = _read_bounded_process(
            process,
            prompt=task.prompt.encode("utf-8"),
            timeout_seconds=task.timeout_seconds,
            maximum_output_bytes=policy.maximum_output_bytes,
        )
        last_message_bytes = b""
        if output_path.is_file():
            size = output_path.stat().st_size
            if len(stdout) + len(stderr) + size > policy.maximum_output_bytes:
                raise WorkerError("codex_output_too_large")
            last_message_bytes = output_path.read_bytes()

        return {
            "task_id": task.task_id,
            "return_code": return_code,
            "last_message": _redact(
                last_message_bytes.decode("utf-8", errors="replace")
            ),
            "event_stream": _redact(stdout.decode("utf-8", errors="replace")),
            "diagnostic": _redact(stderr.decode("utf-8", errors="replace")),
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
