"""Production model execution core with durable idempotency and receipts."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


class ModelExecutionError(ValueError):
    def __init__(self, code: str): super().__init__(code); self.code = code


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class ProviderResult:
    answer: str
    request_id: str
    receipt_id: str


class ModelProvider(Protocol):
    def generate(self, *, question: str, context: Mapping[str, object], request_key: str, timeout_seconds: float) -> ProviderResult: ...
    def reconcile(self, *, request_key: str, timeout_seconds: float) -> ProviderResult | None: ...
    def revoke_session(self, *, session_id: str, timeout_seconds: float) -> None: ...


@dataclass(frozen=True)
class ModelReceipt:
    idempotency_key: str
    fingerprint: str
    subject: str
    session_id: str
    state: str
    answer_digest: str | None
    provider_request_id: str | None
    provider_receipt_id: str | None


class ProductionModelGateway:
    def __init__(self, path: str, *, provider: ModelProvider, daily_request_limit: int = 1000, maximum_question_chars: int = 8000) -> None:
        if daily_request_limit < 1 or maximum_question_chars < 1: raise ValueError("invalid model gateway limits")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(path, isolation_level=None, check_same_thread=False); self.db.row_factory=sqlite3.Row
        for pragma in ("PRAGMA journal_mode=WAL","PRAGMA synchronous=FULL","PRAGMA foreign_keys=ON"): self.db.execute(pragma)
        self.provider=provider; self.daily_request_limit=daily_request_limit; self.maximum_question_chars=maximum_question_chars; self.lock=threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS requests(idempotency_key TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,subject TEXT NOT NULL,session_id TEXT NOT NULL,day INTEGER NOT NULL,state TEXT NOT NULL,answer_digest TEXT,provider_request_id TEXT,provider_receipt_id TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS revoked_sessions(session_id TEXT PRIMARY KEY, revoked_at INTEGER NOT NULL)")
    def close(self): self.db.close()
    def _receipt(self,row): return ModelReceipt(row["idempotency_key"],row["fingerprint"],row["subject"],row["session_id"],row["state"],row["answer_digest"],row["provider_request_id"],row["provider_receipt_id"])
    def execute(self, *, subject:str, session_id:str, idempotency_key:str, question:str, context:Mapping[str,object], now:int, timeout_seconds:float=15) -> tuple[str,ModelReceipt]:
        if not subject or not session_id or not idempotency_key or len(idempotency_key)>256: raise ModelExecutionError("model_binding_invalid")
        if not isinstance(question,str) or not question.strip() or len(question)>self.maximum_question_chars: raise ModelExecutionError("model_question_invalid")
        if timeout_seconds<=0 or timeout_seconds>60: raise ModelExecutionError("model_timeout_invalid")
        try: fingerprint=hashlib.sha256(_canonical({"question":question,"context":context,"subject":subject,"session_id":session_id})).hexdigest()
        except (TypeError,ValueError): raise ModelExecutionError("model_context_invalid")
        day=now//86400
        with self.lock:
            if self.db.execute("SELECT 1 FROM revoked_sessions WHERE session_id=?",(session_id,)).fetchone(): raise ModelExecutionError("model_session_revoked")
            row=self.db.execute("SELECT * FROM requests WHERE idempotency_key=?",(idempotency_key,)).fetchone()
            if row:
                if row["fingerprint"]!=fingerprint: raise ModelExecutionError("model_idempotency_conflict")
                if row["state"]=="committed": raise ModelExecutionError("model_duplicate_committed")
                if row["state"]=="indeterminate":
                    result=self.provider.reconcile(request_key=idempotency_key,timeout_seconds=timeout_seconds)
                    if result is None: raise ModelExecutionError("model_effect_indeterminate")
                    return self._commit(idempotency_key,result)
                raise ModelExecutionError("model_request_in_progress")
            count=self.db.execute("SELECT COUNT(*) FROM requests WHERE subject=? AND day=?",(subject,day)).fetchone()[0]
            if count>=self.daily_request_limit: raise ModelExecutionError("model_quota_exhausted")
            self.db.execute("INSERT INTO requests VALUES(?,?,?,?,?,'prepared',NULL,NULL,NULL)",(idempotency_key,fingerprint,subject,session_id,day))
        try:
            result=self.provider.generate(question=question,context=context,request_key=idempotency_key,timeout_seconds=timeout_seconds)
        except Exception as error:
            with self.lock: self.db.execute("UPDATE requests SET state='indeterminate' WHERE idempotency_key=?",(idempotency_key,))
            raise ModelExecutionError("model_effect_indeterminate") from error
        return self._commit(idempotency_key,result)
    def _commit(self,key:str,result:ProviderResult)->tuple[str,ModelReceipt]:
        if not result.answer or not result.request_id or not result.receipt_id: raise ModelExecutionError("model_provider_response_invalid")
        digest=hashlib.sha256(result.answer.encode()).hexdigest()
        with self.lock:
            self.db.execute("UPDATE requests SET state='committed',answer_digest=?,provider_request_id=?,provider_receipt_id=? WHERE idempotency_key=?",(digest,result.request_id,result.receipt_id,key))
            row=self.db.execute("SELECT * FROM requests WHERE idempotency_key=?",(key,)).fetchone()
        return result.answer,self._receipt(row)
    def revoke_session(self,session_id:str,*,now:int,timeout_seconds:float=5)->None:
        with self.lock: self.db.execute("INSERT OR REPLACE INTO revoked_sessions VALUES(?,?)",(session_id,now))
        self.provider.revoke_session(session_id=session_id,timeout_seconds=timeout_seconds)
