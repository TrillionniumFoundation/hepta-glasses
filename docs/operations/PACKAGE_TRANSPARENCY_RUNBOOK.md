# Signed Skill package transparency operations

Owner: skills. Design: `docs/development/PACKAGE_TRANSPARENCY.md`.
Contract: `contracts/signed-skill-transparency-v1.json`.
HG-0087/skills remains OPEN; this runbook is not evidence that an external log or
witness service exists.

## Provisioning

Provision each `TransparencyLogKey` from an independently reviewed log authority.
Verify the exact log ID, key ID, 44-byte Ed25519 SPKI DER fingerprint and
not-before/not-after times out of band. Do not read a verification key from the
package, checkpoint, provider response or unauthenticated request. Use a new key
ID for rotation and retain a reviewed overlap/revocation procedure.

Choose `required=True` for production admission unless an explicitly approved
policy says otherwise. The required flag and full key configuration are bound to
the persistent registry policy. Do not toggle optional mode to recover from log
outage. An established registry rejects policy drift; plan a reviewed migration
rather than editing SQLite rows or verifier internals.

The verifier configuration is immutable after construction. Create it and the
registry in trusted startup code. Do not expose constructors through generic
configuration JSON, plugin code or client-controlled dependency injection.

## Proof acquisition and admission

Acquire canonical checkpoint bytes, raw detached signature, leaf index and audit
path through a bounded authenticated log client outside this module. Confirm the
returned bytes are associated with the intended environment and log. The source
verifier itself does not fetch, submit, retry or cache network objects.

Pass the exact canonical Skill manifest to both publisher verification and the
transparency proof. Never regenerate/reformat the manifest between proof
construction and install. A changed whitespace byte, manifest field, root, tree
size, leaf index or sibling path must fail.

Treat verification errors as terminal for that admission attempt. Do not:

- replace the configured log key with a key from the failing response;
- accept an unsigned checkpoint or HMAC substitute;
- remove the proof in required mode;
- extend checkpoint timestamps;
- reuse a proof for a modified manifest; or
- bypass final transaction expiry checks.

The proof/key deadline is carried into final installation and persisted as an
upper bound on later resolution. If verification or SQLite waiting consumes the
remaining lifetime, obtain a newly issued checkpoint and proof. Do not patch the
stored installation expiry.

## Outage and compromise response

For a suspected log-key compromise, stop new package admission, preserve the
registry and actual external evidence, and follow the log authority's verified
revocation/rotation process. Local Skill revocation can deny a package, key,
publisher or Skill ID, but does not remove a manifest from the remote log or prove
a compromised checkpoint was never observed.

A valid inclusion proof is not consistency or split-view proof. Compare signed
checkpoints using a separately reviewed consistency/gossip/witness process before
claiming a log is globally append-only. Do not infer independent transparency
from `verify_local_audit()`; that method checks only the registry's local chain.

The registry intentionally does not retain the full proof/checkpoint. Archive
required provenance in a separately access-controlled, append-only evidence
system, keyed by manifest/checkpoint digest. Keep personal or confidential
package metadata out of general logs. The local returned checkpoint hash is an
integrity identifier, not an external receipt.

## Database and upgrade handling

Stop/drain old service processes before enabling transparency policy. Already
running old binaries cannot be retroactively fenced by this source change.
Adding or changing transparency on an existing registry requires explicit policy
migration. Never delete or recreate the registry, lower its schema marker, edit
the stored policy digest, restore a stale snapshot or substitute an empty database
to make startup pass.

The current storage schema does not add transparency tables. This means there is
no automatic proof migration, proof archive, remote anti-rollback checkpoint or
cross-host replication. Backup replacement and whole-database rollback remain
external operational risks. Keep package execution disabled where those risks
cannot be bounded.

## Verification and acceptance

Run the transparency, signed-registry and schema suites, complete repository
validators, all service/adapter tests, compilation and every canonical CI lane on
the exact final head. Download and inspect the source-evidence artifact and obtain
an eligible non-pusher/CODEOWNER decision after the last source change.

Local random Ed25519 keys and Merkle trees test the algorithm only. They do not
establish a real log, publisher authority, witness quorum, gossip, provider/device
qualification or production acceptance. Keep PR #101 Draft until the broader
plan is satisfied; do not self-approve, merge, deploy or use administrator bypass.
