"""Persistent, subject-bound realtime authority with monotonic revocation.

Admission contract: contracts/realtime-admission-v1.json. Provider methods are
trusted server-side adapters; they must honor deadlines and make revoke
idempotent. A provider lookup returning None is NOT proof of non-execution.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from services.control_plane.bounded_calls import BoundedCalls
from services.control_plane import realtime_recovery as recovery
from services.control_plane import realtime_provider_binding as provider_scope
from services.control_plane.durable_state import (
    DurableDatabase, deadline, identifier, timestamp,
)


class DurableRealtimeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RealtimeActivation:
    provider_session_id: str
    provider_receipt_id: str


class RealtimeProvider(Protocol):
    def activate(self, *, ticket: str, subject: str, session_id: str,
                 timeout_seconds: float) -> RealtimeActivation: ...
    def reconcile_activation(self, *, session_id: str,
                             timeout_seconds: float) -> RealtimeActivation | None: ...
    def revoke(self, *, provider_session_id: str, timeout_seconds: float) -> None: ...


class DurableRealtimeStore:
    def __init__(self, path: str, *, provider: RealtimeProvider, provider_binding: str, clock: Callable[[], int],
                 ticket_ttl_seconds: int = 60, maximum_records: int = 100000,
                 maximum_workers: int = 4, maximum_readbacks: int = 8,
                 maximum_revoke_attempts: int = 8):
        if type(ticket_ttl_seconds) is not int or not 1 <= ticket_ttl_seconds <= 300:
            raise ValueError("invalid ticket ttl")
        if type(maximum_records) is not int or not 1 <= maximum_records <= 1000000:
            raise ValueError("invalid record limit")
        if not callable(clock) or type(maximum_workers) is not int or not 1 <= maximum_workers <= 16:
            raise ValueError("realtime_configuration_invalid")
        recovery.checked_limits(maximum_readbacks, maximum_revoke_attempts)
        provider_scope.checked_binding(provider_binding)
        provider_scope.check_adapter(provider, provider_binding)
        self._provider, self._provider_binding = provider, provider_binding
        self.clock = clock
        self._storage = DurableDatabase(path)
        self.db, self.lock = self._storage.db, self._storage.lock
        self.ticket_ttl_seconds = ticket_ttl_seconds
        self.maximum_records = maximum_records
        self._calls = BoundedCalls(maximum_workers)
        try:
            with self._storage.transaction():
                unmarked = self._storage.version("realtime", provider_scope.VERSION)
                required = recovery.LEGACY_TABLES | recovery.BUDGET_TABLES | provider_scope.TABLES
                tables = {row[0] for row in self.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if unmarked and required & tables:
                    raise ValueError("realtime_unmarked_schema_rejected")
                if not unmarked and not required <= tables:
                    raise ValueError("realtime_schema_integrity_invalid")
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS tickets(ticket_digest TEXT PRIMARY KEY,"
                    "subject TEXT NOT NULL,session_id TEXT NOT NULL,expires_at INTEGER NOT NULL,"
                    "state TEXT NOT NULL)"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,"
                    "subject TEXT NOT NULL,state TEXT NOT NULL,generation INTEGER NOT NULL,"
                    "provider_session_id TEXT,provider_receipt_id TEXT)"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS realtime_attempts(session_id TEXT PRIMARY KEY,"
                    "attempt_id TEXT NOT NULL UNIQUE,subject TEXT NOT NULL,generation INTEGER NOT NULL)"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS realtime_revoke_outbox(job_id TEXT PRIMARY KEY,"
                    "session_id TEXT NOT NULL,provider_session_id TEXT,state TEXT NOT NULL)"
                )
                self.db.execute("CREATE INDEX IF NOT EXISTS realtime_ticket_session ON tickets(session_id)")
                self.db.execute("CREATE INDEX IF NOT EXISTS realtime_remote_session ON sessions(provider_session_id,session_id)")
                self.db.execute("CREATE INDEX IF NOT EXISTS realtime_remote_cleanup ON realtime_revoke_outbox(provider_session_id,session_id)")
                self.db.execute("CREATE INDEX IF NOT EXISTS realtime_cleanup_session ON realtime_revoke_outbox(session_id,state)")
                if unmarked:
                    recovery.create_budgets(self.db, maximum_readbacks, maximum_revoke_attempts)
                    provider_scope.create_scope(self.db, provider_binding)
                recovery.validate_budgets(self.db, maximum_readbacks, maximum_revoke_attempts)
                provider_scope.require_scope(self.db, provider_binding)
                self._storage.mark_version("realtime", provider_scope.VERSION)
        except BaseException:
            self.close()
            raise

    @property
    def provider(self) -> RealtimeProvider:
        return self._provider

    @property
    def provider_binding(self) -> str:
        return self._provider_binding

    def _scope(self) -> None:
        if self._storage.version("realtime", provider_scope.VERSION):
            raise ValueError("realtime_provider_scope_invalid")
        provider_scope.require_scope(self.db, self._provider_binding)

    def _checked_provider(self) -> RealtimeProvider:
        # Call under the local lock/transaction; never hold it for provider I/O.
        self._scope()
        provider_scope.check_adapter(self._provider, self._provider_binding)
        return self._provider

    def close(self) -> None:
        self._storage.close()

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise DurableRealtimeError("realtime_clock_invalid") from None
        if not timestamp(value):
            raise DurableRealtimeError("realtime_clock_invalid")
        return value

    def _window(self, expires_at: int, *, earliest: int = 0,
                until: float | None = None) -> int:
        now = self._now()
        if now < earliest:
            raise DurableRealtimeError("realtime_clock_rollback")
        if not timestamp(expires_at) or now >= expires_at:
            raise DurableRealtimeError("realtime_ticket_expired")
        if until is not None and time.monotonic() >= until:
            raise DurableRealtimeError("realtime_deadline_expired")
        return now

    def _attempt_expiry(self, session: sqlite3.Row) -> int:
        # Each one-shot session can consume exactly one ticket. Do not infer a
        # fresh expiry from constructor TTL or synthesize one for legacy state.
        rows = self.db.execute(
            "SELECT expires_at FROM tickets WHERE session_id=? AND subject=? "
            "AND state='consumed' LIMIT 2", (session["session_id"], session["subject"])).fetchall()
        if len(rows) != 1 or not timestamp(rows[0][0]):
            raise DurableRealtimeError("realtime_attempt_ticket_invalid")
        return rows[0][0]

    def _expire_pending(self, session: sqlite3.Row) -> None:
        # Called under a write transaction; invalid/expired admission is a
        # terminal local denial, but unknown remote work remains cleanup custody.
        if session["state"] not in ("activating", "indeterminate"):
            return
        try:
            self._window(self._attempt_expiry(session))
        except DurableRealtimeError:
            self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?",
                            (session["session_id"],))
            self._queue_revoke(session["session_id"], session["provider_session_id"])

    def _session(self, session_id: str) -> sqlite3.Row:
        self._scope()
        row = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise DurableRealtimeError("realtime_session_unknown")
        return row

    def issue_ticket(self, *, subject: str, session_id: str) -> str:
        if not identifier(subject) or not identifier(session_id):
            raise DurableRealtimeError("realtime_binding_invalid")
        ticket = secrets.token_urlsafe(32)
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        with self._storage.transaction():
            self._checked_provider()
            now = self._now()  # after lock waiting, never selected by the caller
            expires_at = now + self.ticket_ttl_seconds
            if not timestamp(expires_at):
                raise DurableRealtimeError("realtime_ticket_expiry_invalid")
            row = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is not None:
                if row["subject"] != subject:
                    raise DurableRealtimeError("realtime_subject_conflict")
                if row["state"] != "new":
                    raise DurableRealtimeError("realtime_session_not_new")
            if self.db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] >= self.maximum_records:
                raise DurableRealtimeError("realtime_capacity_exhausted")
            if row is None:
                self.db.execute("INSERT INTO sessions VALUES(?,?,'new',1,NULL,NULL)", (session_id, subject))
                self.db.execute("INSERT INTO realtime_lookup_budget VALUES(?,0)", (session_id,))
            else:
                recovery.usage(self.db, "lookup", session_id)
            self.db.execute(
                "UPDATE tickets SET state='superseded' WHERE session_id=? AND state='issued'",
                (session_id,),
            )
            self.db.execute("INSERT INTO tickets VALUES(?,?,?,?,?)",
                            (digest, subject, session_id, expires_at, "issued"))
            self._window(expires_at, earliest=now)
            self._checked_provider()
        return ticket

    def activate(self, *, ticket: str, subject: str, session_id: str,
                 timeout_seconds: float = 10) -> sqlite3.Row:
        if (not identifier(ticket, 512) or not identifier(subject) or not identifier(session_id)
                or not deadline(timeout_seconds)):
            raise DurableRealtimeError("realtime_binding_invalid")
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        attempt_id = secrets.token_hex(16)
        until = time.monotonic() + timeout_seconds
        with self._storage.transaction():
            self._checked_provider()
            now = self._now()
            ticket_row = self.db.execute("SELECT * FROM tickets WHERE ticket_digest=?", (digest,)).fetchone()
            if (ticket_row is None or ticket_row["subject"] != subject
                    or ticket_row["session_id"] != session_id):
                raise DurableRealtimeError("realtime_ticket_invalid")
            if ticket_row["expires_at"] <= now:
                raise DurableRealtimeError("realtime_ticket_expired")
            if ticket_row["state"] != "issued":
                raise DurableRealtimeError("realtime_ticket_replayed")
            session = self._session(session_id)
            if session["subject"] != subject or session["state"] != "new":
                raise DurableRealtimeError("realtime_session_not_new")
            recovery.usage(self.db, "lookup", session_id)
            generation = session["generation"]
            self.db.execute("UPDATE tickets SET state='consumed' WHERE ticket_digest=?", (digest,))
            self.db.execute("UPDATE tickets SET state='superseded' WHERE session_id=? AND state='issued'", (session_id,))
            self.db.execute("INSERT INTO realtime_attempts VALUES(?,?,?,?)",
                            (session_id, attempt_id, subject, generation))
            self.db.execute("UPDATE sessions SET state='activating' WHERE session_id=?", (session_id,))
            self._window(ticket_row["expires_at"], earliest=now, until=until)
            self._checked_provider()

        def dispatch() -> RealtimeActivation:
            with self._storage.transaction():
                current = self._session(session_id)
                attempt = self.db.execute("SELECT * FROM realtime_attempts WHERE session_id=?", (session_id,)).fetchone()
                if (current["state"] != "activating" or attempt is None
                        or attempt["attempt_id"] != attempt_id
                        or attempt["subject"] != current["subject"]
                        or attempt["generation"] != current["generation"]):
                    raise DurableRealtimeError("realtime_session_revoked_or_stale")
                fresh = self._window(self._attempt_expiry(current), earliest=now, until=until)
                provider = self._checked_provider()
            remaining = min(until - time.monotonic(), ticket_row["expires_at"] - fresh)
            if remaining <= 0:
                raise DurableRealtimeError("realtime_deadline_expired")
            return provider.activate(ticket=ticket, subject=subject, session_id=session_id,
                                          timeout_seconds=remaining)

        outcome = self._calls.run(dispatch, timeout_seconds=max(0.0, until - time.monotonic()))
        if outcome.state != "completed":
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_activation_indeterminate")
        return self._commit_activation(session_id, attempt_id, outcome.value, until=until, earliest=now)

    def _indeterminate(self, session_id: str, attempt_id: str) -> None:
        with self._storage.transaction():
            self.db.execute(
                "UPDATE sessions SET state='indeterminate' WHERE session_id=? AND state='activating' "
                "AND EXISTS(SELECT 1 FROM realtime_attempts WHERE session_id=? AND attempt_id=?)",
                (session_id, session_id, attempt_id),
            )
            self._expire_pending(self._session(session_id))

    def reconcile(self, session_id: str, *, timeout_seconds: float = 5) -> sqlite3.Row:
        if not identifier(session_id) or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_binding_invalid")
        until = time.monotonic() + timeout_seconds
        with self._storage.transaction():
            session = self._session(session_id)
            if session["state"] == "active":
                self._checked_provider()
                # Ticket expiry is an admission deadline, not a live-session TTL.
                return session
            if session["state"] not in ("activating", "indeterminate", "revoked"):
                raise DurableRealtimeError("realtime_reconcile_invalid")
            attempt = self.db.execute("SELECT * FROM realtime_attempts WHERE session_id=?", (session_id,)).fetchone()
            if attempt is None:
                if session["state"] == "revoked":
                    return session
                raise DurableRealtimeError("realtime_attempt_missing")
            attempt_id = attempt["attempt_id"]
            earliest = 0
            if session["state"] != "revoked":
                try:
                    earliest = self._now()
                except DurableRealtimeError:
                    pass  # _expire_pending must still persist denial on clock failure.
            self._expire_pending(session)
            admitted = recovery.reserve(self.db, "lookup", session_id)
        if not admitted:
            # Keep any expiry/revocation transaction committed even at exhaustion.
            raise DurableRealtimeError("realtime_readback_budget_exhausted")

        def lookup() -> RealtimeActivation | None:
            with self._storage.transaction():
                provider = self._checked_provider()
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise DurableRealtimeError("realtime_deadline_expired")
            return provider.reconcile_activation(session_id=session_id, timeout_seconds=remaining)

        outcome = self._calls.run(lookup, timeout_seconds=max(0.0, until - time.monotonic()))
        if outcome.state != "completed" or outcome.value is None:
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_activation_indeterminate")
        return self._commit_activation(session_id, attempt_id, outcome.value, until=until, earliest=earliest)

    def _remote_owned_elsewhere(self, session_id: str, provider_id: str) -> bool:
        # Check under the same write transaction as admission/cleanup. An ID
        # already bound to another local session is not ours to revoke.
        return bool(self.db.execute(
            "SELECT 1 FROM sessions WHERE provider_session_id=? AND session_id!=? LIMIT 1",
            (provider_id, session_id)).fetchone() or self.db.execute(
            "SELECT 1 FROM realtime_revoke_outbox WHERE provider_session_id=? AND session_id!=? LIMIT 1",
            (provider_id, session_id)).fetchone())

    def _queue_revoke(self, session_id: str, provider_id: str | None) -> str:
        if provider_id is not None and self._remote_owned_elsewhere(session_id, provider_id):
            # Do not turn a mismatched observation into authority to delete
            # another session. Retain this session's unresolved lookup instead.
            provider_id = None
        job_id = "provider:" + provider_id if provider_id else "lookup:" + session_id
        inserted = self.db.execute(
            "INSERT INTO realtime_revoke_outbox VALUES(?,?,?,'pending') "
            "ON CONFLICT(job_id) DO NOTHING", (job_id, session_id, provider_id)).rowcount
        existing = self.db.execute(
            "SELECT session_id,provider_session_id FROM realtime_revoke_outbox WHERE job_id=?",
            (job_id,)).fetchone()
        if tuple(existing) != (session_id, provider_id):
            raise ValueError("realtime_cleanup_binding_invalid")
        if provider_id is not None:
            if inserted:
                self.db.execute("INSERT INTO realtime_revoke_budget VALUES(?,0)", (job_id,))
            else:
                recovery.usage(self.db, "revoke", job_id)
        elif not inserted:
            # A newly unaccounted result can require lookup again, but the
            # existing persistent lookup allowance is never replenished.
            self.db.execute("UPDATE realtime_revoke_outbox SET state='pending' WHERE job_id=?", (job_id,))
        return job_id

    def _commit_activation(self, session_id: str, attempt_id: str,
                           activation: RealtimeActivation, *, until: float, earliest: int) -> sqlite3.Row:
        if (type(activation) is not RealtimeActivation
                or not identifier(activation.provider_session_id)
                or not identifier(activation.provider_receipt_id)):
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_provider_response_invalid")
        rejection = None
        cleanup = False
        cleanup_jobs: set[str] = set()
        with self._storage.transaction():
            self._checked_provider()
            session = self._session(session_id)
            attempt = self.db.execute("SELECT * FROM realtime_attempts WHERE session_id=?", (session_id,)).fetchone()
            exact = (attempt is not None and attempt["attempt_id"] == attempt_id
                     and attempt["subject"] == session["subject"]
                     and attempt["generation"] == session["generation"])
            other_owner = self._remote_owned_elsewhere(session_id, activation.provider_session_id)
            conflicting = (session["provider_session_id"] is not None
                           and (session["provider_session_id"], session["provider_receipt_id"])
                           != (activation.provider_session_id, activation.provider_receipt_id))
            if other_owner or conflicting:
                # An error alone would leave active authority and lose custody
                # of a second remote session. Commit terminal local denial and
                # every owned cleanup responsibility before raising the error.
                rejection = ("realtime_provider_owner_conflict" if other_owner
                             else "realtime_provider_identity_conflict")
                cleanup = True
                if session["state"] != "revoked":
                    self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?",
                                    (session_id,))
                self.db.execute("UPDATE tickets SET state='revoked' WHERE session_id=? AND state='issued'", (session_id,))
            elif session["state"] == "active":
                if not exact:
                    # A late identical activation result after a local interrupt
                    # must not revoke the current generation as a provider conflict.
                    raise DurableRealtimeError("realtime_session_revoked_or_stale")
                if time.monotonic() >= until:
                    raise DurableRealtimeError("realtime_deadline_expired")
                return session
            elif exact and session["state"] in ("activating", "indeterminate"):
                try:
                    expiry = self._attempt_expiry(session)
                    fresh = self._window(expiry, earliest=earliest, until=until)
                    self.db.execute(
                        "UPDATE sessions SET state='active',provider_session_id=?,provider_receipt_id=? "
                        "WHERE session_id=? AND subject=? AND generation=? AND state IN ('activating','indeterminate')",
                        (activation.provider_session_id, activation.provider_receipt_id, session_id,
                         attempt["subject"], attempt["generation"]),
                    )
                    self._window(expiry, earliest=fresh, until=until)
                    self._checked_provider()
                except DurableRealtimeError as error:
                    rejection = error.code
                    if error.code == "realtime_deadline_expired":
                        self.db.execute("UPDATE sessions SET state='indeterminate' WHERE session_id=?", (session_id,))
                    else:
                        cleanup = True
                        self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?", (session_id,))
            else:
                rejection = "realtime_session_revoked_or_stale"
                cleanup = True
            if cleanup:
                # Keep both the stored identity and newly observed identity. An
                # owner collision becomes lookup-only, never cross-session revoke.
                identities = {activation.provider_session_id}
                if session["provider_session_id"] is not None:
                    identities.add(session["provider_session_id"])
                unresolved = False
                for provider_id in sorted(identities):
                    job_id = self._queue_revoke(session_id, provider_id)
                    if job_id.startswith("provider:"):
                        cleanup_jobs.add(job_id)
                    else:
                        unresolved = True
                if not unresolved:
                    self.db.execute("UPDATE realtime_revoke_outbox SET state='completed' WHERE job_id=?",
                                    ("lookup:" + session_id,))
            result = self._session(session_id)
        if rejection is not None:
            for job_id in sorted(cleanup_jobs):
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                self._drain_known(job_id, remaining)
            raise DurableRealtimeError(rejection)
        return result

    def interrupt(self, session_id: str, *, generation: int) -> sqlite3.Row:
        with self._storage.transaction():
            self._checked_provider()
            row = self._session(session_id)
            if row["state"] != "active":
                raise DurableRealtimeError("realtime_session_not_active")
            if type(generation) is not int or row["generation"] != generation:
                raise DurableRealtimeError("stale_realtime_generation")
            self.db.execute("UPDATE sessions SET generation=generation+1 WHERE session_id=?", (session_id,))
            # Activation attempt is historical after interruption; no new activation is allowed.
            return self._session(session_id)

    def require_generation(self, session_id: str, generation: int) -> sqlite3.Row:
        with self.lock:
            self._checked_provider()
            row = self._session(session_id)
            if row["state"] != "active":
                raise DurableRealtimeError("realtime_session_not_active")
            if type(generation) is not int or row["generation"] != generation:
                raise DurableRealtimeError("stale_realtime_generation")
            return row

    def revoke(self, session_id: str, *, timeout_seconds: float = 5) -> None:
        if not identifier(session_id) or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_binding_invalid")
        until = time.monotonic() + timeout_seconds
        with self._storage.transaction():
            row = self._session(session_id)
            if row["state"] != "revoked":
                self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?", (session_id,))
            self.db.execute("UPDATE tickets SET state='revoked' WHERE session_id=? AND state='issued'", (session_id,))
            if row["provider_session_id"]:
                self._queue_revoke(session_id, row["provider_session_id"])
            elif row["state"] in ("activating", "indeterminate"):
                self._queue_revoke(session_id, None)
        # A conflicting observation can leave multiple known remote sessions.
        # Draining only sessions.provider_session_id would falsely acknowledge
        # completion while an alternate known cleanup is still pending.
        with self.lock:
            jobs = self.db.execute(
                "SELECT job_id FROM realtime_revoke_outbox WHERE session_id=? "
                "AND provider_session_id IS NOT NULL AND state='pending' ORDER BY job_id LIMIT 100",
                (session_id,)).fetchall()
        for job in jobs:
            remaining = until - time.monotonic()
            if remaining <= 0:
                break
            self._drain_known(job["job_id"], remaining)
        with self.lock:
            known_pending = self.db.execute(
                "SELECT 1 FROM realtime_revoke_outbox WHERE session_id=? "
                "AND provider_session_id IS NOT NULL AND state='pending' LIMIT 1", (session_id,)).fetchone()
        if known_pending:
            raise DurableRealtimeError("realtime_provider_revoke_pending")

    def _drain_known(self, job_id: str, timeout_seconds: float) -> bool:
        until = time.monotonic() + timeout_seconds
        with self._storage.transaction():
            self._scope()
            job = self.db.execute("SELECT * FROM realtime_revoke_outbox WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                raise ValueError("realtime_cleanup_job_missing")
            if job["state"] == "completed":
                return True
            if job["provider_session_id"] is None:
                return False
            if not recovery.reserve(self.db, "revoke", job_id):
                return False
            if self._remote_owned_elsewhere(job["session_id"], job["provider_session_id"]):
                # Ambiguous legacy custody cannot authorize deleting another
                # session. Charge this bounded attempt and retain pending work.
                return False
        def cleanup() -> None:
            with self._storage.transaction():
                provider = self._checked_provider()
                current = self.db.execute("SELECT * FROM realtime_revoke_outbox WHERE job_id=?", (job_id,)).fetchone()
                if (current is None or current["session_id"] != job["session_id"]
                        or current["provider_session_id"] != job["provider_session_id"]):
                    raise ValueError("realtime_cleanup_binding_invalid")
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise DurableRealtimeError("realtime_deadline_expired")
            return provider.revoke(provider_session_id=job["provider_session_id"], timeout_seconds=remaining)

        outcome = self._calls.run(cleanup, timeout_seconds=max(0.0, until - time.monotonic()))
        if outcome.state != "completed" or outcome.value is not None:
            # The trusted adapter contract returns None ONLY after successful
            # revoke/readback. False, error dictionaries and arbitrary payloads
            # are not success. This still is not independent provider evidence.
            return False
        with self._storage.transaction():
            self._checked_provider()
            current = self.db.execute("SELECT * FROM realtime_revoke_outbox WHERE job_id=?", (job_id,)).fetchone()
            if (current is None or current["session_id"] != job["session_id"]
                    or current["provider_session_id"] != job["provider_session_id"]):
                raise ValueError("realtime_cleanup_binding_invalid")
            self.db.execute("UPDATE realtime_revoke_outbox SET state='completed' WHERE job_id=?", (job_id,))
        return True

    def drain_revocations(self, *, limit: int = 20, timeout_seconds: float = 5) -> int:
        if type(limit) is not int or not 1 <= limit <= 100 or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_drain_invalid")
        until = time.monotonic() + timeout_seconds
        with self.lock:
            self._scope()
            jobs = recovery.eligible_jobs(self.db, limit)
        for job in jobs:
            remaining = until - time.monotonic()
            if remaining <= 0:
                break
            if job["provider_session_id"] is not None:
                self._drain_known(job["job_id"], remaining)
            else:
                try:
                    self.reconcile(job["session_id"], timeout_seconds=remaining)
                except DurableRealtimeError:
                    pass  # Pending is retained; operator retries without replaying activation.
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM realtime_revoke_outbox WHERE state='pending'").fetchone()[0]

    def recovery_status(self, session_id: str) -> dict[str, object]:
        """Operator metadata: exhausted work is pending, never a cleanup receipt."""
        if not identifier(session_id):
            raise DurableRealtimeError("realtime_binding_invalid")
        with self._storage.transaction():
            session = self._session(session_id)
            used, maximum = recovery.usage(self.db, "lookup", session_id)
            _, revoke_limit = recovery.limits(self.db)
            if self.db.execute(
                "SELECT 1 FROM realtime_revoke_outbox o LEFT JOIN realtime_revoke_budget b USING(job_id) "
                "WHERE o.session_id=? AND o.provider_session_id IS NOT NULL "
                "AND (b.used IS NULL OR typeof(b.used)!='integer' OR b.used<0 OR b.used>?) LIMIT 1",
                (session_id, revoke_limit)).fetchone():
                raise ValueError("realtime_recovery_counter_invalid")
            total, pending, spent, exhausted = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(o.state='pending'),0),COALESCE(SUM(b.used),0),"
                "COALESCE(SUM(o.state='pending' AND b.used>=?),0) "
                "FROM realtime_revoke_outbox o JOIN realtime_revoke_budget b USING(job_id) "
                "WHERE o.session_id=?", (revoke_limit, session_id)).fetchone()
            lookup_jobs, pending_lookup = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(state='pending'),0) FROM realtime_revoke_outbox "
                "WHERE session_id=? AND provider_session_id IS NULL", (session_id,)).fetchone()
            lookup_exhausted = pending_lookup if used >= maximum else 0
            return {"session_id": session_id, "state": session["state"],
                    "lookup": {"used": used, "limit": maximum, "exhausted": used >= maximum},
                    "cleanup": {"jobs": total + lookup_jobs, "pending": pending + pending_lookup,
                                "known_jobs": total, "known_pending": pending,
                                "lookup_jobs": lookup_jobs, "lookup_pending": pending_lookup,
                                "attempts": spent, "exhausted_pending": exhausted + lookup_exhausted,
                                "limit_per_job": revoke_limit},
                    "independent_evidence": False}

    def pending_recovery(self, *, limit: int = 100) -> list[str]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise DurableRealtimeError("realtime_recovery_limit_invalid")
        with self.lock:
            self._scope()
            return [row[0] for row in self.db.execute(
                "SELECT session_id FROM sessions WHERE state IN ('activating','indeterminate') "
                "UNION SELECT session_id FROM realtime_revoke_outbox WHERE state='pending' ORDER BY session_id LIMIT ?",
                (limit,),
            )]