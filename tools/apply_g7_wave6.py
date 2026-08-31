#!/usr/bin/env python3
"""Patch the Codex worker to enforce output limits while the child runs."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = ROOT / "services/codex_worker/worker.py"
    text = path.read_text(encoding="utf-8")
    if "import signal\n" not in text:
        text = text.replace(
            "import re\n",
            "import re\nimport signal\nimport threading\nimport time\n",
            1,
        )

    helper = r'''

def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _run_bounded_process(
    command: Sequence[str],
    *,
    prompt: str,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    maximum_output_bytes: int,
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        raise WorkerError("codex_start_failed") from error

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    total_bytes = 0
    lock = threading.Lock()
    overflow = threading.Event()

    def drain(stream, chunks: list[bytes]) -> None:
        nonlocal total_bytes
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                with lock:
                    total_bytes += len(chunk)
                    if total_bytes > maximum_output_bytes:
                        overflow.set()
                        return
                chunks.append(chunk)
        finally:
            stream.close()

    assert process.stdout is not None
    assert process.stderr is not None
    readers = [
        threading.Thread(
            target=drain,
            args=(process.stdout, stdout_chunks),
            daemon=True,
        ),
        threading.Thread(
            target=drain,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    assert process.stdin is not None
    try:
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
    except BrokenPipeError:
        pass

    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        if overflow.is_set():
            _terminate_process_group(process)
            for reader in readers:
                reader.join(timeout=5)
            raise WorkerError("codex_output_too_large")
        if time.monotonic() >= deadline:
            _terminate_process_group(process)
            for reader in readers:
                reader.join(timeout=5)
            raise WorkerError("codex_timeout")
        time.sleep(0.01)

    for reader in readers:
        reader.join(timeout=5)
    if overflow.is_set():
        raise WorkerError("codex_output_too_large")
    return process.returncode, b"".join(stdout_chunks), b"".join(stderr_chunks)
'''
    if "def _run_bounded_process(" not in text:
        marker = "\ndef run_task(\n"
        if marker not in text:
            raise RuntimeError("run_task marker missing")
        text = text.replace(marker, helper + marker, 1)

    old = '''        try:
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
'''
    new = '''        return_code, stdout, stderr = _run_bounded_process(
            command,
            prompt=task.prompt,
            cwd=task.workspace,
            env=bounded_environment(),
            timeout_seconds=task.timeout_seconds,
            maximum_output_bytes=policy.maximum_output_bytes,
        )
'''
    if new not in text:
        if old not in text:
            raise RuntimeError("Codex subprocess.run block missing")
        text = text.replace(old, new, 1)

    text = text.replace(
        '            "return_code": completed.returncode,\n'
        '            "last_message": last_message,\n'
        '            "event_stream": completed.stdout,\n'
        '            "diagnostic": completed.stderr,\n',
        '            "return_code": return_code,\n'
        '            "last_message": last_message,\n'
        '            "event_stream": stdout.decode("utf-8", errors="replace"),\n'
        '            "diagnostic": stderr.decode("utf-8", errors="replace"),\n',
    )
    path.write_text(text, encoding="utf-8")

    test = ROOT / "services/codex_worker/test_bounded_output_g7.py"
    test.write_text(
        '''from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from services.codex_worker.worker import WorkerError, _run_bounded_process


class BoundedProcessTests(unittest.TestCase):
    def test_collects_output_within_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, stdout, stderr = _run_bounded_process(
                [sys.executable, "-c", "print('ok')"],
                prompt="",
                cwd=Path(directory),
                env={"PATH": str(Path(sys.executable).parent)},
                timeout_seconds=5,
                maximum_output_bytes=1024,
            )
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), b"ok")
        self.assertEqual(stderr, b"")

    def test_terminates_process_group_on_output_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkerError) as raised:
                _run_bounded_process(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.write('x' * 200000)",
                    ],
                    prompt="",
                    cwd=Path(directory),
                    env={"PATH": str(Path(sys.executable).parent)},
                    timeout_seconds=5,
                    maximum_output_bytes=1024,
                )
        self.assertEqual(raised.exception.code, "codex_output_too_large")

    def test_terminates_process_group_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkerError) as raised:
                _run_bounded_process(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    prompt="",
                    cwd=Path(directory),
                    env={"PATH": str(Path(sys.executable).parent)},
                    timeout_seconds=1,
                    maximum_output_bytes=1024,
                )
        self.assertEqual(raised.exception.code, "codex_timeout")


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )
    path.chmod(0o644)
    for tool in ROOT.glob("tools/apply_g7_*.py"):
        tool.chmod(0o755)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
