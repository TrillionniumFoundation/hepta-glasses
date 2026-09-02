"""Trusted OpenSSL executable and subprocess-environment policy.

Authority-bearing verification and signing must not inherit executable selection
from ``PATH`` or dynamic-loader/OpenSSL configuration from the invoking
environment. The supported verifier therefore executes one root-owned,
non-writable system binary by absolute path under a minimal deterministic
environment and a deliberately narrow subprocess API.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

_TRUSTED_OPENSSL = Path("/usr/bin/openssl")
_TRUSTED_ENVIRONMENT = {
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "OPENSSL_CONF": "/dev/null",
    "PATH": "/usr/bin:/bin",
    "TZ": "UTC",
}
_ALLOWED_RUN_KEYWORDS = frozenset(
    {
        "capture_output",
        "check",
        "encoding",
        "errors",
        "input",
        "stderr",
        "stdin",
        "stdout",
        "text",
        "timeout",
    }
)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_root_owned_non_writable(
    path: Path,
    *,
    directory: bool,
    fail: Callable[[str], Any],
) -> os.stat_result:
    try:
        value = os.lstat(path)
    except OSError as error:
        fail(f"trusted OpenSSL path component {path} is unavailable: {error}")
    expected = stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)
    if not expected:
        kind = "directory" if directory else "regular file"
        fail(f"trusted OpenSSL path component {path} must be a real {kind}")
    if value.st_uid != 0:
        fail(f"trusted OpenSSL path component {path} must be owned by root")
    if value.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        fail(
            f"trusted OpenSSL path component {path} must not be group/world writable"
        )
    return value


def trusted_openssl_path(*, fail: Callable[[str], Any]) -> str:
    """Return the verified absolute OpenSSL path or fail closed.

    Every ancestor is a root-owned, non-group/world-writable real directory.
    The final executable is a root-owned, non-writable regular file opened with
    no-follow semantics, and its lexical/opened/post-check identities must
    agree. A caller cannot substitute a same-name program through ``PATH``.
    """

    if not hasattr(os, "O_NOFOLLOW"):
        fail("platform cannot securely open the trusted OpenSSL executable")
    for directory in reversed(_TRUSTED_OPENSSL.parents):
        _require_root_owned_non_writable(
            directory,
            directory=True,
            fail=fail,
        )
    lexical_before = _require_root_owned_non_writable(
        _TRUSTED_OPENSSL,
        directory=False,
        fail=fail,
    )
    if not lexical_before.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        fail("trusted OpenSSL executable is not executable")

    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(_TRUSTED_OPENSSL, flags)
    except OSError as error:
        fail(f"trusted OpenSSL executable cannot be opened safely: {error}")
    try:
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    lexical_after = _require_root_owned_non_writable(
        _TRUSTED_OPENSSL,
        directory=False,
        fail=fail,
    )
    if _identity(opened) != _identity(lexical_before):
        fail("trusted OpenSSL executable changed between inspection and open")
    if _identity(lexical_after) != _identity(opened):
        fail("trusted OpenSSL executable changed after open")
    return os.fspath(_TRUSTED_OPENSSL)


def trusted_subprocess_environment() -> dict[str, str]:
    """Return a fresh environment without loader or OpenSSL injection knobs."""

    return dict(_TRUSTED_ENVIRONMENT)


def _canonical_command(
    command: Sequence[Any],
    *,
    fail: Callable[[str], Any],
) -> list[str]:
    if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
        fail("OpenSSL command must be an argument sequence")
    values: list[str] = []
    for index, item in enumerate(command):
        try:
            value = os.fspath(item)
        except TypeError:
            fail(f"OpenSSL command argument {index} is not path/string-like")
        if not isinstance(value, str):
            fail(f"OpenSSL command argument {index} must be text")
        if "\x00" in value:
            fail(f"OpenSSL command argument {index} contains NUL")
        values.append(value)
    if not values:
        fail("OpenSSL command must not be empty")
    return values


class _TrustedOpenSSLSubprocess:
    _hepta_trusted_openssl_proxy = True

    def __init__(
        self,
        real: ModuleType,
        *,
        fail: Callable[[str], Any],
    ) -> None:
        self._real = real
        self._fail = fail

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def run(
        self,
        command: Sequence[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        values = _canonical_command(command, fail=self._fail)
        if args:
            self._fail(
                "positional subprocess options are prohibited for OpenSSL"
            )
        if kwargs.get("shell"):
            self._fail("shell execution is prohibited for OpenSSL")
        if "executable" in kwargs and kwargs["executable"] is not None:
            self._fail("subprocess executable override is prohibited for OpenSSL")
        if "env" in kwargs:
            self._fail(
                "caller-supplied subprocess environment is prohibited for OpenSSL"
            )
        unknown = sorted(set(kwargs) - _ALLOWED_RUN_KEYWORDS)
        if unknown:
            self._fail(
                "unsupported OpenSSL subprocess options are prohibited: "
                f"{unknown}"
            )

        trusted = trusted_openssl_path(fail=self._fail)
        requested = values[0]
        if requested not in {"openssl", trusted}:
            self._fail(
                "custom OpenSSL executable selection is prohibited on the "
                "authority-bearing path"
            )
        values[0] = trusted
        return self._real.run(
            values,
            env=trusted_subprocess_environment(),
            **kwargs,
        )


def _proxy(real: Any, *, fail: Callable[[str], Any]) -> Any:
    if getattr(real, "_hepta_trusted_openssl_proxy", False):
        return real
    return _TrustedOpenSSLSubprocess(real, fail=fail)


def install_core_openssl_policy(core: ModuleType) -> None:
    """Install the absolute-path resolver and sanitized subprocess proxy."""

    def resolve(requested: str) -> str:
        if requested != "openssl":
            core.fail(
                "custom OpenSSL executable selection is prohibited on the "
                "authority-bearing path"
            )
        return trusted_openssl_path(fail=core.fail)

    core._resolve_openssl = resolve
    core.subprocess = _proxy(core.subprocess, fail=core.fail)
    core.TRUSTED_OPENSSL_PATH = os.fspath(_TRUSTED_OPENSSL)


def install_signing_io_openssl_policy(
    signing_io: ModuleType,
    core: ModuleType,
) -> None:
    """Apply the same subprocess policy to private-key checks and signing."""

    signing_io.subprocess = _proxy(signing_io.subprocess, fail=core.fail)


__all__ = [
    "install_core_openssl_policy",
    "install_signing_io_openssl_policy",
    "trusted_openssl_path",
    "trusted_subprocess_environment",
]
