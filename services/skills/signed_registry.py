"""Durable public-key Skill admission, not an execution sandbox or trust root.

Authenticated host code supplies consent and externally governed publisher keys.
No production signer, automatic network access or arbitrary execution is added.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from services.control_plane.bounded_calls import BoundedCalls
from services.control_plane.durable_state import DurableDatabase, timestamp
from services.skills.signed_package import (
    PublisherKey, SignedSkillError, canonical, digest, fail, inspect_package,
    name, parse_manifest, sha256, verify_signature, version,
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
        return json.loads(self.document)  # defensive copy, not shared mutable state


class SignedSkillRegistry:
    def __init__(self, path: str, *, subject: str, keys: Mapping[str, PublisherKey],
                 allowed_capabilities: frozenset[str], allowed_domains: frozenset[str],
                 clock: Callable[[], int], maximum_entries: int = 4096):
        self.subject = name(subject)
        if (not isinstance(keys, Mapping) or not 1 <= len(keys) <= 32
                or type(maximum_entries) is not int or not 1 <= maximum_entries <= 10000
                or not callable(clock)):
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
        self.keys = MappingProxyType(pins)
        self.capabilities, self.domains = allowed_capabilities, allowed_domains
        self.clock, self.maximum_entries = clock, maximum_entries
        self._calls = BoundedCalls(4)
        self.storage = DurableDatabase(path)
        policy = canonical({"subject": subject, "capabilities": sorted(allowed_capabilities),
                            "domains": sorted(allowed_domains), "maximum_entries": maximum_entries})
        try:
            with self.storage.transaction() as db:
                unmarked = self.storage.version("signed_skills", 1)
                if unmarked and db.execute("SELECT 1 FROM sqlite_master WHERE name GLOB 'signed_skill_*'").fetchone():
                    fail("skill_unmarked_schema_rejected")
                for statement in (
                    "CREATE TABLE IF NOT EXISTS signed_skill_policy(id INTEGER PRIMARY KEY CHECK(id=1),policy BLOB NOT NULL,last_time INTEGER NOT NULL,suspended INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS signed_skill_keys(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,binding BLOB NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS signed_skill_installed(id TEXT PRIMARY KEY,document BLOB NOT NULL,signature BLOB NOT NULL,digest TEXT NOT NULL,consent_expires_at INTEGER NOT NULL,event_sequence INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS signed_skill_revocations(kind TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(kind,target))",
                    "CREATE TABLE IF NOT EXISTS signed_skill_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,target TEXT NOT NULL,digest TEXT NOT NULL,observed_at INTEGER NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)",
                ):
                    db.execute(statement)
                old = db.execute("SELECT policy FROM signed_skill_policy WHERE id=1").fetchone()
                if old and bytes(old[0]) != policy:
                    fail("skill_registry_policy_migration_required")
                db.execute("INSERT OR IGNORE INTO signed_skill_policy VALUES(1,?,?,0)", (policy, self._now()))
                for kid, key in pins.items():
                    fingerprint = sha256(key.public_der)
                    binding = canonical({"publisher": key.publisher, "not_before": key.not_before, "not_after": key.not_after})
                    stored = db.execute("SELECT fingerprint,binding FROM signed_skill_keys WHERE id=?", (kid,)).fetchone()
                    if stored and (stored[0], bytes(stored[1])) != (fingerprint, binding):
                        fail("skill_public_key_binding_changed")
                    if not stored:
                        if db.execute("SELECT 1 FROM signed_skill_keys WHERE fingerprint=?", (fingerprint,)).fetchone():
                            fail("skill_public_key_alias")
                        if db.execute("SELECT COUNT(*) FROM signed_skill_keys").fetchone()[0] >= 32:
                            fail("skill_key_capacity_exhausted")
                        db.execute("INSERT INTO signed_skill_keys VALUES(?,?,?)", (kid, fingerprint, binding))
                self.storage.mark_version("signed_skills", 1)
        except BaseException:
            self.storage.close()
            raise

    def close(self) -> None:
        self.storage.close()

    def _now(self) -> int:
        now = self.clock()
        if not timestamp(now):
            fail("skill_clock_invalid")
        return now

    @contextmanager
    def _transaction(self, *, expiries: list[int] | None = None, revocation: bool = False):
        with self.storage.transaction() as db:
            last = db.execute("SELECT last_time FROM signed_skill_policy WHERE id=1").fetchone()[0]
            if revocation:
                # Emergency denial does not become impossible during a clock incident.
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

    def _key(self, manifest: dict, now: int) -> PublisherKey:
        key = self.keys.get(manifest["key_id"])
        if key is None or key.publisher != manifest["publisher"]:
            fail("skill_publisher_key_mismatch")
        if not key.not_before <= manifest["issued_at"] <= now < min(key.not_after, manifest["expires_at"]):
            fail("skill_signer_or_manifest_expired")
        if manifest["expires_at"] > key.not_after:
            fail("skill_manifest_outlives_key")
        return key

    def _guard(self, db, manifest: dict, now: int, expiries: list[int]) -> None:
        if db.execute("SELECT suspended FROM signed_skill_policy WHERE id=1").fetchone()[0]:
            fail("skill_registry_suspended")
        key = self._key(manifest, now)
        for kind, target in (("skill", manifest["skill_id"]), ("publisher", manifest["publisher"]),
                             ("key", manifest["key_id"]), ("package", manifest["package_sha256"])):
            if db.execute("SELECT 1 FROM signed_skill_revocations WHERE kind=? AND target=?", (kind, target)).fetchone():
                fail("skill_revoked")
        if not set(manifest["capabilities"]) <= self.capabilities:
            fail("skill_capability_not_allowed")
        if not set(manifest["network_domains"]) <= self.domains:
            fail("skill_network_domain_not_allowed")
        expiries.extend((key.not_after, manifest["expires_at"]))

    def _dependencies(self, db, manifest: dict, now: int, expiries: list[int], *, seen=None, budget=None) -> None:
        seen = set() if seen is None else seen
        budget = [128] if budget is None else budget
        if manifest["skill_id"] in seen or len(seen) >= 16 or budget[0] <= 0:
            fail("skill_dependency_cycle_or_limit")
        seen = seen | {manifest["skill_id"]}
        budget[0] -= 1
        for dep in manifest["dependencies"]:
            row = db.execute("SELECT * FROM signed_skill_installed WHERE id=?", (dep["skill_id"],)).fetchone()
            if row is None or row["digest"] != dep["manifest_sha256"] or row["consent_expires_at"] <= now:
                fail("skill_dependency_unavailable")
            child = parse_manifest(bytes(row["document"]))
            if child["version"] != dep["version"]:
                fail("skill_dependency_binding_mismatch")
            self._guard(db, child, now, expiries)
            expiries.append(row["consent_expires_at"])
            self._dependencies(db, child, now, expiries, seen=seen, budget=budget)

    def _event(self, db, event: str, target: str, object_digest: str, now: int) -> int:
        last = db.execute("SELECT sequence,event_hash FROM signed_skill_events ORDER BY sequence DESC LIMIT 1").fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, "")
        body = [seq, event, target, object_digest, now, previous]
        db.execute("INSERT INTO signed_skill_events VALUES(?,?,?,?,?,?,?)", (*body, sha256(canonical(body))))
        return seq

    def _verify(self, document: bytes, signature: bytes, package: bytes):
        manifest = parse_manifest(document)
        key = self._key(manifest, self._now())
        if type(signature) is not bytes or len(signature) != 64:
            fail("skill_signature_invalid")
        outcome = self._calls.run(lambda: (verify_signature(key, document, signature),
                                          inspect_package(manifest, package))[1], timeout_seconds=8)
        if outcome.state != "completed":
            # No worker's private error text or untrusted package content reaches logs.
            fail("skill_package_verification_failed")
        return manifest, outcome.value

    def install(self, document: bytes, *, signature: bytes, package: bytes, consent: InstallConsent) -> CheckedSkill:
        if (type(consent) is not InstallConsent or consent.subject != self.subject
                or not timestamp(consent.expires_at) or type(document) is not bytes
                or consent.manifest_sha256 != sha256(document)):
            fail("skill_exact_consent_required")
        manifest, files = self._verify(document, signature, package)
        fingerprint = sha256(document)
        expiries = [consent.expires_at]
        with self._transaction(expiries=expiries) as (db, now):
            if consent.expires_at <= now:
                fail("skill_consent_expired")
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            old = db.execute("SELECT * FROM signed_skill_installed WHERE id=?", (manifest["skill_id"],)).fetchone()
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
                    return CheckedSkill(document, files, old["consent_expires_at"], old["event_sequence"])
            if db.execute("SELECT COUNT(*) FROM signed_skill_events WHERE event='installed'").fetchone()[0] >= self.maximum_entries:
                fail("skill_installation_capacity_exhausted")
            until = min(consent.expires_at, manifest["expires_at"])
            seq = self._event(db, "installed", manifest["skill_id"], fingerprint, now)
            db.execute("INSERT INTO signed_skill_installed VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "document=excluded.document,signature=excluded.signature,digest=excluded.digest,consent_expires_at=excluded.consent_expires_at,event_sequence=excluded.event_sequence",
                (manifest["skill_id"], document, signature, fingerprint, until, seq))
            return CheckedSkill(document, files, until, seq)

    def resolve(self, skill_id: str, *, package: bytes) -> CheckedSkill:
        name(skill_id)
        expiries: list[int] = []
        with self._transaction(expiries=expiries) as (db, now):
            row = db.execute("SELECT * FROM signed_skill_installed WHERE id=?", (skill_id,)).fetchone()
            if row is None:
                fail("skill_unknown")
            document, signature, fingerprint = bytes(row["document"]), bytes(row["signature"]), row["digest"]
            manifest = parse_manifest(document)
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            expiries.append(row["consent_expires_at"])
        manifest, files = self._verify(document, signature, package)
        expiries = []
        # The object must still be the same admitted version after expensive verification.
        with self._transaction(expiries=expiries) as (db, now):
            current = db.execute("SELECT * FROM signed_skill_installed WHERE id=?", (skill_id,)).fetchone()
            if current is None or current["digest"] != fingerprint or current["event_sequence"] != row["event_sequence"]:
                fail("skill_admission_changed")
            self._guard(db, manifest, now, expiries)
            self._dependencies(db, manifest, now, expiries)
            expiries.append(current["consent_expires_at"])
            return CheckedSkill(document, files, current["consent_expires_at"], current["event_sequence"])

    def revoke(self, kind: str, target: str) -> dict:
        if type(kind) is not str or kind not in {"skill", "publisher", "key", "package"}:
            fail("skill_revocation_kind_invalid")
        digest(target) if kind == "package" else name(target)
        with self._transaction(revocation=True) as (db, now):
            if db.execute("SELECT 1 FROM signed_skill_revocations WHERE kind=? AND target=?", (kind, target)).fetchone():
                return {"revoked": True, "scope": kind}
            count = db.execute("SELECT COUNT(*) FROM signed_skill_revocations").fetchone()[0]
            if count >= self.maximum_entries:
                if not db.execute("SELECT suspended FROM signed_skill_policy WHERE id=1").fetchone()[0]:
                    self._event(db, "suspended", "registry", "", now)
                    db.execute("UPDATE signed_skill_policy SET suspended=1 WHERE id=1")
                return {"revoked": True, "scope": "registry", "reason": "revocation_capacity"}
            self._event(db, "revoked." + kind, target, "", now)
            db.execute("INSERT INTO signed_skill_revocations VALUES(?,?)", (kind, target))
            return {"revoked": True, "scope": kind}

    def verify_local_audit(self) -> dict:
        """Local chain consistency only; no external append-only witness or pin."""
        with self._transaction(revocation=True) as (db, _):
            previous, count = "", 0
            for row in db.execute("SELECT * FROM signed_skill_events ORDER BY sequence"):
                count += 1
                body = [row["sequence"], row["event"], row["target"], row["digest"], row["observed_at"], row["previous_hash"]]
                if row["sequence"] != count or row["previous_hash"] != previous or sha256(canonical(body)) != row["event_hash"]:
                    fail("skill_local_audit_invalid")
                previous = row["event_hash"]
            return {"events": count, "last_hash": previous, "external_witness_verified": False}
