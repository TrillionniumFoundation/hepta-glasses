# Signed Skill package transparency inclusion verification

Status: incremental HG-0087/skills source implementation; Skills and aggregate
HG-0087 remain **OPEN**. Owner: skills. Source:
`services/skills/package_transparency.py` and
`services/skills/signed_registry.py`. Tests:
`services/skills/test_package_transparency.py`. Contract:
`contracts/signed-skill-transparency-v1.json`. Operations:
`docs/operations/PACKAGE_TRANSPARENCY_RUNBOOK.md`.

## Responsibility and trust boundary

This component verifies that the exact canonical Skill manifest supplied to
`SignedSkillRegistry.install` is included in one externally signed Merkle-tree
checkpoint. The log key set, key validity windows, log identity, required/optional
mode and trusted clock are supplied by trusted host configuration. A package may
not select its own log key or verification mode.

The component does **not** operate a transparency log, submit manifests, fetch a
checkpoint, discover trust roots, prove publisher ownership, compare views with
other clients, provide gossip, witness co-signatures, or detect a split view by
itself. A valid inclusion proof establishes only that one exact manifest hashes
to the signed root under the configured log key. It is not proof that the log is
honest, globally consistent, independently witnessed, available, or accepted by
a production authority.

The public API is deliberately narrow:

| API | Contract |
|---|---|
| `TransparencyLogKey(log_id, public_der, not_before, not_after)` | One externally governed Ed25519 checkpoint key; exact 44-byte SPKI DER and fixed log binding |
| `TransparencyProof(checkpoint, signature, leaf_index, audit_path)` | Canonical checkpoint bytes, raw detached signature and exact RFC6962 inclusion path supplied by trusted ingress |
| `TransparencyVerifier(keys, clock, required=True)` | Immutable verifier policy and key set; exposes only its deterministic policy binding and verification method |
| `verify(document, proof)` | Validate checkpoint, key/time/signature and exact manifest inclusion; return immutable metadata and effective expiry |
| `SignedSkillRegistry(..., transparency_verifier=...)` | Persist the verifier-policy digest as part of the registry policy; only the exact built-in verifier class is accepted |
| `install(..., transparency=proof)` | Require/validate proof according to fixed policy and carry its expiry into the final SQLite admission transaction |

`required=True` rejects a missing proof. `required=False` permits a completely
absent proof, but a supplied malformed proof still fails; optional mode is not a
fallback after failed verification. If no verifier is configured, supplying a
proof fails as `skill_transparency_unconfigured` rather than being ignored.

## Checkpoint and Merkle contract

Checkpoint bytes are canonical compact sorted UTF-8 JSON with exactly:

```json
{
  "expires_at": 1200,
  "issued_at": 1000,
  "key_id": "log-v1",
  "log_id": "primary-log",
  "root_sha256": "<64 lowercase hexadecimal characters>",
  "schema_version": 1,
  "tree_size": 4
}
```

Duplicate keys, extra fields, noncanonical bytes, booleans masquerading as
integers, a nonpositive or over-63-bit tree size, invalid digests and malformed
timestamps are rejected. A checkpoint may live for at most 24 hours. It must be
issued within the configured key validity window, may not be issued in the
future, and may not outlive that key.

The signature domain is the literal ASCII bytes:

```text
HEPTA-SKILL-TRANSPARENCY-V1\n
```

followed by the exact checkpoint bytes. Signatures are raw 64-byte Ed25519.
Verification uses the same root-owned absolute OpenSSL policy, sanitized process
environment and sealed anonymous Linux memory descriptors as package signature
verification. There is no HMAC, unsigned, caller-executable or disk-key fallback.

The Merkle algorithm uses the RFC6962 domain separation:

- leaf hash: `SHA-256(0x00 || canonical_manifest_bytes)`;
- node hash: `SHA-256(0x01 || left_hash || right_hash)`.

The leaf index must be an integer in `[0, tree_size)`. The audit path is an exact
tuple of at most 64 32-byte hashes. The verifier consumes the path according to
the declared tree size and rejects an extra, missing or incorrect sibling. The
regression suite covers every leaf position for tree sizes 1 through 17,
including non-power-of-two trees.

## Registry integration, concurrency and expiry

The verifier key policy is copied and frozen during construction. Duplicate
public-key aliases under different key IDs are rejected. The verifier exposes a
deterministic binding over required mode, key ID, log ID, key fingerprint and
validity. `SignedSkillRegistry` incorporates that binding into its persisted
policy; adding, removing or changing transparency policy on an established
registry requires an explicit reviewed policy migration. A verifier subclass is
not accepted, because Python method override must not replace the built-in
cryptographic checks.

In a strict installation, transparency verification completes before the package
is admitted. The checkpoint/key effective expiry is appended to the same list as
consent, manifest and publisher-key deadlines. The final `BEGIN IMMEDIATE`
transaction samples the trusted clock after lock waiting and again before commit.
If the proof or key expires while package verification is running or while the
transaction waits, no installation or matching audit event commits.

The effective transparency expiry is included in the stored installation expiry,
so later `resolve` operations stop after that time. The registry does not persist
the audit path, checkpoint document or a durable external log receipt. The source
therefore provides admission-time inclusion verification and deadline custody,
not a long-term evidence archive. Production provenance retention requires a
separately governed immutable evidence store with privacy and retention controls.

A log-key configuration can be rotated only by opening a separately reviewed
policy migration. Existing installed manifests are not silently rebound to a
new log. Local SQLite policy binding does not prevent a privileged operator from
restoring an older whole database, replacing the configured files, or running an
already-open old binary. External anti-rollback/fencing remains required.

## Failure and recovery

| Failure | Result | Permitted continuation |
|---|---|---|
| Missing proof in required mode | No package admission | Obtain the actual proof from the configured log path |
| Invalid checkpoint/signature/path | No package admission | Correct the log object; never downgrade to unsigned/HMAC or optional mode in place |
| Unknown/mismatched log key | No package admission | Use the externally reviewed key configuration and exact log identity |
| Proof/key expires during verification or lock waiting | Transaction rolls back | Obtain a fresh checkpoint/proof and fresh user authority where required |
| Verifier policy changes on reopen | Startup rejects policy drift | Run a separately reviewed migration; do not patch the stored digest |
| Verification runtime is unavailable | No package admission | Restore the trusted Linux/OpenSSL boundary; do not invoke another executable |
| Database/commit failure after verification | No successful installation is returned | Preserve state and retry only while every original authority remains valid |

A proof becoming invalid after an already completed install cannot retract bytes
previously returned to a caller. Runtime consumers must resolve current registry
authority before execution/effects. Transparency inclusion is also independent
of exact-manifest user consent, publisher signature, package byte validation,
dependency checks and local revocation; all remain mandatory.

## Configuration and deployment

Use a controlled Linux verifier host and provision log keys out of band. Verify
log ownership, key fingerprints, validity windows, rotation procedures and
incident contacts independently. Treat `required=False` as a distinct reviewed
policy, not a temporary availability switch. Never expose verifier construction,
key maps, required mode or the trusted clock directly to package/client input.

The verifier accepts proofs supplied to the install call but performs no network
I/O. The host is responsible for bounded authenticated retrieval, caching,
retention and freshness of those bytes. A fixture key or locally generated tree
is not a production log. Store no package, checkpoint or audit path in logs unless
an approved evidence/privacy policy explicitly requires it.

Run:

```bash
python3 -m unittest services.skills.test_package_transparency -v
python3 -m unittest services.skills.test_signed_registry -v
python3 -m unittest services.skills.test_signed_registry_schema -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m compileall -q services/skills
```

Then require all canonical repository/platform/source-evidence jobs on one
unchanged head, independently inspect its artifact and obtain eligible review.

## Remaining HG-0087 work

This closes only the source subtask for validating one signed inclusion proof.
Skills remains OPEN for an actually operated append-only log, checkpoint
consistency, cross-client gossip or independent witness quorum, external
publisher-root administration, durable transparency evidence retention,
arbitrary-code OS/process isolation, capability-mediated I/O, nonempty-domain
egress enforcement, running-task termination, authenticated consent service,
encrypted package custody and independent deployment qualification.
