"""One identity interpretation for model, speech and mutation ingress.

A deployment-specific durable token authority and active-pair registry are
injected. This adapter never trusts client JSON for subject, device, session,
pair, scope, user-presence or biometric facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from services.control_plane.mutation_authority import (
    DEFAULT_AUDIENCE as MUTATION_AUDIENCE,
    REQUIRED_SCOPE as MUTATION_SCOPE,
    MutationPrincipal,
)
from services.model_gateway.model_ingress import (
    DEFAULT_AUDIENCE as MODEL_AUDIENCE,
    REQUIRED_SCOPE as MODEL_SCOPE,
    ModelPrincipal,
)
from services.model_gateway.speech_ingress import (
    DEFAULT_AUDIENCE as SPEECH_AUDIENCE,
    REQUIRED_SCOPE as SPEECH_SCOPE,
    SpeechPrincipal,
)

MAX_TIME = 253_402_300_799


class PrincipalAdapterError(ValueError):
    def __init__(self, code: str = "identity_principal_invalid") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VerifiedAccessClaims:
    subject: str
    device_id: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    expires_at: int
    policy_hash: str
    user_present: bool
    biometric_verified: bool


@dataclass(frozen=True)
class ActivePairBinding:
    subject: str
    device_id: str
    session_id: str
    pair_identity: str
    active: bool
    expires_at: int


class DurableAccessAuthority(Protocol):
    def verify_access(self, *, bearer_token: str, audience: str,
                      required_scope: str) -> VerifiedAccessClaims: ...


class ActivePairAuthority(Protocol):
    def resolve_pair(self, *, subject: str, device_id: str,
                     session_id: str) -> ActivePairBinding: ...


class AuthenticatedPrincipalAdapter:
    """Implements the identical `verify` surface used by all three ingresses."""

    def __init__(self, *, access: DurableAccessAuthority,
                 pairs: ActivePairAuthority, clock) -> None:
        if not callable(getattr(access, "verify_access", None)):
            raise PrincipalAdapterError("identity_access_authority_invalid")
        if not callable(getattr(pairs, "resolve_pair", None)):
            raise PrincipalAdapterError("identity_pair_authority_invalid")
        if not callable(clock):
            raise PrincipalAdapterError("identity_clock_invalid")
        self.access = access
        self.pairs = pairs
        self.clock = clock

    def verify(self, *, bearer_token: str, audience: str,
               required_scope: str) -> object:
        expected_scope = {
            MODEL_AUDIENCE: MODEL_SCOPE,
            SPEECH_AUDIENCE: SPEECH_SCOPE,
            MUTATION_AUDIENCE: MUTATION_SCOPE,
        }.get(audience)
        if expected_scope is None or required_scope != expected_scope:
            raise PrincipalAdapterError("identity_audience_scope_invalid")
        try:
            claims = self.access.verify_access(
                bearer_token=bearer_token,
                audience=audience,
                required_scope=required_scope,
            )
        except Exception:
            raise PrincipalAdapterError("identity_access_denied") from None
        claims = self._claims(claims)
        now = self._now()
        if claims.audience != audience or required_scope not in claims.scopes \
                or claims.expires_at <= now:
            raise PrincipalAdapterError("identity_access_denied")

        if audience == MODEL_AUDIENCE:
            return ModelPrincipal(
                subject=claims.subject,
                session_id=claims.session_id,
                audience=audience,
                scopes=claims.scopes,
                consent_expires_at=claims.expires_at,
            )

        pair = self._pair(
            self.pairs.resolve_pair(
                subject=claims.subject,
                device_id=claims.device_id,
                session_id=claims.session_id,
            ),
            claims=claims,
            now=now,
        )
        if audience == SPEECH_AUDIENCE:
            return SpeechPrincipal(
                subject=claims.subject,
                session_id=claims.session_id,
                pair_identity=pair.pair_identity,
                audience=audience,
                scopes=claims.scopes,
            )
        if audience == MUTATION_AUDIENCE:
            # Device effects are bound to the exact active pair, while access
            # verification remains bound to the registered phone/device ID.
            return MutationPrincipal(
                subject=claims.subject,
                device_id=pair.pair_identity,
                session_id=claims.session_id,
                audience=audience,
                scopes=claims.scopes,
                policy_hash=claims.policy_hash,
                user_present=claims.user_present,
                biometric_verified=claims.biometric_verified,
                expires_at=min(claims.expires_at, pair.expires_at),
            )
        raise PrincipalAdapterError("identity_audience_scope_invalid")

    def _claims(self, value: object) -> VerifiedAccessClaims:
        if type(value) is not VerifiedAccessClaims:
            raise PrincipalAdapterError("identity_access_denied")
        for identifier in (value.subject, value.device_id, value.session_id, value.audience):
            self._identifier(identifier)
        if type(value.scopes) is not tuple or not value.scopes or len(value.scopes) > 32 \
                or len(set(value.scopes)) != len(value.scopes) \
                or any(type(scope) is not str or not 1 <= len(scope) <= 128
                       for scope in value.scopes) \
                or type(value.expires_at) is not int or type(value.expires_at) is bool \
                or not 0 < value.expires_at <= MAX_TIME \
                or re.fullmatch(r"[a-f0-9]{64}", value.policy_hash) is None \
                or type(value.user_present) is not bool \
                or type(value.biometric_verified) is not bool:
            raise PrincipalAdapterError("identity_access_denied")
        return value

    def _pair(self, value: object, *, claims: VerifiedAccessClaims,
              now: int) -> ActivePairBinding:
        if type(value) is not ActivePairBinding:
            raise PrincipalAdapterError("identity_pair_denied")
        for identifier in (
            value.subject,
            value.device_id,
            value.session_id,
            value.pair_identity,
        ):
            self._identifier(identifier)
        if (value.subject != claims.subject or value.device_id != claims.device_id
                or value.session_id != claims.session_id or value.active is not True
                or type(value.expires_at) is not int or type(value.expires_at) is bool
                or value.expires_at <= now or value.expires_at > claims.expires_at):
            raise PrincipalAdapterError("identity_pair_denied")
        return value

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise PrincipalAdapterError("identity_clock_invalid") from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= MAX_TIME:
            raise PrincipalAdapterError("identity_clock_invalid")
        return value

    @staticmethod
    def _identifier(value: object) -> str:
        if type(value) is not str or not 1 <= len(value) <= 256 \
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None:
            raise PrincipalAdapterError("identity_access_denied")
        return value
