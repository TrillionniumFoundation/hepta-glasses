"""Production speech bootstrap custody and metadata-only ASR receipts."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class SpeechGatewayError(ValueError):
    def __init__(self,code:str): super().__init__(code); self.code=code


@dataclass(frozen=True)
class ProviderSpeechTicket:
    endpoint: str
    bearer_token: str
    provider: str
    provider_ticket_id: str
    expires_at: int
    maximum_audio_bytes: int


class SpeechProviderBroker(Protocol):
    def mint_ticket(self, *, subject:str, session_id:str, locale:str, audio_format:str, maximum_audio_bytes:int, expires_at:int, timeout_seconds:float) -> ProviderSpeechTicket: ...
    def revoke_session(self, *, session_id:str, timeout_seconds:float) -> None: ...


@dataclass(frozen=True)
class SpeechBootstrap:
    bootstrap_id:str
    session_id:str
    generation:int
    pair_identity:str
    locale:str
    endpoint:str
    bearer_token:str
    provider:str
    expires_at:int
    maximum_audio_bytes:int


class ProductionSpeechGateway:
    AUDIO_FORMAT="pcm_s16le_16000_mono"
    def __init__(self,path:str,*,broker:SpeechProviderBroker,maximum_session_bytes:int=960000,ticket_ttl_seconds:int=90,daily_limit:int=200):
        if maximum_session_bytes<3200 or ticket_ttl_seconds<1 or ticket_ttl_seconds>300 or daily_limit<1: raise ValueError("speech_configuration_invalid")
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,isolation_level=None,check_same_thread=False); self.db.row_factory=sqlite3.Row
        for p in ("PRAGMA journal_mode=WAL","PRAGMA synchronous=FULL"): self.db.execute(p)
        self.broker=broker; self.maximum_session_bytes=maximum_session_bytes; self.ticket_ttl_seconds=ticket_ttl_seconds; self.daily_limit=daily_limit; self.lock=threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS bootstraps(bootstrap_digest TEXT PRIMARY KEY,subject TEXT NOT NULL,session_id TEXT NOT NULL,generation INTEGER NOT NULL,pair_digest TEXT NOT NULL,locale TEXT NOT NULL,provider TEXT NOT NULL,provider_ticket_digest TEXT NOT NULL,expires_at INTEGER NOT NULL,state TEXT NOT NULL,day INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS revoked_sessions(session_id TEXT PRIMARY KEY,revoked_at INTEGER NOT NULL)")
    def close(self):self.db.close()
    def bootstrap(self,*,subject:str,session_id:str,generation:int,pair_identity:str,locale:str,now:int,timeout_seconds:float=8)->SpeechBootstrap:
        if not subject or not session_id or generation<1 or not pair_identity or not locale or len(locale)>64: raise SpeechGatewayError("speech_binding_invalid")
        day=now//86400
        with self.lock:
            if self.db.execute("SELECT 1 FROM revoked_sessions WHERE session_id=?",(session_id,)).fetchone(): raise SpeechGatewayError("speech_session_revoked")
            count=self.db.execute("SELECT COUNT(*) FROM bootstraps WHERE subject=? AND day=?",(subject,day)).fetchone()[0]
            if count>=self.daily_limit: raise SpeechGatewayError("speech_quota_exhausted")
        expiry=now+self.ticket_ttl_seconds
        ticket=self.broker.mint_ticket(subject=subject,session_id=session_id,locale=locale,audio_format=self.AUDIO_FORMAT,maximum_audio_bytes=self.maximum_session_bytes,expires_at=expiry,timeout_seconds=timeout_seconds)
        if not ticket.endpoint.startswith("https://") or not ticket.bearer_token or ticket.expires_at>expiry or ticket.maximum_audio_bytes>self.maximum_session_bytes: raise SpeechGatewayError("speech_provider_ticket_invalid")
        bootstrap_id=secrets.token_urlsafe(24); digest=hashlib.sha256(bootstrap_id.encode()).hexdigest()
        with self.lock:
            self.db.execute("INSERT INTO bootstraps VALUES(?,?,?,?,?,?,?,?,?,'issued',?)",(digest,subject,session_id,generation,hashlib.sha256(pair_identity.encode()).hexdigest(),locale,ticket.provider,hashlib.sha256(ticket.provider_ticket_id.encode()).hexdigest(),ticket.expires_at,day))
        return SpeechBootstrap(bootstrap_id,session_id,generation,pair_identity,locale,ticket.endpoint,ticket.bearer_token,ticket.provider,ticket.expires_at,ticket.maximum_audio_bytes)
    def consume(self,bootstrap_id:str,*,session_id:str,generation:int,pair_identity:str,now:int)->None:
        digest=hashlib.sha256(bootstrap_id.encode()).hexdigest()
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row=self.db.execute("SELECT * FROM bootstraps WHERE bootstrap_digest=?",(digest,)).fetchone()
                if not row or row["session_id"]!=session_id or row["generation"]!=generation or row["pair_digest"]!=hashlib.sha256(pair_identity.encode()).hexdigest(): raise SpeechGatewayError("speech_bootstrap_invalid")
                if row["expires_at"]<=now: raise SpeechGatewayError("speech_bootstrap_expired")
                if row["state"]!="issued": raise SpeechGatewayError("speech_bootstrap_replayed")
                self.db.execute("UPDATE bootstraps SET state='consumed' WHERE bootstrap_digest=?",(digest,)); self.db.execute("COMMIT")
            except Exception:self.db.execute("ROLLBACK");raise
    def revoke_session(self,session_id:str,*,now:int,timeout_seconds:float=5):
        with self.lock:self.db.execute("INSERT OR REPLACE INTO revoked_sessions VALUES(?,?)",(session_id,now));self.db.execute("UPDATE bootstraps SET state='revoked' WHERE session_id=?",(session_id,))
        self.broker.revoke_session(session_id=session_id,timeout_seconds=timeout_seconds)
