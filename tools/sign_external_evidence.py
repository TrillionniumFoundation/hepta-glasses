#!/usr/bin/env python3
"""Compatibility CLI for authenticated external-evidence signing."""

from __future__ import annotations

from tools.external_evidence.signing import (
    _read_private_key_snapshot,
    contract_revision,
    finalize,
    main,
    normalize_time,
    parser,
    read_bundle,
    sign_ed25519,
    sign_reviewer,
    sign_submission,
    verify_private_key_ed25519,
    write_signature,
)

__all__ = [
    "_read_private_key_snapshot",
    "contract_revision",
    "finalize",
    "main",
    "normalize_time",
    "parser",
    "read_bundle",
    "sign_ed25519",
    "sign_reviewer",
    "sign_submission",
    "verify_private_key_ed25519",
    "write_signature",
]


if __name__ == "__main__":
    raise SystemExit(main())
