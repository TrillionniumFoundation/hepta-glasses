#!/usr/bin/env python3
"""Bounded non-interactive Codex worker for Hepta Glasses source tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence

POLICY_PATH = Path(__file__).with_name("policy.json")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
READ_CHUNK_BYTES = 64 * 1024


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
    network_isolation_command: tuple[str, ...]
    require_network_isolation: bool

    @classmethod
    def load(cls, path: Path = POLICY_PATH) -> "WorkerPolicy":
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise WorkerError("worker_policy_invalid")
        allowed_sandboxes = document.get("allowed_sandboxes")
        isolation = document.get("network_isolation_command")
        if (
            not isinstance(allowed_sandboxes, list)
            or not all(isinstance(item, str) and item for item in allowed_sandboxes)
            or not isinstance(isolation, list)
            or not all(isinstance(item, str) and item for item in isolation)
        ):
            raise WorkerError("worker_policy_invalid")
        policy = cls(
            allowed_sandboxes=tuple(allowed_sandboxes),
            maximum_prompt_characters=int(document["maximum_prompt_characters"]),
            maximum_timeout_seconds=int(document["maximum_timeout_seconds"]),
            maximum_output_bytes=int(document["maximum_output_bytes"]),
            executable=str(document["executable"]),
            network_isolation_command=tuple(isolation),
            require_network_isolation=bool(
                document.get("require_network_isolation", True)
            ),
        )
        if (
            not policy.allowed_sandboxes
            or policy.maximum_prompt_characters < 1
            or policy.maximum_timeout_seconds < 1
            or policy.maximum_output_bytes < 1
            or not policy.executable
            or (
                policy.require_network_isolation
                and not policy.network_isolation_command
            )
        ):
            raise WorkerError("worker_policy_invalid")
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
        or isinstance(timeout_seconds, bool)
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
    if policy.require_network_isolation:
        if not policy.network_isolation_command:
            raise WorkerError("network_isolation_required")
        return [*policy.network_isolation_command, *codex_command]
    return codex_command


def bounded_environment(
    source: Mapping[str, str] | None = None,
    *,
    home: Path,
    codex_home: Path,
) -> dict[str, str]:
    """Return a secret-minimal environment with worker-owned credential roots."""

    source = source or os.environ
    allowed_names = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    environment = {
        name: source[name] for name in allowed_names if name in source
    }
    environment["HOME"] = str(home)
    environment["CODEX_HOME"] = str(codex_home)
    return environment


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass


def _drain_bounded(
    stream: BinaryIO,
    destination: bytearray,
    *,
    maximum_bytes: int,
    total: list[int],
    lock: threading.Lock,
    overflow: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    try:
        while True:
            chunk = stream.read(READ_CHUNK_BYTES)
            if not chunk:
                return
            with lock:
                remaining = max(0, maximum_bytes - total[0])
                if remaining:
                    destination.extend(chunk[:remaining])
                    total[0] += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    overflow.set()
            if overflow.is_set():
                _kill_process_group(process)
                return
    finally:
        stream.close()


def _read_last_message(path: Path, *, maximum_bytes: int) -> bytes:
    if not path.exists() and not path.is_symlink():
        return b""
    try:
        metadata = path.lstat()
    except OSError as error:
        raise WorkerError("codex_last_message_invalid") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum_bytes:
        raise WorkerError(
            "codex_output_too_large"
            if metadata.st_size > maximum_bytes
            else "codex_last_message_invalid"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise WorkerError("codex_last_message_invalid") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise WorkerError("codex_last_message_invalid")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(READ_CHUNK_BYTES, maximum_bytes - total + 1),
            )
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise WorkerError("codex_output_too_large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_executable(command: str, *, error_code: str) -> None:
    if os.path.sep in command:
        exists = Path(command).is_file() and os.access(command, os.X_OK)
    else:
        exists = shutil.which(command) is not None
    if not exists:
        raise WorkerError(error_code)


def run_task(
    task: CodexTask,
    *,
    policy: WorkerPolicy,
    dry_run: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"hepta-codex-{task.task_id}-") as temp_dir:
        temporary_root = Path(temp_dir)
        home = temporary_root / "home"
        codex_home = temporary_root / "codex-home"
        home.mkdir(mode=0o700)
        codex_home.mkdir(mode=0o700)
        output_path = temporary_root / "last-message.txt"
        command = build_command(task, policy=policy, output_path=output_path)
        if dry_run:
            return {
                "task_id": task.task_id,
                "command": command,
                "workspace": str(task.workspace),
                "sandbox": task.sandbox,
                "network_isolated": policy.require_network_isolation,
                "host_home_inherited": False,
            }

        if policy.require_network_isolation:
            _require_executable(
                policy.network_isolation_command[0],
                error_code="network_isolation_unavailable",
            )
        _require_executable(
            policy.executable,
            error_code="codex_executable_unavailable",
        )

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=task.workspace,
                env=bounded_environment(
                    home=home,
                    codex_home=codex_home,
                ),
                start_new_session=True,
            )
        except OSError as error:
            raise WorkerError("codex_start_failed") from error

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        total = [0]
        total_lock = threading.Lock()
        overflow = threading.Event()
        readers = [
            threading.Thread(
                target=_drain_bounded,
                args=(process.stdout, stdout),
                kwargs={
                    "maximum_bytes": policy.maximum_output_bytes,
                    "total": total,
                    "lock": total_lock,
                    "overflow": overflow,
                    "process": process,
                },
                daemon=True,
            ),
            threading.Thread(
                target=_drain_bounded,
                args=(process.stderr, stderr),
                kwargs={
                    "maximum_bytes": policy.maximum_output_bytes,
                    "total": total,
                    "lock": total_lock,
                    "overflow": overflow,
                    "process": process,
                },
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        try:
            try:
                process.stdin.write(task.prompt.encode("utf-8"))
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()
            try:
                return_code = process.wait(timeout=task.timeout_seconds)
            except subprocess.TimeoutExpired as error:
                _kill_process_group(process)
                process.wait()
                raise WorkerError("codex_timeout") from error
        finally:
            for reader in readers:
                reader.join(timeout=5)
            if any(reader.is_alive() for reader in readers):
                _kill_process_group(process)
                raise WorkerError("codex_output_reader_failed")

        if overflow.is_set():
            raise WorkerError("codex_output_too_large")
        remaining = policy.maximum_output_bytes - total[0]
        last_message_bytes = _read_last_message(
            output_path,
            maximum_bytes=remaining,
        )
        return {
            "task_id": task.task_id,
            "return_code": return_code,
            "last_message": last_message_bytes.decode(
                "utf-8", errors="replace"
            ),
            "event_stream": bytes(stdout).decode("utf-8", errors="replace"),
            "diagnostic": bytes(stderr).decode("utf-8", errors="replace"),
            "network_isolated": policy.require_network_isolation,
            "host_home_inherited": False,
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
