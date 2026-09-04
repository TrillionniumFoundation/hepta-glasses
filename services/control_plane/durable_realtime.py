"""Durable realtime session/ticket custody with single-use bootstrap semantics."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class DurableRealtimeError(ValueError):
    def __init__(self, code: str): super().__init__(code); self.code=code


@dataclass(frozen=True)
class RealtimeActivation:
    provider_session_id: str
    provider_receipt_id: str


class RealtimeProvider(Protocol):
    def activate(self, *, ticket: str, subject: str, session_id: str, timeout_seconds: float) -> RealtimeActivation: ...
    def reconcile_activation(self, *, session_id: str, timeout_seconds: float) -> RealtimeActivation | None: ...
    def revoke(self, *, provider_session_id: str, timeout_seconds: float) -> None: ...


class DurableRealtimeStore:
    def __init__(self,path:str,*,provider:RealtimeProvider,ticket_ttl_seconds:int=60):
        if ticket_ttl_seconds<1 or ticket_ttl_seconds>300: raise ValueError("invalid ticket ttl")
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,isolation_level=None,check_same_thread=False); self.db.row_factory=sqlite3.Row
        for p in ("PRAGMA journal_mode=WAL","PRAGMA synchronous=FULL"): self.db.execute(p)
        self.provider=provider; self.ticket_ttl_seconds=ticket_ttl_seconds; self.lock=threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS tickets(ticket_digest TEXT PRIMARY KEY,subject TEXT NOT NULL,session_id TEXT NOT NULL,expires_at INTEGER NOT NULL,state TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,subject TEXT NOT NULL,state TEXT NOT NULL,generation INTEGER NOT NULL,provider_session_id TEXT,provider_receipt_id TEXT)")
    def close(self): self.db.close()
    def issue_ticket(self,*,subject:str,session_id:str,now:int)->str:
        if not subject or not session_id: raise DurableRealtimeError("realtime_binding_invalid")
        ticket=secrets.token_urlsafe(32); digest=hashlib.sha256(ticket.encode()).hexdigest()
        with self.lock:
            self.db.execute("INSERT INTO tickets VALUES(?,?,?,?,?)",(digest,subject,session_id,now+self.ticket_ttl_seconds,"issued"))
            self.db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,'new',1,NULL,NULL)",(session_id,subject))
        return ticket
    def activate(self,*,ticket:str,subject:str,session_id:str,now:int,timeout_seconds:float=10)->sqlite3.Row:
        digest=hashlib.sha256(ticket.encode()).hexdigest()
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row=self.db.execute("SELECT * FROM tickets WHERE ticket_digest=?",(digest,)).fetchone()
                if not row or row["subject"]!=subject or row["session_id"]!=session_id: raise DurableRealtimeError("realtime_ticket_invalid")
                if row["expires_at"]<=now: raise DurableRealtimeError("realtime_ticket_expired")
                if row["state"]!="issued": raise DurableRealtimeError("realtime_ticket_replayed")
                self.db.execute("UPDATE tickets SET state='consumed' WHERE ticket_digest=?",(digest,))
                self.db.execute("UPDATE sessions SET state='activating' WHERE session_id=?",(session_id,))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK"); raise
        try: activation=self.provider.activate(ticket=ticket,subject=subject,session_id=session_id,timeout_seconds=timeout_seconds)
        except Exception as error:
            with self.lock: self.db.execute("UPDATE sessions SET state='indeterminate' WHERE session_id=?",(session_id,))
            raise DurableRealtimeError("realtime_activation_indeterminate") from error
        return self._commit_activation(session_id,activation)
    def reconcile(self,session_id:str,*,timeout_seconds:float=5)->sqlite3.Row:
        with self.lock:
            row=self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
            if not row or row["state"]!="indeterminate": raise DurableRealtimeError("realtime_reconcile_invalid")
        activation=self.provider.reconcile_activation(session_id=session_id,timeout_seconds=timeout_seconds)
        if activation is None: raise DurableRealtimeError("realtime_activation_indeterminate")
        return self._commit_activation(session_id,activation)
    def _commit_activation(self,session_id,activation):
        if not activation.provider_session_id or not activation.provider_receipt_id: raise DurableRealtimeError("realtime_provider_response_invalid")
        with self.lock:
            self.db.execute("UPDATE sessions SET state='active',provider_session_id=?,provider_receipt_id=? WHERE session_id=?",(activation.provider_session_id,activation.provider_receipt_id,session_id))
            return self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
    def interrupt(self,session_id:str,*,generation:int)->sqlite3.Row:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row=self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
                if not row: raise DurableRealtimeError("realtime_session_unknown")
                if row["state"]!="active": raise DurableRealtimeError("realtime_session_not_active")
                if row["generation"]!=generation: raise DurableRealtimeError("stale_realtime_generation")
                self.db.execute("UPDATE sessions SET generation=generation+1 WHERE session_id=?",(session_id,))
                result=self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone(); self.db.execute("COMMIT"); return result
            except Exception: self.db.execute("ROLLBACK"); raise
    def require_generation(self,session_id:str,generation:int)->sqlite3.Row:
        with self.lock:
            row=self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
            if not row or row["state"]!="active": raise DurableRealtimeError("realtime_session_not_active")
            if row["generation"]!=generation: raise DurableRealtimeError("stale_realtime_generation")
            return row
    def revoke(self,session_id:str,*,timeout_seconds:float=5)->None:
        with self.lock:
            row=self.db.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
            if not row: raise DurableRealtimeError("realtime_session_unknown")
            self.db.execute("UPDATE sessions SET state='revoked',generation=generation+1 WHERE session_id=?",(session_id,))
        if row["provider_session_id"]: self.provider.revoke(provider_session_id=row["provider_session_id"],timeout_seconds=timeout_seconds)
