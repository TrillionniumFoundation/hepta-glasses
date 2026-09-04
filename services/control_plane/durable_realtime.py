"""Persistent, subject-bound realtime authority with monotonic revocation.

Source contract: contracts/realtime-speech-custody-v2.json. Provider methods are
trusted server-side adapters; they must honor deadlines and make revoke
idempotent. A provider lookup returning None is NOT proof of non-execution.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from services.control_plane.bounded_calls import BoundedCalls
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
    def __init__(self, path: str, *, provider: RealtimeProvider,
                 ticket_ttl_seconds: int = 60, maximum_records: int = 100000,
                 maximum_workers: int = 4):
        if type(ticket_ttl_seconds) is not int or not 1 <= ticket_ttl_seconds <= 300:
            raise ValueError("invalid ticket ttl")
        if type(maximum_records) is not int or maximum_records < 1:
            raise ValueError("invalid record limit")
        self._storage = DurableDatabase(path)
        self.db, self.lock = self._storage.db, self._storage.lock
        self.provider = provider
        self.ticket_ttl_seconds = ticket_ttl_seconds
        self.maximum_records = maximum_records
        self._calls = BoundedCalls(maximum_workers)
        try:
            with self._storage.transaction():
                legacy = self._storage.version("realtime", 2)
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
                if legacy:
                    # Old unspent tickets have no attempt custody: invalidate, never reinterpret.
                    self.db.execute("UPDATE tickets SET state='superseded' WHERE state='issued'")
                    self.db.execute(
                        "INSERT OR IGNORE INTO realtime_attempts "
                        "SELECT session_id,lower(hex(randomblob(16))),subject,generation "
                        "FROM sessions WHERE state IN ('activating','indeterminate')"
                    )
                self._storage.mark_version("realtime", 2)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._storage.close()

    def _session(self, session_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise DurableRealtimeError("realtime_session_unknown")
        return row

    def issue_ticket(self, *, subject: str, session_id: str, now: int) -> str:
        if not identifier(subject) or not identifier(session_id) or not timestamp(now):
            raise DurableRealtimeError("realtime_binding_invalid")
        ticket = secrets.token_urlsafe(32)
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        with self._storage.transaction():
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
            self.db.execute(
                "UPDATE tickets SET state='superseded' WHERE session_id=? AND state='issued'",
                (session_id,),
            )
            self.db.execute("INSERT INTO tickets VALUES(?,?,?,?,?)",
                            (digest, subject, session_id, now + self.ticket_ttl_seconds, "issued"))
        return ticket

    def activate(self, *, ticket: str, subject: str, session_id: str, now: int,
                 timeout_seconds: float = 10) -> sqlite3.Row:
        if (not identifier(ticket, 512) or not identifier(subject) or not identifier(session_id)
                or not timestamp(now) or not deadline(timeout_seconds)):
            raise DurableRealtimeError("realtime_binding_invalid")
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        attempt_id = secrets.token_hex(16)
        with self._storage.transaction():
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
            generation = session["generation"]
            self.db.execute("UPDATE tickets SET state='consumed' WHERE ticket_digest=?", (digest,))
            self.db.execute("UPDATE tickets SET state='superseded' WHERE session_id=? AND state='issued'", (session_id,))
            self.db.execute("INSERT INTO realtime_attempts VALUES(?,?,?,?)",
                            (session_id, attempt_id, subject, generation))
            self.db.execute("UPDATE sessions SET state='activating' WHERE session_id=?", (session_id,))
        outcome = self._calls.run(
            lambda: self.provider.activate(ticket=ticket, subject=subject, session_id=session_id,
                                           timeout_seconds=timeout_seconds),
            timeout_seconds=timeout_seconds,
        )
        if outcome.state != "completed":
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_activation_indeterminate")
        return self._commit_activation(session_id, attempt_id, outcome.value, timeout_seconds)

    def _indeterminate(self, session_id: str, attempt_id: str) -> None:
        with self._storage.transaction():
            self.db.execute(
                "UPDATE sessions SET state='indeterminate' WHERE session_id=? AND state='activating' "
                "AND EXISTS(SELECT 1 FROM realtime_attempts WHERE session_id=? AND attempt_id=?)",
                (session_id, session_id, attempt_id),
            )

    def reconcile(self, session_id: str, *, timeout_seconds: float = 5) -> sqlite3.Row:
        if not identifier(session_id) or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_binding_invalid")
        with self.lock:
            session = self._session(session_id)
            if session["state"] == "active":
                return session
            if session["state"] not in ("activating", "indeterminate", "revoked"):
                raise DurableRealtimeError("realtime_reconcile_invalid")
            attempt = self.db.execute("SELECT * FROM realtime_attempts WHERE session_id=?", (session_id,)).fetchone()
            if attempt is None:
                if session["state"] == "revoked":
                    return session
                raise DurableRealtimeError("realtime_attempt_missing")
            attempt_id = attempt["attempt_id"]
        outcome = self._calls.run(
            lambda: self.provider.reconcile_activation(session_id=session_id, timeout_seconds=timeout_seconds),
            timeout_seconds=timeout_seconds,
        )
        if outcome.state != "completed" or outcome.value is None:
            # Includes the crash window after preparation and before/after remote creation.
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_activation_indeterminate")
        return self._commit_activation(session_id, attempt_id, outcome.value, timeout_seconds)

    def _queue_revoke(self, session_id: str, provider_id: str | None) -> None:
        job_id = "provider:" + provider_id if provider_id else "lookup:" + session_id
        self.db.execute("INSERT OR IGNORE INTO realtime_revoke_outbox VALUES(?,?,?,'pending')",
                        (job_id, session_id, provider_id))

    def _commit_activation(self, session_id: str, attempt_id: str,
                           activation: RealtimeActivation, timeout_seconds: float) -> sqlite3.Row:
        if (not isinstance(activation, RealtimeActivation)
                or not identifier(activation.provider_session_id)
                or not identifier(activation.provider_receipt_id)):
            self._indeterminate(session_id, attempt_id)
            raise DurableRealtimeError("realtime_provider_response_invalid")
        rejected = False
        with self._storage.transaction():
            session = self._session(session_id)
            attempt = self.db.execute("SELECT * FROM realtime_attempts WHERE session_id=?", (session_id,)).fetchone()
            exact = (attempt is not None and attempt["attempt_id"] == attempt_id
                     and attempt["subject"] == session["subject"]
                     and attempt["generation"] == session["generation"])
            if session["state"] == "active":
                if (not exact or session["provider_session_id"] != activation.provider_session_id
                        or session["provider_receipt_id"] != activation.provider_receipt_id):
                    raise DurableRealtimeError("realtime_provider_identity_conflict")
                return session
            if exact and session["state"] in ("activating", "indeterminate"):
                self.db.execute(
                    "UPDATE sessions SET state='active',provider_session_id=?,provider_receipt_id=? "
                    "WHERE session_id=? AND subject=? AND generation=? AND state IN ('activating','indeterminate')",
                    (activation.provider_session_id, activation.provider_receipt_id, session_id,
                     attempt["subject"], attempt["generation"]),
                )
            else:
                # A late provider result is cleanup work, never restored authority.
                rejected = True
                self._queue_revoke(session_id, activation.provider_session_id)
                self.db.execute("UPDATE realtime_revoke_outbox SET state='completed' WHERE job_id=?",
                                ("lookup:" + session_id,))
            result = self._session(session_id)
        if rejected:
            self._drain_known("provider:" + activation.provider_session_id, timeout_seconds)
            raise DurableRealtimeError("realtime_session_revoked_or_stale")
        return result

    def interrupt(self, session_id: str, *, generation: int) -> sqlite3.Row:
        with self._storage.transaction():
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
            row = self._session(session_id)
            if row["state"] != "active":
                raise DurableRealtimeError("realtime_session_not_active")
            if type(generation) is not int or row["generation"] != generation:
                raise DurableRealtimeError("stale_realtime_generation")
            return row

    def revoke(self, session_id: str, *, timeout_seconds: float = 5) -> None:
        if not identifier(session_id) or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_binding_invalid")
        with self._storage.transaction():
            row = self._session(session_id)
            if row["state"] != "revoked":
                self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?", (session_id,))
            self.db.execute("UPDATE tickets SET state='revoked' WHERE session_id=? AND state='issued'", (session_id,))
            if row["provider_session_id"]:
                self._queue_revoke(session_id, row["provider_session_id"])
            elif row["state"] in ("activating", "indeterminate"):
                self._queue_revoke(session_id, None)
        if row["provider_session_id"]:
            if not self._drain_known("provider:" + row["provider_session_id"], timeout_seconds):
                raise DurableRealtimeError("realtime_provider_revoke_pending")

    def _drain_known(self, job_id: str, timeout_seconds: float) -> bool:
        with self.lock:
            job = self.db.execute("SELECT * FROM realtime_revoke_outbox WHERE job_id=?", (job_id,)).fetchone()
            if job is None or job["state"] == "completed":
                return True
            if job["provider_session_id"] is None:
                return False
        outcome = self._calls.run(
            lambda: self.provider.revoke(provider_session_id=job["provider_session_id"], timeout_seconds=timeout_seconds),
            timeout_seconds=timeout_seconds,
        )
        if outcome.state != "completed":
            return False
        with self._storage.transaction():
            self.db.execute("UPDATE realtime_revoke_outbox SET state='completed' WHERE job_id=?", (job_id,))
        return True

    def drain_revocations(self, *, limit: int = 20, timeout_seconds: float = 5) -> int:
        if type(limit) is not int or not 1 <= limit <= 100 or not deadline(timeout_seconds):
            raise DurableRealtimeError("realtime_drain_invalid")
        with self.lock:
            jobs = self.db.execute(
                "SELECT * FROM realtime_revoke_outbox WHERE state='pending' ORDER BY job_id LIMIT ?", (limit,)
            ).fetchall()
        for job in jobs:
            if job["provider_session_id"] is not None:
                self._drain_known(job["job_id"], timeout_seconds)
            else:
                try:
                    self.reconcile(job["session_id"], timeout_seconds=timeout_seconds)
                except DurableRealtimeError:
                    pass  # Pending is retained; operator retries without replaying activation.
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM realtime_revoke_outbox WHERE state='pending'").fetchone()[0]

    def pending_recovery(self, *, limit: int = 100) -> list[str]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise DurableRealtimeError("realtime_recovery_limit_invalid")
        with self.lock:
            return [row[0] for row in self.db.execute(
                "SELECT session_id FROM sessions WHERE state IN ('activating','indeterminate') "
                "UNION SELECT session_id FROM realtime_revoke_outbox WHERE state='pending' ORDER BY session_id LIMIT ?",
                (limit,),
            )]
