"""Realtime bootstrap and interruption state machine.

The broker returns an internal one-time bootstrap ticket. A production provider
adapter exchanges that ticket server-side for a provider session; provider API
keys are never returned to the mobile client.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Iterable

from .identity import (
    AccessClaims,
    IdentityError,
    SlidingWindowRateLimiter,
    TokenService,
)


class RealtimeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SessionState(str, Enum):
    ISSUED = "issued"
    CONNECTING = "connecting"
    LISTENING = "listening"
    RESPONDING = "responding"
    INTERRUPTING = "interrupting"
    CLOSED = "closed"
    REVOKED = "revoked"


@dataclass(frozen=True)
class RealtimeTicket:
    session_id: str
    bootstrap_token: str
    subject: str
    device_id: str
    scopes: frozenset[str]
    provider_profile: str
    expires_at: int


@dataclass(frozen=True)
class RealtimeSession:
    session_id: str
    subject: str
    device_id: str
    state: SessionState
    generation: int
    created_at: int
    expires_at: int
    microphone_indicator: bool
    provider_profile: str


class RealtimeSessionBroker:
    """Issues one-time bootstrap tickets and tracks barge-in generations."""

    ALLOWED_SCOPES = frozenset(
        {"audio.input", "audio.output", "transcript.delta", "tool.propose"}
    )

    def __init__(
        self,
        *,
        access_tokens: TokenService,
        bootstrap_tokens: TokenService,
        rate_limiter: SlidingWindowRateLimiter,
        allowed_provider_profiles: Iterable[str],
        clock: Callable[[], int],
        session_id_factory: Callable[[], str] | None = None,
        maximum_ttl_seconds: int = 120,
    ) -> None:
        self.access_tokens = access_tokens
        self.bootstrap_tokens = bootstrap_tokens
        self.rate_limiter = rate_limiter
        self.allowed_provider_profiles = frozenset(allowed_provider_profiles)
        self.clock = clock
        self.session_id_factory = session_id_factory or (
            lambda: secrets.token_urlsafe(16)
        )
        self.maximum_ttl_seconds = maximum_ttl_seconds
        self._sessions: dict[str, RealtimeSession] = {}
        self._consumed_ticket_ids: set[str] = set()

    def issue_ticket(
        self,
        *,
        access_token: str,
        requested_scopes: Iterable[str],
        provider_profile: str,
        ttl_seconds: int = 90,
    ) -> RealtimeTicket:
        now = self.clock()
        claims = self.access_tokens.verify(
            access_token,
            audience="hepta-control-plane",
            required_scopes={"realtime.connect"},
            now=now,
        )
        self.rate_limiter.consume(
            f"{claims.subject}:{claims.device_id}:realtime-ticket", now=now
        )
        scopes = frozenset(requested_scopes)
        if not scopes or not scopes.issubset(self.ALLOWED_SCOPES):
            raise RealtimeError("realtime_scope_invalid")
        if provider_profile not in self.allowed_provider_profiles:
            raise RealtimeError("provider_profile_not_allowed")
        if ttl_seconds < 1 or ttl_seconds > self.maximum_ttl_seconds:
            raise RealtimeError("realtime_ttl_invalid")

        session_id = self.session_id_factory()
        bootstrap = self.bootstrap_tokens.issue(
            subject=claims.subject,
            device_id=claims.device_id,
            audience="hepta-realtime-bootstrap",
            scopes={"realtime.bootstrap", *scopes},
            session_id=session_id,
            ttl_seconds=ttl_seconds,
            now=now,
        )
        session = RealtimeSession(
            session_id=session_id,
            subject=claims.subject,
            device_id=claims.device_id,
            state=SessionState.ISSUED,
            generation=0,
            created_at=now,
            expires_at=now + ttl_seconds,
            microphone_indicator=False,
            provider_profile=provider_profile,
        )
        self._sessions[session_id] = session
        return RealtimeTicket(
            session_id=session_id,
            bootstrap_token=bootstrap,
            subject=claims.subject,
            device_id=claims.device_id,
            scopes=scopes,
            provider_profile=provider_profile,
            expires_at=session.expires_at,
        )

    def activate(self, bootstrap_token: str) -> RealtimeSession:
        now = self.clock()
        claims = self.bootstrap_tokens.verify(
            bootstrap_token,
            audience="hepta-realtime-bootstrap",
            required_scopes={"realtime.bootstrap"},
            now=now,
        )
        if claims.token_id in self._consumed_ticket_ids:
            raise RealtimeError("bootstrap_ticket_replayed")
        session = self._sessions.get(claims.session_id)
        if session is None:
            raise RealtimeError("realtime_session_unknown")
        if session.subject != claims.subject or session.device_id != claims.device_id:
            raise RealtimeError("realtime_session_binding_mismatch")
        if session.state is not SessionState.ISSUED:
            raise RealtimeError("realtime_session_already_activated")
        self._consumed_ticket_ids.add(claims.token_id)
        session = replace(session, state=SessionState.CONNECTING)
        self._sessions[session.session_id] = session
        return session

    def transition(
        self,
        session_id: str,
        *,
        event: str,
        generation: int,
    ) -> RealtimeSession:
        now = self.clock()
        session = self._sessions.get(session_id)
        if session is None:
            raise RealtimeError("realtime_session_unknown")
        if now >= session.expires_at and session.state not in {
            SessionState.CLOSED,
            SessionState.REVOKED,
        }:
            session = replace(
                session,
                state=SessionState.CLOSED,
                microphone_indicator=False,
            )
            self._sessions[session_id] = session
            raise RealtimeError("realtime_session_expired")
        if generation != session.generation:
            raise RealtimeError("stale_realtime_generation")

        transitions = {
            (SessionState.CONNECTING, "connected"): SessionState.LISTENING,
            (SessionState.LISTENING, "response_started"): SessionState.RESPONDING,
            (SessionState.RESPONDING, "response_completed"): SessionState.LISTENING,
            (SessionState.INTERRUPTING, "interrupt_completed"): SessionState.LISTENING,
            (SessionState.LISTENING, "close"): SessionState.CLOSED,
            (SessionState.RESPONDING, "close"): SessionState.CLOSED,
            (SessionState.INTERRUPTING, "close"): SessionState.CLOSED,
            (SessionState.CONNECTING, "close"): SessionState.CLOSED,
        }
        next_state = transitions.get((session.state, event))
        if next_state is None:
            raise RealtimeError("realtime_transition_invalid")
        session = replace(
            session,
            state=next_state,
            microphone_indicator=next_state is SessionState.LISTENING,
        )
        self._sessions[session_id] = session
        return session

    def interrupt(self, session_id: str, *, generation: int) -> RealtimeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise RealtimeError("realtime_session_unknown")
        if generation != session.generation:
            raise RealtimeError("stale_realtime_generation")
        if session.state not in {SessionState.RESPONDING, SessionState.LISTENING}:
            raise RealtimeError("realtime_interrupt_invalid")
        session = replace(
            session,
            state=SessionState.INTERRUPTING,
            generation=session.generation + 1,
            microphone_indicator=False,
        )
        self._sessions[session_id] = session
        return session

    def revoke(self, session_id: str) -> RealtimeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise RealtimeError("realtime_session_unknown")
        session = replace(
            session,
            state=SessionState.REVOKED,
            generation=session.generation + 1,
            microphone_indicator=False,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> RealtimeSession | None:
        return self._sessions.get(session_id)
