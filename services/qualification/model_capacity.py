"""Operator-only, aggregate capacity diagnostics for model-gateway schema v2.

No HTTP ingress, provider call, deletion, migration, retry, quota refund or
admission authority is provided. Use an operator-approved local database path.
The source model-gateway policy remains normative; this observer never changes
it. Normal SQLite WAL read-sidecar behavior is not a disk-immutability promise.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import stat
import sys
import time
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {
    "hepta_component_schema": {"component", "version"},
    "model_policy": {"id", "policy", "last_time", "suspended"},
    "requests": {"subject", "idempotency_key", "fingerprint", "session_id", "day",
                 "state", "expires_at", "request_key", "claim", "claim_until",
                 "readbacks", "answer_digest", "provider_request_id", "provider_receipt_id"},
    "revoked_sessions": {"subject", "session_id"},
    "model_cancellations": {"subject", "idempotency_key"},
    "model_events": {"sequence", "event", "request_key", "observed_at"},
}
POLICY_LIMITS = {"daily_requests": 10000, "question_chars": 8000,
                 "entries": 10000, "readbacks": 8, "workers": 16}


class CapacityObservationError(ValueError):
    """Fixed safe error code; never echo a database path or stored values."""


def _fail(code: str = "model_capacity_unavailable") -> None:
    raise CapacityObservationError(code)


def _policy(raw: object) -> dict[str, Any]:
    if type(raw) is not bytes or len(raw) > 4096:
        _fail("model_capacity_policy_invalid")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail("model_capacity_policy_invalid")
            result[key] = value
        return result

    document = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: _fail("model_capacity_policy_invalid"))
    if type(document) is not dict or set(document) != {*POLICY_LIMITS, "provider"}:
        _fail("model_capacity_policy_invalid")
    for key, maximum in POLICY_LIMITS.items():
        if type(document[key]) is not int or not 1 <= document[key] <= maximum:
            _fail("model_capacity_policy_invalid")
    if type(document["provider"]) is not str or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", document["provider"]
    ) is None:
        _fail("model_capacity_policy_invalid")
    return document


def _capacity(used: int, limit: int) -> dict[str, int | str]:
    level = ("exhausted" if used >= limit else
             "critical" if used * 100 >= limit * 95 else
             "warning" if used * 100 >= limit * 80 else "normal")
    return {"used": used, "limit": limit, "remaining": max(0, limit - used),
            "utilization_basis_points": used * 10000 // limit, "level": level}


def read_snapshot(path: Path, *, timeout_seconds: float = 2.0) -> dict[str, Any]:
    """Read one SQLite snapshot. Missing authority state is an error, not zero.

    A 0 < timeout <= 5 second monotonic budget bounds SQLite lock/VM waiting on
    a best-effort basis. It cannot interrupt an arbitrary stalled filesystem.
    The parent directory and SQLite runtime are trusted operational dependencies;
    no hostile-directory or whole-file anti-rollback guarantee is claimed.
    """
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 5:
        _fail("model_capacity_budget_invalid")
    db: sqlite3.Connection | None = None
    try:
        path = Path(path)
        if not path.is_absolute() or ".." in path.parts:
            _fail("model_capacity_path_invalid")
        if any(part.is_symlink() for part in (path, *path.parents)):
            _fail("model_capacity_path_invalid")
        if not stat.S_ISREG(path.stat().st_mode):
            _fail("model_capacity_path_invalid")
        end = time.monotonic() + timeout_seconds
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                             timeout=timeout_seconds, isolation_level=None)
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.set_progress_handler(lambda: int(time.monotonic() >= end), 500)
        db.execute("BEGIN")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not set(REQUIRED_COLUMNS) <= tables:
            _fail("model_capacity_schema_invalid")
        for table, expected in REQUIRED_COLUMNS.items():
            # Table names are fixed source constants, never operator input.
            columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            if not expected <= columns:
                _fail("model_capacity_schema_invalid")
        versions = db.execute(
            "SELECT version FROM hepta_component_schema WHERE component='model_gateway'"
        ).fetchmany(2)
        if versions != [(2,)]:
            _fail("model_capacity_schema_invalid")
        rows = db.execute("SELECT id,policy,last_time,suspended FROM model_policy").fetchmany(2)
        if len(rows) != 1 or rows[0][0] != 1 or type(rows[0][2]) is not int or not 0 <= rows[0][2] <= 253402300799 or rows[0][3] not in (0, 1):
            _fail("model_capacity_policy_invalid")
        policy = _policy(rows[0][1])
        counts = db.execute(
            "SELECT COUNT(*),"
            "COALESCE(SUM(state='prepared'),0),COALESCE(SUM(state='indeterminate'),0),"
            "COALESCE(SUM(state='committed'),0),COALESCE(SUM(state='cancelled'),0),"
            "COALESCE(SUM(state IN ('prepared','indeterminate') AND readbacks>=?),0),"
            "COALESCE(SUM(state IS NULL OR state NOT IN ('prepared','indeterminate','committed','cancelled') "
            "OR typeof(readbacks)<>'integer' OR readbacks<0 OR readbacks>?),0) FROM requests",
            (policy["readbacks"], policy["readbacks"]),
        ).fetchone()
        if counts is None or counts[6] != 0:
            _fail("model_capacity_state_invalid")
        revoked = db.execute("SELECT COUNT(*) FROM revoked_sessions").fetchone()[0]
        cancelled = db.execute("SELECT COUNT(*) FROM model_cancellations").fetchone()[0]
        events = db.execute("SELECT COUNT(*) FROM model_events").fetchone()[0]
        if time.monotonic() >= end:
            _fail("model_capacity_deadline_exceeded")
        requests = _capacity(counts[0], policy["entries"])
        denials = _capacity(revoked + cancelled, policy["entries"])
        suspended = rows[0][3] == 1
        return {
            "schema_version": 1, "component": "model_gateway", "storage_version": 2,
            "scope": "local_aggregate_snapshot", "admission_authority": False,
            "release_authority": False, "suspended": suspended,
            "requests": requests, "denials": denials, "event_rows": events,
            "states": dict(zip(("prepared", "indeterminate", "committed", "cancelled"), counts[1:5])),
            "unresolved_readback_exhausted": counts[5],
            "operator_attention_required": suspended or counts[5] > 0 or
                requests["level"] != "normal" or denials["level"] != "normal",
        }
    except CapacityObservationError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        raise CapacityObservationError("model_capacity_unavailable") from None
    finally:
        if db is not None:
            db.set_progress_handler(None, 0)
            db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    try:
        result = read_snapshot(args.database, timeout_seconds=args.timeout_seconds)
    except CapacityObservationError as error:
        print(json.dumps({"ok": False, "code": str(error), "release_authority": False}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
