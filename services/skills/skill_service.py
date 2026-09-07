"""Authenticated composition of package custody and broker-only execution."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Protocol

from services.skills.package_vault import (
    EncryptedSkillPackageVault,
    PackageVaultError,
)
from services.skills.sandbox_runtime import (
    LinuxBrokerOnlySandbox,
    SandboxExecution,
    SandboxLimits,
    SkillSandboxError,
)

DEFAULT_AUDIENCE = "hepta-skills"
CONSENT_SCOPE = "skills.consent"
EXECUTE_SCOPE = "skills.execute"
REVOKE_SCOPE = "skills.revoke"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_MAX_TIME = 253_402_300_799


class SkillServiceError(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class SkillPrincipal:
    subject: str
    session_id: str
    audience: str
    scopes: tuple[str, ...]
    expires_at: int


class SkillIdentityVerifier(Protocol):
    def verify(
        self, *, bearer_token: str, audience: str, required_scope: str
    ) -> SkillPrincipal: ...


class AuthenticatedSkillService:
    def __init__(
        self,
        *,
        vault: EncryptedSkillPackageVault,
        sandbox: LinuxBrokerOnlySandbox,
        identity: SkillIdentityVerifier,
        clock: Callable[[], int],
        audience: str = DEFAULT_AUDIENCE,
    ) -> None:
        if (
            not isinstance(vault, EncryptedSkillPackageVault)
            or not isinstance(sandbox, LinuxBrokerOnlySandbox)
            or not callable(getattr(identity, "verify", None))
            or not callable(clock)
            or type(audience) is not str
            or _IDENTIFIER.fullmatch(audience) is None
        ):
            raise SkillServiceError("skill_service_configuration_invalid", 500)
        self.vault = vault
        self.sandbox = sandbox
        self.identity = identity
        self.clock = clock
        self.audience = audience

    @staticmethod
    def _bearer(value: object) -> str:
        if type(value) is not str or not value.startswith("Bearer "):
            raise SkillServiceError("skill_service_unauthorized", 401)
        token = value[7:]
        if (
            not 16 <= len(token.encode("utf-8")) <= 8192
            or any(ord(character) <= 32 or ord(character) == 127 for character in token)
        ):
            raise SkillServiceError("skill_service_unauthorized", 401)
        return token

    def _now(self) -> int:
        try:
            value = self.clock()
        except Exception:
            raise SkillServiceError("skill_service_clock_invalid", 503) from None
        if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME:
            raise SkillServiceError("skill_service_clock_invalid", 503)
        return value

    def _principal(self, authorization: str | None, scope: str) -> SkillPrincipal:
        token = self._bearer(authorization)
        try:
            value = self.identity.verify(
                bearer_token=token,
                audience=self.audience,
                required_scope=scope,
            )
        except Exception:
            raise SkillServiceError("skill_service_unauthorized", 401) from None
        if (
            type(value) is not SkillPrincipal
            or type(value.subject) is not str
            or _IDENTIFIER.fullmatch(value.subject) is None
            or type(value.session_id) is not str
            or _IDENTIFIER.fullmatch(value.session_id) is None
            or value.audience != self.audience
            or type(value.scopes) is not tuple
            or scope not in value.scopes
            or type(value.expires_at) is not int
            or type(value.expires_at) is bool
            or value.expires_at <= self._now()
        ):
            raise SkillServiceError("skill_service_unauthorized", 401)
        return value

    @staticmethod
    def _map_vault(error: PackageVaultError) -> SkillServiceError:
        status = 403 if error.code in {
            "skill_vault_consent_denied",
            "skill_vault_capability_denied",
            "skill_vault_revoked",
            "skill_vault_authority_revoked",
        } else 409 if error.code.endswith("_conflict") else 503 if error.code.endswith(
            ("_failed", "_unavailable")
        ) else 400
        return SkillServiceError(error.code, status)

    @staticmethod
    def _map_sandbox(error: SkillSandboxError) -> SkillServiceError:
        status = 403 if error.code == "skill_authority_revoked" else 503
        return SkillServiceError(error.code, status)

    def grant_consent(
        self,
        *,
        authorization: str | None,
        skill_id: str,
        version: str,
        package_digest: str,
        capabilities: Iterable[str],
        policy_digest: str,
        expires_at: int,
    ) -> None:
        principal = self._principal(authorization, CONSENT_SCOPE)
        if type(expires_at) is not int or type(expires_at) is bool:
            raise SkillServiceError("skill_consent_invalid")
        try:
            self.vault.grant_consent(
                subject=principal.subject,
                skill_id=skill_id,
                version=version,
                package_digest=package_digest,
                capabilities=capabilities,
                policy_digest=policy_digest,
                expires_at=min(expires_at, principal.expires_at),
            )
        except PackageVaultError as error:
            raise self._map_vault(error) from None

    def revoke_consent(
        self, *, authorization: str | None, skill_id: str
    ) -> None:
        principal = self._principal(authorization, REVOKE_SCOPE)
        try:
            self.vault.revoke_consent(
                subject=principal.subject, skill_id=skill_id
            )
        except PackageVaultError as error:
            raise self._map_vault(error) from None

    def execute(
        self,
        *,
        authorization: str | None,
        skill_id: str,
        required_capabilities: Iterable[str],
        policy_digest: str,
        input_value: object,
        capability_handler: Callable[
            [str, Mapping[str, object]], Mapping[str, object]
        ],
        limits: SandboxLimits = SandboxLimits(),
    ) -> SandboxExecution:
        initial = self._principal(authorization, EXECUTE_SCOPE)
        # Capture capability identities once.  A mutable caller container is not
        # reopened after policy admission.
        try:
            required = tuple(required_capabilities)
        except TypeError:
            raise SkillServiceError("skill_capability_policy_invalid") from None

        def authorize() -> None:
            current = self._principal(authorization, EXECUTE_SCOPE)
            if (
                current.subject != initial.subject
                or current.session_id != initial.session_id
                or current.expires_at > initial.expires_at
            ):
                raise SkillServiceError("skill_service_authority_changed", 403)

        try:
            lease = self.vault.lease(
                subject=initial.subject,
                skill_id=skill_id,
                required_capabilities=required,
                policy_digest=policy_digest,
                authorize=authorize,
            )
            if lease.expires_at > initial.expires_at:
                raise SkillServiceError("skill_service_authority_changed", 403)

            def broker(
                capability: str, arguments: Mapping[str, object]
            ) -> Mapping[str, object]:
                authorize()
                if capability not in lease.capabilities:
                    raise SkillServiceError("skill_capability_denied", 403)
                result = capability_handler(capability, arguments)
                authorize()
                return result

            result = self.sandbox.execute(
                source=lease.bytes,
                input_value=input_value,
                allowed_capabilities=lease.capabilities,
                capability_handler=broker,
                authorize=authorize,
                limits=limits,
            )
            authorize()
            return result
        except PackageVaultError as error:
            raise self._map_vault(error) from None
        except SkillSandboxError as error:
            raise self._map_sandbox(error) from None
