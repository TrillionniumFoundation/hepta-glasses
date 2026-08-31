#!/usr/bin/env python3
"""Run the G13 controller with bounded GitHub API rate-limit recovery."""
from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ops import g13_controller as controller

_ORIGINAL_RUN = controller.run
_MAX_RATE_LIMIT_ATTEMPTS = 90


def _is_rate_limit_failure(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return (
        "rate limit exceeded" in text
        or "secondary rate limit" in text
        or "abuse detection mechanism" in text
    )


def resilient_run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> Any:
    is_github_api = len(command) >= 2 and command[0] == "gh" and command[1] == "api"
    if not is_github_api:
        return _ORIGINAL_RUN(
            command,
            cwd=cwd,
            check=check,
            capture=capture,
            input_text=input_text,
            env=env,
        )

    last_result = None
    for attempt in range(1, _MAX_RATE_LIMIT_ATTEMPTS + 1):
        result = _ORIGINAL_RUN(
            command,
            cwd=cwd,
            check=False,
            capture=True,
            input_text=input_text,
            env=env,
        )
        last_result = result
        if result.returncode == 0:
            if not capture:
                sys.stdout.write(result.stdout)
                sys.stderr.write(result.stderr)
            return result

        if not _is_rate_limit_failure(result.stdout, result.stderr):
            if check:
                if capture:
                    sys.stdout.write(result.stdout)
                    sys.stderr.write(result.stderr)
                raise controller.ConvergenceError(
                    f"command failed ({result.returncode}): {' '.join(command)}"
                )
            return result

        if attempt == _MAX_RATE_LIMIT_ATTEMPTS:
            break
        delay = min(60, 10 * attempt)
        print(
            f"::warning::GitHub API rate limit encountered; retry "
            f"{attempt}/{_MAX_RATE_LIMIT_ATTEMPTS} in {delay}s",
            flush=True,
        )
        time.sleep(delay)

    assert last_result is not None
    if check:
        if capture:
            sys.stdout.write(last_result.stdout)
            sys.stderr.write(last_result.stderr)
        raise controller.ConvergenceError(
            f"command failed after rate-limit recovery "
            f"({last_result.returncode}): {' '.join(command)}"
        )
    return last_result


controller.run = resilient_run
raise SystemExit(controller.main())
