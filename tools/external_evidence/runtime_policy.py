"""Trusted runtime boundary for complete external-evidence validation."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any, Callable


def install_runtime_policy(
    complete_closure: ModuleType,
    core: ModuleType,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Install one public current-time validator and one private test hook.

    The evidence submitter may control custody files, but must not control the
    verifier's clock or cryptographic executable. Public package, direct module,
    and CLI paths therefore use the current trusted system clock and the
    repository's fixed OpenSSL command selection. Deterministic unit tests use
    the separately returned private hook and can inject only their clock.
    """

    raw_validate = complete_closure.validate_bundle
    snapshot_validate = core.validation_snapshot(raw_validate)

    def _require_canonical_openssl(value: str) -> None:
        if value != "openssl":
            core.fail(
                "custom OpenSSL executable selection is prohibited on the "
                "authority-bearing validation path"
            )

    @wraps(raw_validate)
    def validate_bundle(*args: Any, **kwargs: Any) -> Any:
        supplied_now = kwargs.pop("now", None)
        if supplied_now is not None:
            core.fail(
                "caller-supplied validation time is prohibited on the "
                "authority-bearing validation path"
            )
        openssl_binary = kwargs.pop("openssl_binary", "openssl")
        _require_canonical_openssl(openssl_binary)
        return snapshot_validate(
            *args,
            **kwargs,
            openssl_binary="openssl",
            now=datetime.now(timezone.utc),
        )

    @wraps(raw_validate)
    def validate_bundle_at_for_tests(*args: Any, **kwargs: Any) -> Any:
        if "now" not in kwargs or kwargs["now"] is None:
            raise TypeError("private deterministic validation requires now")
        openssl_binary = kwargs.pop("openssl_binary", "openssl")
        _require_canonical_openssl(openssl_binary)
        return snapshot_validate(
            *args,
            **kwargs,
            openssl_binary="openssl",
        )

    complete_closure.validate_bundle = validate_bundle
    complete_closure._validate_bundle_at_for_tests = validate_bundle_at_for_tests
    return validate_bundle, validate_bundle_at_for_tests
