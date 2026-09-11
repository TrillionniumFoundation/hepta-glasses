"""Fail-closed POSIX process-group supervisor for a fixed executable.

This module provides bounded termination and basic rlimit custody. It is not a
seccomp, mount-namespace, filesystem, credential, or network sandbox. Production
use must invoke it from a dedicated trusted worker process and combine it with an
OS isolation layer that makes capability brokers the only external I/O path.
"""
from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
_MAX_ARGUMENTS = 128
_MAX_ARGUMENT_BYTES = 4096
_MAX_ENVIRONMENT = 64
_MAX_ENVIRONMENT_BYTES = 65536
_MAX_INPUT_BYTES = 32768
_RESERVED_ENV = frozenset({"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME"})
_LAUNCHER = r'''import ctypes,json,os,resource,sys
spec_fd=int(sys.argv[1]); executable_fd=int(sys.argv[2])
with os.fdopen(os.dup(spec_fd),"rb",closefd=True) as handle:
    raw=handle.read(131073)
if len(raw)>131072: raise SystemExit(126)
spec=json.loads(raw.decode("utf-8"))
os.close(spec_fd)
for name,value in spec["rlimits"]:
    resource.setrlimit(getattr(resource,name),(value,value))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
try:
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0: raise OSError(ctypes.get_errno(),"prctl")
except Exception:
    raise SystemExit(126)
os.umask(0o077)
os.execve("/proc/self/fd/%d" % executable_fd,spec["argv"],spec["env"])
'''


class SupervisorError(RuntimeError):
    """Stable supervisor failure that never embeds child-controlled text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TaskLimits:
    wall_seconds: float = 30.0
    cpu_seconds: int = 10
    address_space_bytes: int = 512 * 1024 * 1024
    file_size_bytes: int = 16 * 1024 * 1024
    open_files: int = 64
    processes: int = 16
    output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if type(self.wall_seconds) not in (int, float) or not 0.01 <= float(self.wall_seconds) <= 3600:
            raise SupervisorError("task_wall_limit_invalid")
        values = (
            (self.cpu_seconds, 1, 3600, "task_cpu_limit_invalid"),
            (self.address_space_bytes, 16 * 1024 * 1024, 64 * 1024**3, "task_memory_limit_invalid"),
            (self.file_size_bytes, 0, 1024**3, "task_file_limit_invalid"),
            (self.open_files, 8, 4096, "task_open_file_limit_invalid"),
            (self.processes, 1, 1024, "task_process_limit_invalid"),
            (self.output_bytes, 1, 64 * 1024 * 1024, "task_output_limit_invalid"),
        )
        for value, lower, upper, code in values:
            if type(value) is not int or not lower <= value <= upper:
                raise SupervisorError(code)


@dataclass(frozen=True)
class SupervisedTask:
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: str = "/"
    environment: Mapping[str, str] | None = None
    input_bytes: bytes = b""
    limits: TaskLimits = TaskLimits()

    def __post_init__(self) -> None:
        if type(self.executable) is not str or not self.executable.startswith("/") or "\x00" in self.executable:
            raise SupervisorError("task_executable_invalid")
        if type(self.arguments) is not tuple or len(self.arguments) > _MAX_ARGUMENTS:
            raise SupervisorError("task_arguments_invalid")
        for value in self.arguments:
            if type(value) is not str or "\x00" in value or len(value.encode("utf-8")) > _MAX_ARGUMENT_BYTES:
                raise SupervisorError("task_arguments_invalid")
        if type(self.working_directory) is not str or not self.working_directory.startswith("/") or "\x00" in self.working_directory:
            raise SupervisorError("task_working_directory_invalid")
        if type(self.input_bytes) is not bytes or len(self.input_bytes) > _MAX_INPUT_BYTES:
            raise SupervisorError("task_input_invalid")
        raw = {} if self.environment is None else dict(self.environment)
        if len(raw) > _MAX_ENVIRONMENT:
            raise SupervisorError("task_environment_invalid")
        total = 0
        clean: dict[str, str] = {}
        for key, value in raw.items():
            if (type(key) is not str or not _ENV_NAME.fullmatch(key) or key in _RESERVED_ENV
                    or type(value) is not str or "\x00" in value):
                raise SupervisorError("task_environment_invalid")
            total += len(key.encode()) + len(value.encode())
            if total > _MAX_ENVIRONMENT_BYTES:
                raise SupervisorError("task_environment_invalid")
            clean[key] = value
        object.__setattr__(self, "environment", MappingProxyType(clean))
        if not isinstance(self.limits, TaskLimits):
            raise SupervisorError("task_limits_invalid")


@dataclass(frozen=True)
class TaskResult:
    return_code: int
    stdout: bytes
    stderr: bytes
    terminated: bool = False


@dataclass
class _HeldDirectory:
    parent_fd: int
    directory_fd: int
    expected: tuple[int, int]
    path: str
    name: str

    def close(self) -> None:
        for fd in (self.directory_fd, self.parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.directory_fd = self.parent_fd = -1


def _open_working_directory(path: str) -> _HeldDirectory:
    if os.name != "posix" or not Path("/proc/self/fd").is_dir() or not hasattr(os, "O_NOFOLLOW"):
        raise SupervisorError("task_supervisor_platform_unsupported")
    parts = Path(path).parts
    if not parts or parts[0] != "/" or any(part in ("", ".", "..") for part in parts[1:]):
        raise SupervisorError("task_working_directory_invalid")
    if len(parts) == 1:
        directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        parent_fd = os.dup(directory_fd)
        current = os.fstat(directory_fd)
        return _HeldDirectory(parent_fd, directory_fd, (current.st_dev, current.st_ino), path, ".")
    parent_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        directory_fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        try:
            os.close(parent_fd)
        except OSError:
            pass
        code = ("task_working_directory_linked"
                if error.errno in (errno.ELOOP, errno.ENOTDIR)
                else "task_working_directory_unavailable")
        raise SupervisorError(code) from None
    try:
        held = os.fstat(directory_fd)
        named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(held.st_mode) or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            raise SupervisorError("task_working_directory_identity_invalid")
        return _HeldDirectory(parent_fd, directory_fd, (held.st_dev, held.st_ino), path, parts[-1])
    except BaseException:
        os.close(directory_fd)
        os.close(parent_fd)
        raise


def _verify_working_directory(held: _HeldDirectory) -> None:
    if held.directory_fd < 0:
        raise SupervisorError("task_working_directory_closed")
    current = os.fstat(held.directory_fd)
    try:
        named = os.stat(held.name, dir_fd=held.parent_fd, follow_symlinks=False)
        absolute = os.stat(held.path, follow_symlinks=False)
    except OSError:
        raise SupervisorError("task_working_directory_replaced") from None
    if (not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != held.expected
            or (named.st_dev, named.st_ino) != held.expected
            or (absolute.st_dev, absolute.st_ino) != held.expected):
        raise SupervisorError("task_working_directory_replaced")


@dataclass
class _HeldExecutable:
    parent_fd: int
    executable_fd: int
    expected: tuple[int, int]
    path: str

    def close(self) -> None:
        for fd in (self.executable_fd, self.parent_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.executable_fd = self.parent_fd = -1


def _open_executable(path: str) -> _HeldExecutable:
    if os.name != "posix" or not Path("/proc/self/fd").is_dir() or not hasattr(os, "O_NOFOLLOW"):
        raise SupervisorError("task_supervisor_platform_unsupported")
    parts = Path(path).parts
    if not parts or parts[0] != "/" or len(parts) < 2 or any(part in ("", ".", "..") for part in parts[1:]):
        raise SupervisorError("task_executable_invalid")
    directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        executable_fd = os.open(parts[-1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        try:
            os.close(directory_fd)
        except OSError:
            pass
        code = "task_executable_linked" if error.errno in (errno.ELOOP, errno.ENOTDIR) else "task_executable_unavailable"
        raise SupervisorError(code) from None
    try:
        held = os.fstat(executable_fd)
        named = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(held.st_mode) or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
            raise SupervisorError("task_executable_identity_invalid")
        if held.st_nlink != 1 or held.st_uid not in (0, os.geteuid()) or held.st_mode & 0o022:
            raise SupervisorError("task_executable_permissions_invalid")
        if not held.st_mode & 0o111:
            raise SupervisorError("task_executable_not_executable")
        return _HeldExecutable(directory_fd, executable_fd, (held.st_dev, held.st_ino), path)
    except BaseException:
        os.close(executable_fd)
        os.close(directory_fd)
        raise


def _verify_executable(held: _HeldExecutable) -> None:
    if held.executable_fd < 0:
        raise SupervisorError("task_executable_closed")
    current = os.fstat(held.executable_fd)
    try:
        named = os.stat(Path(held.path).name, dir_fd=held.parent_fd, follow_symlinks=False)
    except OSError:
        raise SupervisorError("task_executable_replaced") from None
    if (current.st_dev, current.st_ino) != held.expected or (named.st_dev, named.st_ino) != held.expected:
        raise SupervisorError("task_executable_replaced")
    if current.st_nlink != 1 or current.st_uid not in (0, os.geteuid()) or current.st_mode & 0o022 or not current.st_mode & 0o111:
        raise SupervisorError("task_executable_permissions_invalid")


def _sealed_spec(document: dict[str, object]) -> int:
    if not hasattr(os, "memfd_create"):
        raise SupervisorError("task_supervisor_platform_unsupported")
    import fcntl
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > 131072:
        raise SupervisorError("task_spec_too_large")
    fd = os.memfd_create("hepta-task-spec", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise SupervisorError("task_spec_io_unavailable")
            view = view[written:]
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    # The group leader may already have exited while a descendant still holds
    # stdout/stderr. Kill the process group even when Popen.poll() is terminal.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()


def run_supervised(task: SupervisedTask, *, cancel: threading.Event | None = None) -> TaskResult:
    """Run one fixed executable and synchronously reap its process-group leader.

    Cancellation, timeout and output overflow raise a stable error after SIGKILL
    is sent to the process group. A successful return never implies network or
    filesystem isolation beyond the explicit rlimits and process-group custody.
    """
    if not isinstance(task, SupervisedTask):
        raise SupervisorError("task_invalid")
    if cancel is not None and not isinstance(cancel, threading.Event):
        raise SupervisorError("task_cancel_invalid")
    if cancel is not None and cancel.is_set():
        raise SupervisorError("task_cancelled")
    working = _open_working_directory(task.working_directory)
    held: _HeldExecutable | None = None
    spec_fd = -1
    process: subprocess.Popen[bytes] | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        held = _open_executable(task.executable)
        _verify_working_directory(working)
        _verify_executable(held)
        temporary = tempfile.TemporaryDirectory(prefix="hepta-task-")
        home = Path(temporary.name)
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
               "HOME": str(home), "TMPDIR": str(home)}
        env.update(dict(task.environment or {}))
        limits = task.limits
        spec_fd = _sealed_spec({
            "argv": [task.executable, *task.arguments],
            "env": env,
            "rlimits": [
                ["RLIMIT_CPU", limits.cpu_seconds],
                ["RLIMIT_AS", limits.address_space_bytes],
                ["RLIMIT_FSIZE", limits.file_size_bytes],
                ["RLIMIT_NOFILE", limits.open_files],
                ["RLIMIT_NPROC", limits.processes],
            ],
        })
        _verify_working_directory(working)
        _verify_executable(held)
        try:
            process = subprocess.Popen(
                ["/proc/self/exe", "-I", "-S", "-c", _LAUNCHER, str(spec_fd), str(held.executable_fd)],
                cwd=f"/proc/self/fd/{working.directory_fd}",
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(spec_fd, held.executable_fd, working.directory_fd),
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            raise SupervisorError("task_start_failed") from None
        _verify_working_directory(working)
        _verify_executable(held)
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        if task.input_bytes:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        pending = memoryview(task.input_bytes)
        output = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + float(limits.wall_seconds)
        try:
            while selector.get_map():
                if cancel is not None and cancel.is_set():
                    _kill_group(process)
                    raise SupervisorError("task_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_group(process)
                    raise SupervisorError("task_timeout")
                events = selector.select(min(0.05, remaining))
                if not events and process.poll() is not None:
                    continue
                for key, _ in events:
                    stream = key.fileobj
                    if key.data == "stdin":
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        try:
                            written = os.write(stream.fileno(), pending[:16384])
                        except BrokenPipeError:
                            written = 0
                            pending = pending[len(pending):]
                        if written:
                            pending = pending[written:]
                        if not pending:
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    output[key.data].extend(chunk)
                    if len(output["stdout"]) + len(output["stderr"]) > limits.output_bytes:
                        _kill_group(process)
                        raise SupervisorError("task_output_exceeded")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_group(process)
                raise SupervisorError("task_timeout")
            try:
                return_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                raise SupervisorError("task_timeout") from None
        finally:
            selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        _verify_working_directory(working)
        return TaskResult(return_code, bytes(output["stdout"]), bytes(output["stderr"]))
    finally:
        # A successful group leader can deliberately close all inherited pipes,
        # fork a descendant, and exit. Always signal the original process group
        # before returning so pipe closure cannot turn a live descendant into a
        # successful terminal result. killpg is harmless when the group is empty.
        if process is not None:
            _kill_group(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        if spec_fd >= 0:
            try:
                os.close(spec_fd)
            except OSError:
                pass
        if held is not None:
            held.close()
        working.close()
        if temporary is not None:
            temporary.cleanup()
