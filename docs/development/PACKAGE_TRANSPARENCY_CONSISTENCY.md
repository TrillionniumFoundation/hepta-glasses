# Package transparency consistency floor and witness quorum

Status: incremental HG-0087/skills source hardening; the Skills slice and
aggregate remain **OPEN**. Implementation:
`services/skills/package_transparency.py`. Regression is included in
`services/skills/test_signed_registry_schema.py`. Machine contract:
`contracts/signed-skill-transparency-v1.json`. Operations:
`docs/operations/PACKAGE_TRANSPARENCY_WITNESS_RUNBOOK.md`.

## Responsibility and trust boundary

The existing verifier checks that one exact canonical Skill manifest is included
in one Ed25519-signed RFC6962 checkpoint. This increment can additionally prove
that the supplied checkpoint extends one immutable configured tree root and that
an immutable quorum of configured Ed25519 witness identities signed that exact
checkpoint identity.

The verifier remains a local consumer of externally supplied evidence. It does
not submit manifests, fetch proofs, operate the append-only log, publish or store
the newest checkpoint, compare independent client views, establish that witness
operators are organizationally independent, or provide a remote anti-rollback
anchor. A fixture key or locally generated signature is not external evidence.

## API and policy

`TransparencyProof` retains its original checkpoint, signature, leaf index and
inclusion path fields and adds two default-empty immutable tuples:

- `consistency_path`: RFC6962 proof from the configured floor to the presented
  checkpoint;
- `witnesses`: canonical witness statements plus detached signatures.

Existing four-argument callers remain valid. Existing verifier policy binding is
byte-for-byte unchanged when neither advanced feature is configured. Enabling or
changing a floor, witness key/identity, validity window or quorum changes the
verifier binding and therefore requires an explicit reviewed registry policy
migration rather than silently reinterpreting an installed registry.

`TransparencyCheckpointAnchor` binds a log ID, old tree size and old root. It is
part of trusted host configuration, not package input. For every supplied proof:

- a smaller tree is rejected;
- equal size requires the identical root and an empty consistency path;
- a larger tree requires a valid RFC6962 consistency proof; and
- a consistency path supplied without configured policy is rejected.

This is a consistency floor, not a persisted latest-checkpoint service. Two later
checkpoints can both extend the floor while being presented out of order; global
monotonicity still requires a separately operated checkpoint store/gossip layer.

## Witness statement and quorum

Each canonical witness statement has exactly these fields:

```text
schema_version, witness_id, key_id, log_id, tree_size, root_sha256,
checkpoint_sha256, issued_at, expires_at
```

The detached Ed25519 signature domain is:

```text
HEPTA-SKILL-TRANSPARENCY-WITNESS-V1\n
```

A statement must match the already verified log checkpoint, including the exact
SHA-256 of its canonical checkpoint document. Key validity, statement validity
and current trusted time are checked. The effective installation expiry is the
minimum of consent, manifest, Log key, checkpoint, witness key and witness
statement authority.

The quorum is counted by distinct `witness_id`, not key ID. Multiple rotation
keys for one identity can be configured, but two signatures from that identity
never create two votes. Duplicate identity votes are rejected rather than
silently deduplicated. Every supplied statement is validated; a bad extra proof
cannot be ignored to retain a passing quorum.

## Failure and compatibility behavior

Proof shapes are exact tuples, paths contain at most 64 32-byte hashes and the
witness bundle contains at most 64 statements. Canonical JSON rejects duplicate
keys, extra fields, booleans in integer positions, nonfinite values and malformed
UTF-8. OpenSSL is selected by the existing trusted absolute-path policy, receives
sealed anonymous descriptors and a sanitized environment.

Optional transparency mode still accepts a wholly absent proof. Once a proof is
supplied, all configured inclusion, consistency and witness checks apply. A base
verifier without advanced policy rejects unexpected consistency or witness data.
Verifier configuration is immutable after construction, and SignedSkillRegistry
continues to reject subclass-based verifier substitution.

## Verification and evidence ceiling

Deterministic tests cover every old/new tree prefix through size 23, equal-tree
rules, rollback/fork/corrupt proofs, distinct-identity quorum, key rotation,
statement/checkpoint binding, signature and time failures, unconfigured evidence,
legacy binding compatibility and persisted registry policy drift.

These checks establish source behavior only. Production closure still requires
an operated log, authenticated proof retrieval, independently administered
witnesses and keys, dynamic checkpoint publication/retention, cross-client gossip,
split-view response, remote anti-rollback and independent deployment acceptance.
