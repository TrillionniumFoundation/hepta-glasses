# Signed Skill package admission and durable revocation

Status: incremental source candidate under HG-0087/skills; aggregate OPEN.
Owner: skills. The primary modules are `services/skills/signed_package.py` and
`services/skills/signed_registry.py`. The contract is
`contracts/signed-skill-package-v1.json`; operations are in
`docs/operations/SIGNED_SKILLS_RUNBOOK.md`.

## Responsibility and API

This component verifies an externally signed Skill package, records host-approved
installation, resolves the exact installed bytes and propagates local revocation
through exact dependency bindings. It never runs a Skill, extracts files to disk,
opens a provider connection, grants a device lease or installs a sandbox. The
existing `SkillRegistry`/`SkillTrustStore` in `services/skills/registry.py` remain
legacy development references. There is no implicit conversion of their HMAC
signatures to the new format and no HMAC or unsigned fallback.

| API | Input and result |
|---|---|
| `PublisherKey` | Publisher identity, exact 44-byte Ed25519 public SPKI DER, not-before and not-after times; no private signer |
| `SignedSkillRegistry(...)` | Trusted local SQLite path, authenticated subject namespace, pinned public keys, capability/domain policy and trusted clock |
| `install(document, signature, package, consent)` | Verify canonical signed manifest and exact package; atomically record the exact consent-bound version and local audit event |
| `resolve(skill_id, package=...)` | Recheck admission, re-verify signature and bytes, then recheck current version/revocations/dependencies before returning |
| `revoke(kind, target)` | Monotonic denial for a Skill, publisher, signing key or package digest; unknown IDs can be denied before admission |
| `verify_local_audit()` | Verify bounded local event-chain consistency; always reports `external_witness_verified=false` |

`InstallConsent(subject, manifest_sha256, expires_at)` is a typed result from an
authenticated host consent flow. It is not a proof merely because an API client
constructs it. The host must obtain user approval of the exact manifest and
verify the consent lifetime before calling this API. The manifest includes every
requested capability, data class, network domain, risk tier and dependency.
Changing any of those fields requires a different signature and a new exact
approval. Broad consent from a previous version is not automatically transferred.

`CheckedSkill` returns immutable manifest bytes and an immutable tuple of
`(path, bytes)` file snapshots. Its `manifest` property returns a defensive copy.
A caller must not replace these bytes with a later filesystem read. The object
is a checked snapshot, not a perpetual execution permit. A future sandbox must
resolve current authority for each run and route every physical/external effect
through the separate policy/lease gateway; cached package approval cannot bypass
revocation or authorize effects.

## Wire format, cryptography and package bytes

Manifest JSON has an exact field set and deterministic UTF-8 encoding with sorted
keys and compact separators. Duplicate keys, extra fields, nonfinite values,
noncanonical bytes, ambiguous booleans, unordered/duplicate set arrays and invalid
versions are rejected. SemVer is exactly three nonnegative decimal components;
prerelease/build suffixes are outside version 1.

The Ed25519 signature preimage is the literal ASCII prefix
`HEPTA-SKILL-PACKAGE-V1` followed by a newline and the canonical manifest bytes.
The signature is exactly 64 raw bytes. Algorithm selection is not caller input.
The public key is selected from an externally provisioned, immutable map and is
bound to a single publisher. Aliased public keys under different key IDs and
changed key/publisher/validity bindings for an existing ID are rejected. The
manifest must be issued within the key validity window, not in the future, and
must expire no later than the key. Key validity and manifest expiry are rechecked
inside final admission, not only before the expensive cryptographic operation.

Verification reuses the existing trusted absolute OpenSSL resolver and minimal
subprocess environment. Public key, message and detached signature occupy sealed
anonymous Linux memory descriptors. There is no caller-supplied executable,
provider-returned trust key, shell invocation, private signing key or disk-file
fallback in verification. Linux memfd/seals and `/proc/self/fd` are required.

The package is a bounded, single-disk ZIP containing regular, uncompressed files.
Its full raw SHA-256 is signed, as is an exact per-file path/size/SHA-256 inventory.
An end-of-directory check bounds the member count before constructing ZipFile.
The local headers, central-directory interpretation, file sizes and CRC/digests
are checked. Version 1 rejects compression, encryption, data descriptors, ZIP64,
comments, extra fields, prefixes, trailing bytes, gaps, hidden local entries,
directories, links and duplicate members. The parser never writes package bytes
onto the host filesystem.

Paths use a restricted ASCII relative format. Absolute paths, traversal,
backslashes, drive/stream syntax, reserved Windows names, trailing dots,
case-insensitive collisions and file-versus-directory collisions are rejected.
The declared entrypoint must appear in the signed inventory. This is a deliberately
narrow packaging profile, not support for every legal ZIP archive.

## State, concurrency and dependency binding

`DurableDatabase` supplies SQLite WAL, FULL synchronous mode and `BEGIN IMMEDIATE`.
Admission and resolution transactions serialize independent local connections.
Signature verification and package parsing occur outside the write transaction
in a four-worker bounded pool. The final transaction samples the trusted clock
again after lock waiting, validates live authority and dependencies, and checks
all collected expiry bounds again before committing. Local clock rollback after
an observed operation fails admission. This is not a trusted global time service
or protection against restoring an entire older database.

The registry stores canonical manifest bytes, signature, exact document digest,
consent expiry and event sequence, but does not store the package payload or any
private signing key. Each database belongs to one subject and fixed policy.
Callers resupply the package bytes on resolution, which prevents a mutable
pathname from silently replacing a previously checked package.

Installed versions cannot go backwards. An equal version must have exactly the
same manifest digest; replay cannot extend its existing consent. Expired consent
on the same version requires a newly published/approved version. A different
publisher cannot take over an already installed Skill ID through an upgrade.
A newer signing key under the same publisher may be added under a fresh key ID;
an existing key binding cannot be rewritten by reopening the database.

Each dependency binds a Skill ID, exact version and signed manifest digest.
Resolution rechecks its current consent, key/manifest validity and Skill/publisher/
key/package revocations transitively. Missing, upgraded, expired or revoked
dependencies fail the parent closed. Dependency upgrade intentionally invalidates
old parent bindings until the publisher signs and the user approves updated
parent metadata. Recursion is bounded to 16 levels and 128 visited nodes per
operation. Self-reference, cycles and excessive graphs fail admission.

Revocation is terminal within this database. There is no un-revoke or destructive
reset API. It is legal to revoke unknown IDs before an in-flight installation
can create them. Expensive verification never commits a late result after a
matching revocation. Resolution also compares the exact installed digest and
event sequence after verification, so a concurrent upgrade cannot return an old
snapshot as current authority.

## Failure and recovery

| Failure | Durable result | Permitted recovery |
|---|---|---|
| Invalid signature, package, pin or exact consent | No installation | Correct actual inputs; never switch to HMAC or bypass verification |
| Verification timeout/capacity exhausted | No installation; worker retains permit until completion | Restore bounded host capacity; do not create unlimited workers |
| Consent/key/manifest expires while waiting | Admission rolls back | Obtain fresh signed metadata and actual approval as necessary |
| Revocation during verification | No install/current resolve result | Preserve denial; investigate through authenticated operator workflow |
| Process exits before admission commit | Neither install nor its audit event becomes committed | Retry the same exact approved package only while still valid |
| Process exits after revoke commit | Revoke survives reopening | Reopen the same database and continue to deny |
| Dependency or current version changes | Parent/old resolve fails | Sign and approve an updated exact dependency set |
| Local storage/transaction error | No success is returned | Repair storage without discarding revocations or version history |

A checked snapshot returned immediately before a later revocation is still only
a snapshot. Cancellation of an already running sandbox and final effect checks
are responsibilities of the execution integration, which is not implemented
here. A host timeout is not evidence that arbitrary external work was killed.

## Configuration, migration and resource bounds

Defaults and fixed limits: 32 pinned keys, 64 capability/domain entries per
manifest/policy, 32 KiB manifest, 16 MiB raw ZIP, 128 files, 1 MiB per file, 32
direct dependencies, 30-day maximum signed lifetime, 300-second declared task
timeout, four verifier workers, five-second OpenSSL subprocess deadline and
eight-second caller verification wait. The declared task timeout is metadata,
not execution enforcement by this component. SQLite lock waiting has its separate
five-second bound; these are not hard real-time end-to-end latency guarantees.

The default lifetime installation-event and revocation-row budgets are 4096 each,
configurable only as part of the persisted policy within 1..10000. No old record
is silently evicted to admit a new installation. When revocation capacity is
exhausted, a further denial atomically suspends the entire registry instead of
forgetting an earlier revoke or falsely claiming a specific tombstone was saved.
Repeated suspension is idempotent. Emergency revocation remains available during
a clock incident and records the last trusted observed time, not a fabricated
fresh timestamp.

Schema component `signed_skills`, version 1, creates namespaced tables. Unknown
versions and preexisting unmarked component tables are rejected. Changing the
subject, policy or configured lifetime budget requires a reviewed migration;
there is no implicit import from the old reference registry. Store keys and
policy out of band, use a private operator-owned local directory, and do not use
network filesystems, stale restored snapshots or untrusted writable directories.
The metadata database is not encrypted by this component. The package vault,
backup exclusion, anti-rollback anchoring and safe archival are separate work.

## Operations, verification and claim boundary

Run `python3 -m unittest services.skills.test_signed_registry -v` plus the complete
repository and seven-lane exact-head CI matrix. The tests use actual randomly
generated ephemeral Ed25519 keys, real OpenSSL verification and real SQLite.
Keys used by the tests stay in memory/anonymous descriptors and are neither
production credentials nor evidence of a trusted publisher. Tests cover
cross-connection races, actual process exits, package confusion, changed keys,
exact consent, dependency invalidation and final transaction expiry rollback.

The event chain is local diagnostics and tamper detection, not externally
witnessed package transparency. It does not authenticate the host operator,
prevent privileged database rewriting or establish third-party log inclusion.
HG-0087/skills remains OPEN for isolated execution, actual egress enforcement,
external publisher-root administration/transparency, authenticated consent
integration, running-task revocation, encrypted package custody and independent
package qualification. Source tests cannot close provider/device/product gates.

Implementation references: Python `zipfile` documentation, SQLite transaction
documentation and OpenSSL `pkeyutl` Ed25519/raw-input documentation. The component
contract is authoritative for the intentionally narrower supported ZIP profile.

## Optional signed-log inclusion admission

`services/skills/package_transparency.py` adds an optional, policy-bound
admission-time transparency verifier. In required mode, `install` must receive a
canonical signed checkpoint and exact RFC6962 inclusion path for the same
canonical manifest passed to publisher verification. The externally configured
log-key set, log identity, key validity and required flag are immutable after
construction and hashed into the persisted registry policy. A verifier subclass,
configuration drift, missing strict proof or a supplied invalid optional proof
fails closed.

The checkpoint/log-key effective expiry participates in the final SQLite
transaction and stored installation expiry, so verification or lock waiting
cannot extend a stale proof. The verifier performs no network fetch and the
registry does not archive the checkpoint/path. This is one-manifest inclusion
verification only—not an operated log, consistency/gossip, split-view detection,
independent witness quorum, publisher-root governance or durable provenance
archive. See `docs/development/PACKAGE_TRANSPARENCY.md` and
`contracts/signed-skill-transparency-v1.json`.
