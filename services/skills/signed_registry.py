"""Durable public-key Skill admission, not an execution sandbox or trust root.

Authenticated host code supplies consent and externally governed publisher keys.
No production signer, automatic network access or arbitrary execution is added.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from services.control_plane.bounded_calls import BoundedCalls
from services.control_plane.durable_state import DurableDatabase, timestamp
from services.skills.signed_package import (
    PublisherKey, SignedSkillError, canonical, digest, fail, inspect_package,
    name, parse_manifest, sha256, verify_signature, version,
)
from services.skills.signed_registry_schema import (
    STATE_COMPONENT,
    STATE_VERSION,
    RegistryStateAnchor,
    RegistryStateCheckpoint,
    database_identity,
    ensure_signed_skill_schema,
    initialize_registry_state,
    seal_registry_state,
    verify_database_identity,
    verify_registry_state,
)
from services.skills.package_transparency import (
    TransparencyProof, TransparencyVerifier,
)


@dataclass(frozen=True)
class InstallConsent:
    """Host-authenticated approval of one exact manifest; not client JSON proof."""
    subject: str
    manifest_sha256: str
    expires_at: int


@dataclass(frozen=True)
class CheckedSkill:
    document: bytes
    files: tuple[tuple[str, bytes], ...]
    consent_expires_at: int
    event_sequence: int

    @property
    def manifest(self) -> dict:
        return json.loads(self.document)


class SignedSkillRegistry:
    def __init__(self, path: str, *, subject: str, keys: Mapping[str, PublisherKey],
                 allowed_capabilities: frozenset[str], allowed_domains: frozenset[str],
                 clock: Callable[[], int], maximum_entries: int = 4096,
                 transparency_verifier: TransparencyVerifier | None = None,
                 state_anchor: RegistryStateAnchor | None = None):
        configured_subject = name(subject)
        if (not isinstance(keys, Mapping) or not 1 <= len(keys) <= 32
                or type(maximum_entries) is not int or not 1 <= maximum_entries <= 10000
                or not callable(clock)
                or (transparency_verifier is not None
                    and type(transparency_verifier) is not TransparencyVerifier)
                or (state_anchor is not None and type(state_anchor) is not RegistryStateAnchor)):
            fail("skill_registry_configuration_invalid")
        for values in (allowed_capabilities, allowed_domains):
            if type(values) is not frozenset or len(values) > 64:
                fail("skill_registry_configuration_invalid")
            for value in values:
                name(value)
        pins = dict(keys)
        for kid, key in pins.items():
            name(kid)
            if type(key) is not PublisherKey:
                fail("skill_public_key_invalid")
        if len({k.public_der for k in pins.values()}) != len(pins):
            fail("skill_public_key_alias")
        if isinstance(path, str) and Path(path).is_symlink():
            fail("skill_registry_database_identity_invalid")
        if state_anchor is not None and isinstance(path, str) and not Path(path).is_file():
            fail("skill_registry_state_instance_mismatch")

        # Public policy surfaces are read-only properties. Trusted composition
        # cannot accidentally replace a persisted authority binding after open.
        self._subject = configured_subject
        self._keys = MappingProxyType(pins)
        self._capabilities = allowed_capabilities
        self._domains = allowed_domains
        self._clock = clock
        self._maximum_entries = maximum_entries
        self._transparency_verifier = transparency_verifier
        self._state_anchor = state_anchor
        self._calls = BoundedCalls(4)
        self._path = path
        self.storage = DurableDatabase(path)
        try:
            self._database_identity = database_identity(path)
            policy_value = {
                "subject": configured_subject,
                "capabilities": sorted(allowed_capabilities),
                "domains": sorted(allowed_domains),
                "maximum_entries": maximum_entries,
            }
            if transparency_verifier is not None:
                policy_value["transparency"] = transparency_verifier.binding
            self._policy = canonical(policy_value)
            with self.storage.transaction() as db:
                verify_database_identity(self._path, self._database_identity)
                registry_fresh = self.storage.version("signed_skills", 1)
                state_fresh = self.storage.version(STATE_COMPONENT, STATE_VERSION)
                if registry_fresh != state_fresh:
                    if not registry_fresh and state_fresh:
                        fail("skill_registry_state_migration_required")
                    if registry_fresh and not state_fresh:
                        fail("skill_unmarked_schema_rejected")
                    fail("skill_registry_schema_integrity_invalid")
                ensure_signed_skill_schema(
                    db,
                    fresh=registry_fresh,
                    policy=self._policy,
                    now=self._now() if registry_fresh else None,
                )
                if registry_fresh:
                    if self._state_anchor is not None:
                        fail("skill_registry_state_instance_mismatch")
                    prior = initialize_registry_state(db)
                else:
                    prior = verify_registry_state(db, self._state_anchor, deep=True)
                for kid, key in pins.items():
                    fingerprint = sha256(key.public_der)
                    binding = canonical({
                        "publisher": key.publisher,
                        "not_before": key.not_before,
                        "not_after": key.not_after,
                    })
                    stored = db.execute(
                        "SELECT fingerprint,binding FROM signed_skill_keys WHERE id=?",
                        (kid,),
                    ).fetchone()
                    if stored and (stored[0], bytes(stored[1])) != (fingerprint, binding):
                        fail("skill_public_key_binding_changed")
                    if not stored:
                        if db.execute(
                            "SELECT 1 FROM signed_skill_keys WHERE fingerprint=?",
                            (fingerprint,),
                        ).fetchone():
                            fail("skill_public_key_alias")
                        if db.execute("SELECT COUNT(*) FROM signed_skill_keys").fetchone()[0] >= 32:
                            fail("skill_key_capacity_exhausted")
                        db.execute(
                            "INSERT INTO signed_skill_keys VALUES(?,?,?)",
                            (kid, fingerprint, binding),
                        )
                self.storage.mark_version("signed_skills", 1)
                self.storage.mark_version(STATE_COMPONENT, STATE_VERSION)
                seal_registry_state(db, prior)
                verify_database_identity(self._path, self._database_identity)
            verify_database_identity(self._path, self._database_identity)
        except BaseException:
            self.storage.close()
            raise

    @property
    def subject(self) -> str:
        return self._subject

    @property
    def keys(self) -> Mapping[str, PublisherKey]:
        return self._keys

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    @property
    def domains(self) -> frozenset[str]:
        return self._domains

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

    @property
    def maximum_entries(self) -> int:
        return self._maximum_entries

    @property
    def transparency_verifier(self) -> TransparencyVerifier | None:
        return self._transparency_verifier

    @property
    def state_anchor(self) -> RegistryStateAnchor | None:
        return self._state_anchor

    def close(self) -> None:
        self.storage.close()

    def _now(self) -> int:
        try:
            now = self._clock()
        except Exception:
            raise SignedSkillError("skill_clock_invalid") from None
        if not timestamp(now):
            fail("skill_clock_invalid")
        return now

    def _established(self, db) -> RegistryStateCheckpoint:
        if self.storage.version("signed_skills", 1):
            fail("skill_registry_schema_integrity_invalid")
        if self.storage.version(STATE_COMPONENT, STATE_VERSION):
            fail("skill_registry_state_migration_required")
        ensure_signed_skill_schema(db, fresh=False, policy=self._policy)
        return verify_registry_state(db, self._state_anchor)

    @contextmanager
    def _transaction(self, *, expiries: list[int] | None = None,
                     revocation: bool = False):
        verify_database_identity(self._path, self._database_identity)
        with self.storage.transaction() as db:
            verify_database_identity(self._path, self._database_identity)
            prior = self._established(db)
            last = db.execute(
                "SELECT last_time FROM signed_skill_policy WHERE id=1"
            ).fetchone()[0]
            if revocation:
                now = last
            else:
                now = self._now()
                if now < last:
                    fail("skill_clock_rollback")
            yield db, now
            final = now if revocation else self._now()
            if final < now:
                fail("skill_clock_rollback")
            if expiries and any(final >= expiry for expiry in expiries):
                fail("skill_admission_expired")
            db.execute("UPDATE signed_skill_policy SET last_time=? WHERE id=1", (final,))
            seal_registry_state(db, prior)
            verify_database_identity(self._path, self._database_identity)
        verify_database_identity(self._path, self._database_identity)

    def state_checkpoint(self) -> RegistryStateCheckpoint:
        """Return local continuity metadata; never claim an external witness."""
        verify_database_identity(self._path, self._database_identity)
        with self.storage.transaction() as db:
            verify_database_identity(self._path, self._database_identity)
            checkpoint = self._established(db)
            checkpoint = verify_registry_state(db, self._state_anchor, deep=True)
            verify_database_identity(self._path, self._database_identity)
        verify_database_identity(self._path, self._database_identity)
        return checkpoint

    def _key(self, manifest: dict, now: int) -> PublisherKey:
        key = self._keys.get(manifest["key_id"])
        if key is None or key.publisher != manifest["publisher"]:
            fail("skill_publisher_key_mismatch")
        if not key.not_before <= manifest["issued_at"] <= now < min(
            key.not_after, manifest["expires_at"]
        ):
            fail("skill_signer_or_manifest_expired")
        if manifest["expires_at"] > key.not_after:
            fail("skill_manifest_outlives_key")
        return key

    def _guard(self, db, manifest: dict, now: int, expiries: list[int]) -> None:
        if db.execute("SELECT suspended FROM signed_skill_policy WHERE id=1").fetchone()[0]:
            fail("skill_registry_suspended")
        key = self._key(manifest, now)
        for kind, target in (
            ("skill", manifest["skill_id"]),
            ("publisher", manifest["publisher"]),
            ("key", manifest["key_id"]),
            ("package", manifest["package_sha256"]),
        ):
            if db.execute(
                "SELECT 1 FROM signed_skill_revocations WHERE kind=? AND target=?",
                (kind, target),
            ).fetchone():
                fail("skill_revoked")
        if not set(manifest["capabilities"]) <= self._capabilities:
            fail("skill_capability_not_allowed")
        if not set(manifest["network_domains"]) <= self._domains:
            fail("skill_network_domain_not_allowed")
        expiries.extend((key.not_after, manifest["expires_at"]))

    def _dependencies(self, db, manifest: dict, now: int, expiries: list[int],
                      *, seen=None, budget=None) -> None:
        seen = set() if seen is None else seen
        budget = [128] if budget is None else budget
        if manifest["skill_id"] in seen or len(seen) >= 16 or budget[0] <= 0:
            fail("skill_dependency_cycle_or_limit")
        seen = seen | {manifest["skill_id"]}
        budget[0] -= 1
        for dep in manifest["dependencies"]:
            row = db.execute(
                "SELECT * FROM signed_skill_installed WHERE id=?",
                (dep["skill_id"],),
            ).fetchone()
            if row is None or row["digest"] != dep["manifest_sha256"] or row["consent_expires_at"] <= now:
                fail("skill_dependency_unavailable")
            child = parse_manifest(bytes(row["document"]))
            if child["version"] != dep["version"]:
                fail("skill_dependency_binding_mismatch")
            self._guard(db, child, now, expiries)
            expiries.append(row["consent_expires_at"])
            self._dependencies(db, child, now, expiries, seen=seen, budget=budget)

    def _event(self, db, event: str, target: str, object_digest: str, now: int) -> int:
        last = db.execute(
            "SELECT sequence,event_hash FROM signed_skill_events "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, "")
        body = [seq, event, target, object_digest, now, previous]
        db.execute(
            "INSERT INTO signed_skill_events VALUES(?,?,?,?,?,?,?)",
            (*body, sha256(canonical(body))),
        )
        return seq

    def _verify(self, document: bytes, signature: bytes, package: bytes):
        manifest = parse_manifest(document)
        key = self._key(manifest, self._now())
        if type(signature) is not bytes or len(signature) != 64:
            fail("skill_signature_invalid")
        outcome = self._calls.run(
            lambda: (verify_signature(key, document, signature),
                     inspect_package(manifest, package))[1],
            timeout_seconds=8,
        )
        if outcome.state != "completed":
            fail("skill_package_verification_failed")
        return manifest, outcome.value

    def install(self, document: bytes, *, signature: bytes, package: bytes,
                consent: InstallConsent,
                transparency: TransparencyProof | None = None) -> CheckedSkill:
        if (type(consent) is not InstallConsent or consent.subject != self._subject
                or not timestamp(consent.expires_at) or type(document) is not bytes
                or consent.manifest_sha256 != sha256(document)):
            fail("skill_exact_consent_required")
        if self._transparency_verifier is None:
            if transparency is not None:
                fail("skill_transparency_unconfigured")
            verified_transparency = None
        else:
            verified_transparency = self._transparency_verifier.verify(document, transparency)
        manifest, files = self._verify(document, signature, package)
        fingerprint = sha256(document)
        expiries = [consent.expires_at]
        if verified_transparency is not None:
            expiries.append(verified_transparency.expires_at)
        with self._transaction(expiries=expiries) as (db, now):
            if consent.expires_at <= now:
                fail("skill_consent_expired")
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            old = db.execute(
                "SELECT * FROM signed_skill_installed WHERE id=?",
                (manifest["skill_id"],),
            ).fetchone()
            if old:
                previous = parse_manifest(bytes(old["document"]))
                if previous["publisher"] != manifest["publisher"]:
                    fail("skill_publisher_replacement_forbidden")
                if version(manifest["version"]) < version(previous["version"]):
                    fail("skill_version_downgrade_forbidden")
                if version(manifest["version"]) == version(previous["version"]):
                    if old["digest"] != fingerprint:
                        fail("skill_version_manifest_conflict")
                    if old["consent_expires_at"] <= now:
                        fail("skill_reconsent_requires_new_version")
                    expiries.append(old["consent_expires_at"])
                    return CheckedSkill(
                        document, files, old["consent_expires_at"], old["event_sequence"]
                    )
            if db.execute(
                "SELECT COUNT(*) FROM signed_skill_events WHERE event='installed'"
            ).fetchone()[0] >= self._maximum_entries:
                fail("skill_installation_capacity_exhausted")
            until = min(
                [consent.expires_at, manifest["expires_at"]]
                + ([verified_transparency.expires_at]
                   if verified_transparency is not None else [])
            )
            seq = self._event(db, "installed", manifest["skill_id"], fingerprint, now)
            db.execute(
                "INSERT INTO signed_skill_installed VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET document=excluded.document,"
                "signature=excluded.signature,digest=excluded.digest,"
                "consent_expires_at=excluded.consent_expires_at,"
                "event_sequence=excluded.event_sequence",
                (manifest["skill_id"], document, signature, fingerprint, until, seq),
            )
            return CheckedSkill(document, files, until, seq)

    def resolve(self, skill_id: str, *, package: bytes) -> CheckedSkill:
        name(skill_id)
        expiries: list[int] = []
        with self._transaction(expiries=expiries) as (db, now):
            row = db.execute(
                "SELECT * FROM signed_skill_installed WHERE id=?", (skill_id,)
            ).fetchone()
            if row is None:
                fail("skill_unknown")
            document, signature, fingerprint = (
                bytes(row["document"]), bytes(row["signature"]), row["digest"]
            )
            manifest = parse_manifest(document)
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            expiries.append(row["consent_expires_at"])
        manifest, files = self._verify(document, signature, package)
        expiries = []
        with self._transaction(expiries=expiries) as (db, now):
            current = db.execute(
                "SELECT * FROM signed_skill_installed WHERE id=?", (skill_id,)
            ).fetchone()
            if current is None or current["digest"] != fingerprint or current["event_sequence"] != row["event_sequence"]:
                fail("skill_admission_changed")
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            expiries.append(current["consent_expires_at"])
            return CheckedSkill(
                document, files, current["consent_expires_at"], current["event_sequence"]
            )

    def revoke(self, kind: str, target: str) -> dict:
        if type(kind) is not str or kind not in {"skill", "publisher", "key", "package"}:
            fail("skill_revocation_kind_invalid")
        digest(target) if kind == "package" else name(target)
        with self._transaction(revocation=True) as (db, now):
            if db.execute(
                "SELECT 1 FROM signed_skill_revocations WHERE kind=? AND target=?",
                (kind, target),
            ).fetchone():
                return {"revoked": True, "scope": kind}
            count = db.execute("SELECT COUNT(*) FROM signed_skill_revocations").fetchone()[0]
            if count >= self._maximum_entries:
                if not db.execute(
                    "SELECT suspended FROM signed_skill_policy WHERE id=1"
                ).fetchone()[0]:
                    self._event(db, "suspended", "registry", "", now)
                    db.execute("UPDATE signed_skill_policy SET suspended=1 WHERE id=1")
                return {
                    "revoked": True,
                    "scope": "registry",
                    "reason": "revocation_capacity",
                }
            self._event(db, "revoked." + kind, target, "", now)
            db.execute(
                "INSERT INTO signed_skill_revocations VALUES(?,?)", (kind, target)
            )
            return {"revoked": True, "scope": kind}

    def verify_local_audit(self) -> dict:
        """Check the local event chain without converting it into external proof."""
        verify_database_identity(self._path, self._database_identity)
        with self.storage.transaction() as db:
            verify_database_identity(self._path, self._database_identity)
            if self.storage.version("signed_skills", 1):
                fail("skill_registry_schema_integrity_invalid")
            if self.storage.version(STATE_COMPONENT, STATE_VERSION):
                fail("skill_registry_state_migration_required")
            ensure_signed_skill_schema(db, fresh=False, policy=self._policy)
            previous, count = "", 0
            for row in db.execute("SELECT * FROM signed_skill_events ORDER BY sequence"):
                count += 1
                body = [
                    row["sequence"], row["event"], row["target"], row["digest"],
                    row["observed_at"], row["previous_hash"],
                ]
                if (row["sequence"] != count or row["previous_hash"] != previous
                        or sha256(canonical(body)) != row["event_hash"]):
                    fail("skill_local_audit_invalid")
                previous = row["event_hash"]
            verify_registry_state(db, self._state_anchor)
            verify_database_identity(self._path, self._database_identity)
        verify_database_identity(self._path, self._database_identity)
        return {
            "events": count,
            "last_hash": previous,
            "external_witness_verified": False,
        }
