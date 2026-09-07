"""Linux broker-only Skill execution with Landlock and seccomp enforcement.

The runtime executes UTF-8 Python source only after a trusted launcher has:

* captured and verified sealed source/specification bytes;
* set ``NO_NEW_PRIVS`` and hard rlimits;
* restricted filesystem access with Landlock;
* installed a seccomp filter denying networking, process creation, namespace,
  mount, ptrace, keyring, BPF and further-exec syscalls; and
* retained exactly one pre-opened capability-broker file descriptor.

This is a Linux x86-64 source implementation.  It fails closed when the kernel
cannot enforce Landlock or seccomp.  It is not a hostile-kernel, VM, cgroup,
confidential-computing or multi-tenant deployment qualification claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_INPUT_BYTES = 256 * 1024
_MAX_FRAME_BYTES = 64 * 1024


class SkillSandboxError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 10.0
    cpu_seconds: int = 5
    address_space_bytes: int = 512 * 1024 * 1024
    output_bytes: int = 1024 * 1024
    open_files: int = 32
    capability_requests: int = 16

    def __post_init__(self) -> None:
        if (
            type(self.wall_seconds) not in (int, float)
            or type(self.wall_seconds) is bool
            or not math.isfinite(float(self.wall_seconds))
            or not 0.05 <= float(self.wall_seconds) <= 300
            or type(self.cpu_seconds) is not int
            or not 1 <= self.cpu_seconds <= 300
            or type(self.address_space_bytes) is not int
            or not 64 * 1024 * 1024 <= self.address_space_bytes <= 8 * 1024**3
            or type(self.output_bytes) is not int
            or not 1 <= self.output_bytes <= 16 * 1024 * 1024
            or type(self.open_files) is not int
            or not 8 <= self.open_files <= 256
            or type(self.capability_requests) is not int
            or not 0 <= self.capability_requests <= 128
        ):
            raise SkillSandboxError("skill_sandbox_limits_invalid")


@dataclass(frozen=True)
class SandboxExecution:
    output: Mapping[str, object]
    capability_requests: int
    stdout_digest: str


# The launcher is trusted repository code.  Skill bytes are compiled but never
# executed until every mandatory kernel control is installed.
_LAUNCHER = r'''
import ctypes,errno,json,os,resource,struct,sys

PR_SET_NO_NEW_PRIVS=38
PR_SET_SECCOMP=22
SECCOMP_MODE_FILTER=2
SECCOMP_RET_KILL_PROCESS=0x80000000
SECCOMP_RET_ERRNO=0x00050000
SECCOMP_RET_ALLOW=0x7fff0000
AUDIT_ARCH_X86_64=0xc000003e
BPF_LD=0x00; BPF_W=0x00; BPF_ABS=0x20
BPF_JMP=0x05; BPF_JEQ=0x10; BPF_K=0x00
BPF_RET=0x06
SYS_LANDLOCK_CREATE_RULESET=444
SYS_LANDLOCK_ADD_RULE=445
SYS_LANDLOCK_RESTRICT_SELF=446
LANDLOCK_CREATE_RULESET_VERSION=1
LANDLOCK_RULE_PATH_BENEATH=1

class SockFilter(ctypes.Structure):
    _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]
class SockFprog(ctypes.Structure):
    _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(SockFilter))]
class RulesetAttr(ctypes.Structure):
    _fields_=[('handled_access_fs',ctypes.c_uint64)]
class PathBeneathAttr(ctypes.Structure):
    _fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int32),('reserved',ctypes.c_uint32)]

libc=ctypes.CDLL(None,use_errno=True)
libc.prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong]
libc.prctl.restype=ctypes.c_int

def syscall(number,*args):
    value=libc.syscall(number,*args)
    if value < 0:
        raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
    return value

def read_all(fd,limit):
    data=bytearray()
    while True:
        part=os.read(fd,min(65536,limit+1-len(data)))
        if not part: break
        data.extend(part)
        if len(data)>limit: raise RuntimeError('oversized')
    return bytes(data)

def no_new_privs():
    if libc.prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)!=0:
        raise OSError(ctypes.get_errno(),'no_new_privs')

def add_landlock_path(ruleset,path,rights):
    flags=getattr(os,'O_PATH',os.O_RDONLY)|os.O_CLOEXEC
    fd=os.open(path,flags)
    try:
        attr=PathBeneathAttr(rights,fd,0)
        syscall(SYS_LANDLOCK_ADD_RULE,ruleset,LANDLOCK_RULE_PATH_BENEATH,ctypes.byref(attr),0)
    finally:
        os.close(fd)

def landlock(workspace):
    abi=syscall(SYS_LANDLOCK_CREATE_RULESET,0,0,LANDLOCK_CREATE_RULESET_VERSION)
    if abi < 1: raise RuntimeError('landlock_abi')
    execute=1<<0; write_file=1<<1; read_file=1<<2; read_dir=1<<3
    remove_dir=1<<4; remove_file=1<<5; make_char=1<<6; make_dir=1<<7
    make_reg=1<<8; make_sock=1<<9; make_fifo=1<<10; make_block=1<<11; make_sym=1<<12
    handled=(execute|write_file|read_file|read_dir|remove_dir|remove_file|make_char|
             make_dir|make_reg|make_sock|make_fifo|make_block|make_sym)
    if abi>=2: handled|=1<<13
    if abi>=3: handled|=1<<14
    attr=RulesetAttr(handled)
    ruleset=syscall(SYS_LANDLOCK_CREATE_RULESET,ctypes.byref(attr),ctypes.sizeof(attr),0)
    try:
        readonly=execute|read_file|read_dir
        for path in ('/usr','/bin','/lib','/lib64'):
            if os.path.exists(path): add_landlock_path(ruleset,path,readonly)
        for path in ('/etc/ld.so.cache','/dev/null','/dev/urandom'):
            if os.path.exists(path): add_landlock_path(ruleset,path,read_file|(write_file if path=='/dev/null' else 0))
        add_landlock_path(ruleset,workspace,handled)
        syscall(SYS_LANDLOCK_RESTRICT_SELF,ruleset,0)
    finally:
        os.close(ruleset)

def seccomp():
    # Linux x86-64 syscall numbers.  Everything not listed remains available to
    # the already-running Python VM; Landlock controls path access.
    forbidden=(
        41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,288,  # sockets
        56,57,58,435,109,112,272,308,                     # clone/session/ns
        59,322,                                             # further exec
        62,200,234,                                         # signal other tasks
        101,155,161,165,166,169,175,176,246,248,249,250,
        298,304,313,321,323,                                # privileged kernel APIs
    )
    instructions=[
        (BPF_LD|BPF_W|BPF_ABS,0,0,4),
        (BPF_JMP|BPF_JEQ|BPF_K,1,0,AUDIT_ARCH_X86_64),
        (BPF_RET|BPF_K,0,0,SECCOMP_RET_KILL_PROCESS),
        (BPF_LD|BPF_W|BPF_ABS,0,0,0),
    ]
    for number in forbidden:
        instructions.append((BPF_JMP|BPF_JEQ|BPF_K,0,1,number))
        instructions.append((BPF_RET|BPF_K,0,0,SECCOMP_RET_ERRNO|errno.EPERM))
    instructions.append((BPF_RET|BPF_K,0,0,SECCOMP_RET_ALLOW))
    array=(SockFilter*len(instructions))(*[SockFilter(*item) for item in instructions])
    program=SockFprog(len(instructions),array)
    if libc.prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,ctypes.addressof(program),0,0)!=0:
        raise OSError(ctypes.get_errno(),'seccomp')

try:
    spec_fd=int(sys.argv[1]); source_fd=int(sys.argv[2]); broker_fd=int(sys.argv[3])
    spec=json.loads(read_all(spec_fd,65536).decode('utf-8'))
    source=read_all(source_fd,spec['maximum_source_bytes'])
    os.close(spec_fd); os.close(source_fd)
    import hashlib
    if hashlib.sha256(source).hexdigest()!=spec['source_digest']:
        raise RuntimeError('source_digest')
    code=compile(source.decode('utf-8'),'<hepta-skill>','exec',dont_inherit=True,optimize=2)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(spec['cpu_seconds'],spec['cpu_seconds']))
    resource.setrlimit(resource.RLIMIT_AS,(spec['address_space_bytes'],spec['address_space_bytes']))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    resource.setrlimit(resource.RLIMIT_NOFILE,(spec['open_files'],spec['open_files']))
    resource.setrlimit(resource.RLIMIT_NPROC,(1,1))
    os.umask(0o077)
    no_new_privs()
    landlock(spec['workspace'])
    seccomp()
    os.environ.clear()
    os.environ.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
                       'HEPTA_CAPABILITY_FD':str(broker_fd)})
    sys.argv=['hepta-skill']
    namespace={'__name__':'__main__','__file__':'<hepta-skill>'}
    exec(code,namespace,namespace)
except SystemExit as exc:
    value=exc.code
    if value not in (None,0):
        os.write(2,b'skill_runtime_failed\n')
        os._exit(70)
except BaseException:
    try: os.write(2,b'skill_runtime_failed\n')
    except BaseException: pass
    os._exit(70)
'''


def _sealed_memfd(name: str, raw: bytes, maximum: int) -> int:
    if (
        not hasattr(os, "memfd_create")
        or not hasattr(os, "MFD_ALLOW_SEALING")
        or len(raw) > maximum
    ):
        raise SkillSandboxError("skill_sandbox_platform_unsupported")
    import fcntl

    fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        view = memoryview(raw)
        while view:
            try:
                written = os.write(fd, view)
            except InterruptedError:
                continue
            if written <= 0:
                raise SkillSandboxError("skill_sandbox_io_failed")
            view = view[written:]
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(
            fd,
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SEAL,
        )
        return fd
    except BaseException:
        os.close(fd)
        raise


def _canonical(value: object, *, maximum: int, code: str) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        captured = json.loads(raw.decode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise SkillSandboxError(code) from None
    if len(raw) > maximum or not isinstance(captured, (dict, list)):
        raise SkillSandboxError(code)
    return raw


def _kill_group(process: subprocess.Popen[bytes]) -> None:
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


class _CapabilityBroker:
    def __init__(
        self,
        sock: socket.socket,
        *,
        allowed: frozenset[str],
        handler: Callable[[str, Mapping[str, object]], Mapping[str, object]],
        authorize: Callable[[], None],
        maximum_requests: int,
    ) -> None:
        self.sock = sock
        self.allowed = allowed
        self.handler = handler
        self.authorize = authorize
        self.maximum_requests = maximum_requests
        self.requests = 0
        self.error: str | None = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.thread.join(timeout=2)

    def _read_exact(self, length: int) -> bytes | None:
        data = bytearray()
        while len(data) < length and not self.stop.is_set():
            try:
                part = self.sock.recv(length - len(data))
            except socket.timeout:
                continue
            except OSError:
                return None
            if not part:
                return None
            data.extend(part)
        return bytes(data) if len(data) == length else None

    @staticmethod
    def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("duplicate")
            value[key] = child
        return value

    def _send(self, value: Mapping[str, object]) -> None:
        raw = _canonical(value, maximum=_MAX_FRAME_BYTES, code="skill_broker_response_invalid")
        self.sock.sendall(struct.pack(">I", len(raw)) + raw)

    def _run(self) -> None:
        self.sock.settimeout(0.1)
        try:
            while not self.stop.is_set():
                header = self._read_exact(4)
                if header is None:
                    return
                length = struct.unpack(">I", header)[0]
                if not 1 <= length <= _MAX_FRAME_BYTES:
                    raise SkillSandboxError("skill_broker_frame_invalid")
                raw = self._read_exact(length)
                if raw is None:
                    raise SkillSandboxError("skill_broker_frame_invalid")
                try:
                    request = json.loads(
                        raw.decode("utf-8"),
                        object_pairs_hook=self._object,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                    )
                except (ValueError, UnicodeError, json.JSONDecodeError):
                    raise SkillSandboxError("skill_broker_request_invalid") from None
                if (
                    type(request) is not dict
                    or set(request) != {"request_id", "capability", "arguments"}
                    or type(request["request_id"]) is not str
                    or _IDENTIFIER.fullmatch(request["request_id"]) is None
                    or type(request["capability"]) is not str
                    or _IDENTIFIER.fullmatch(request["capability"]) is None
                    or type(request["arguments"]) is not dict
                ):
                    raise SkillSandboxError("skill_broker_request_invalid")
                self.requests += 1
                if self.requests > self.maximum_requests:
                    raise SkillSandboxError("skill_broker_request_limit")
                capability = request["capability"]
                if capability not in self.allowed:
                    self._send(
                        {
                            "request_id": request["request_id"],
                            "ok": False,
                            "error": "capability_denied",
                        }
                    )
                    continue
                try:
                    self.authorize()
                    result = self.handler(capability, request["arguments"])
                    self.authorize()
                    if type(result) is not dict:
                        raise ValueError("result")
                    response = {
                        "request_id": request["request_id"],
                        "ok": True,
                        "result": result,
                    }
                except SkillSandboxError:
                    raise
                except Exception:
                    response = {
                        "request_id": request["request_id"],
                        "ok": False,
                        "error": "capability_unavailable",
                    }
                self._send(response)
        except SkillSandboxError as error:
            self.error = error.code
        except Exception:
            self.error = "skill_broker_failed"


class LinuxBrokerOnlySandbox:
    """Execute one source snapshot under mandatory kernel isolation."""

    def __init__(self, *, python_executable: str | None = None) -> None:
        executable = python_executable or sys.executable
        if (
            os.name != "posix"
            or platform.system() != "Linux"
            or platform.machine() not in {"x86_64", "amd64"}
            or type(executable) is not str
            or not Path(executable).is_absolute()
        ):
            raise SkillSandboxError("skill_sandbox_platform_unsupported")
        self.python_executable = str(Path(executable).resolve(strict=True))

    @staticmethod
    def _capabilities(values: Iterable[str]) -> frozenset[str]:
        try:
            result = frozenset(values)
        except TypeError:
            raise SkillSandboxError("skill_capability_policy_invalid") from None
        if len(result) > 64 or any(
            type(value) is not str or _IDENTIFIER.fullmatch(value) is None
            for value in result
        ):
            raise SkillSandboxError("skill_capability_policy_invalid")
        return result

    def execute(
        self,
        *,
        source: bytes,
        input_value: object,
        allowed_capabilities: Iterable[str],
        capability_handler: Callable[
            [str, Mapping[str, object]], Mapping[str, object]
        ],
        authorize: Callable[[], None],
        limits: SandboxLimits = SandboxLimits(),
    ) -> SandboxExecution:
        if (
            type(source) is not bytes
            or not source
            or len(source) > _MAX_SOURCE_BYTES
            or not isinstance(limits, SandboxLimits)
            or not callable(capability_handler)
            or not callable(authorize)
        ):
            raise SkillSandboxError("skill_sandbox_request_invalid")
        try:
            source.decode("utf-8")
        except UnicodeError:
            raise SkillSandboxError("skill_source_invalid") from None
        input_raw = _canonical(
            input_value, maximum=_MAX_INPUT_BYTES, code="skill_input_invalid"
        )
        allowed = self._capabilities(allowed_capabilities)
        authorize()
        spec_fd = source_fd = -1
        process: subprocess.Popen[bytes] | None = None
        parent_sock: socket.socket | None = None
        child_sock: socket.socket | None = None
        broker: _CapabilityBroker | None = None
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            temporary = tempfile.TemporaryDirectory(prefix="hepta-skill-")
            workspace = Path(temporary.name)
            workspace.chmod(0o700)
            spec = {
                "source_digest": hashlib.sha256(source).hexdigest(),
                "maximum_source_bytes": _MAX_SOURCE_BYTES,
                "workspace": str(workspace),
                "cpu_seconds": limits.cpu_seconds,
                "address_space_bytes": limits.address_space_bytes,
                "open_files": limits.open_files,
            }
            spec_fd = _sealed_memfd(
                "hepta-skill-spec",
                json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                65_536,
            )
            source_fd = _sealed_memfd(
                "hepta-skill-source", source, _MAX_SOURCE_BYTES
            )
            parent_sock, child_sock = socket.socketpair(
                socket.AF_UNIX, socket.SOCK_STREAM
            )
            parent_sock.set_inheritable(False)
            child_sock.set_inheritable(True)
            broker = _CapabilityBroker(
                parent_sock,
                allowed=allowed,
                handler=capability_handler,
                authorize=authorize,
                maximum_requests=limits.capability_requests,
            )
            try:
                process = subprocess.Popen(
                    [
                        self.python_executable,
                        "-I",
                        "-S",
                        "-B",
                        "-c",
                        _LAUNCHER,
                        str(spec_fd),
                        str(source_fd),
                        str(child_sock.fileno()),
                    ],
                    cwd=str(workspace),
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    pass_fds=(spec_fd, source_fd, child_sock.fileno()),
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError:
                raise SkillSandboxError("skill_sandbox_start_failed") from None
            child_sock.close()
            child_sock = None
            broker.start()
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            try:
                process.stdin.write(input_raw)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            output = {"stdout": bytearray(), "stderr": bytearray()}
            deadline = time.monotonic() + float(limits.wall_seconds)
            try:
                while selector.get_map() or process.poll() is None:
                    try:
                        authorize()
                    except Exception:
                        _kill_group(process)
                        raise SkillSandboxError("skill_authority_revoked") from None
                    if broker.error is not None:
                        _kill_group(process)
                        raise SkillSandboxError(broker.error)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _kill_group(process)
                        raise SkillSandboxError("skill_timeout")
                    for key, _ in selector.select(min(0.05, remaining)):
                        stream = key.fileobj
                        try:
                            chunk = os.read(stream.fileno(), 65_536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        output[key.data].extend(chunk)
                        if len(output["stdout"]) + len(output["stderr"]) > limits.output_bytes:
                            _kill_group(process)
                            raise SkillSandboxError("skill_output_exceeded")
                    if process.poll() is not None and not selector.get_map():
                        break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_group(process)
                    raise SkillSandboxError("skill_timeout")
                try:
                    return_code = process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    _kill_group(process)
                    raise SkillSandboxError("skill_timeout") from None
            finally:
                selector.close()
            if broker.error is not None:
                raise SkillSandboxError(broker.error)
            if return_code != 0:
                if output["stderr"].startswith(b"skill_runtime_failed"):
                    raise SkillSandboxError("skill_runtime_failed")
                raise SkillSandboxError("skill_sandbox_failed")
            if output["stderr"]:
                raise SkillSandboxError("skill_stderr_forbidden")
            try:
                result = json.loads(output["stdout"].decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise SkillSandboxError("skill_output_invalid") from None
            if type(result) is not dict:
                raise SkillSandboxError("skill_output_invalid")
            canonical = _canonical(
                result, maximum=limits.output_bytes, code="skill_output_invalid"
            )
            authorize()
            return SandboxExecution(
                output=result,
                capability_requests=broker.requests,
                stdout_digest=hashlib.sha256(canonical).hexdigest(),
            )
        finally:
            if process is not None and process.poll() is None:
                _kill_group(process)
            if broker is not None:
                broker.close()
            else:
                if parent_sock is not None:
                    parent_sock.close()
            if child_sock is not None:
                child_sock.close()
            for fd in (spec_fd, source_fd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            if temporary is not None:
                temporary.cleanup()
