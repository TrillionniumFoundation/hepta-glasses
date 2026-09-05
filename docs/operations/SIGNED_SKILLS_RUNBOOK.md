# Signed Skills operations and incident runbook

Scope: local public-key package admission. Owner: skills. Contract:
`contracts/signed-skill-package-v1.json`. Design:
`docs/development/SIGNED_SKILLS.md`. HG-0087/skills remains OPEN.

## Before enabling an ingress

Use trusted Linux with root-owned non-writable system OpenSSL, memfd sealing and
`/proc/self/fd`. Run the service under a least-privileged account, umask 077 and a
private local storage directory. Apply operational encryption and restrictive
backup access to the metadata database; this library does not encrypt it. Do not
place it on a network filesystem or in an untrusted writable directory.

Publisher keys must come from the reviewed external publisher authority. Verify
the publisher, key ID, exact Ed25519 public DER and validity out of band. Never
load a key from the package being verified. Private signing keys are not part of
this service. A new key requires a new ID and a reviewed overlap policy; changing
an existing key ID's binding fails startup rather than silently rotating it.

Authenticate the subject and obtain actual approval of the exact manifest
SHA-256 and lifetime. Construct `InstallConsent` only inside that trusted flow.
Do not expose dataclass construction from arbitrary client JSON as authorization.
A package signed by a publisher is not permission to access user data or devices.

No executor or egress firewall is installed by this component. Keep production
Skill execution disabled until an independently reviewed sandbox, resource and
network controls, consent integration and final effect gateway are connected.
Do not route checked package contents into an unrestricted Python/shell worker.

## Installation and resolution

Accept only canonical manifest bytes, a raw detached Ed25519 signature and the
exact bounded version-1 ZIP. Install under fixed host capability/domain policy.
Record safe identifiers, manifest/package digests and the resulting event
sequence; do not log package contents, private credentials or sensitive user
context. Correct a packaging error at its source instead of loosening parser
checks or permitting a fallback signature scheme.

For resolution, resupply the exact package and consume only the returned
immutable file snapshots. Never replace them with a second filesystem read or
cache the result as permanent authority. Dependency upgrades require newly
signed and consented parent bindings. A failed current resolve must stop the run,
not silently load a previously cached version.

## Revocation and incident handling

Revoke by Skill ID, publisher ID, signing key ID or package digest using the
trusted operator path. Unknown IDs can be tombstoned before installation. Open a
second connection/process and confirm both installation and resolution are
rejected. Verify dependent Skills also reject the revoked package transitively.
Keep the database and denial state across restarts.

Key/publisher compromise requires stopping the relevant execution route in the
separate sandbox service and revoking already issued effect authority there.
This registry cannot kill a running task or undo a prior physical effect.
The local event chain does not constitute a provider or independent incident
attestation. Preserve genuine external records through the existing evidence
process rather than inventing signatures or declaring local events sufficient.

At revocation capacity the registry suspends all admission/resolution. Treat that
as an incident requiring reviewed storage/policy migration, not a reason to
remove tombstones. There is no un-revoke or unsuspend API. During clock failure,
new admission fails; emergency denial still works and audit timestamps retain the
last observed trusted time. Restore clock health without resetting its history.

## Crash, storage and upgrade recovery

A failure before an install transaction commits leaves no committed installation
or matching install event. Retry only the same still-valid signed package and
actual consent. A completed revoke remains terminal. Never restore an old
snapshot into an active registry: that may forget revocations, consent expiry or
version history. This component has no remote monotonic checkpoint or replicated
recovery service; unresolved rollback risk must keep execution unavailable.

Schema/policy mismatch stops startup. Rehearse any migration on controlled copies,
retain immutable old version/key bindings and validate the full dependency graph.
Do not rewrite schema markers, delete denial records, import HMAC manifests as
verified public-key packages or patch persisted consent deadlines to recover.
Metadata backup, encryption and package-vault retention require their own
operating contracts and independently witnessed drills.

## Verification and acceptance

Run the dedicated signature/registry suite, module ownership and handoff checks,
all service/adapter tests, compilation and every canonical CI lane on one final
head. Inspect the downloaded source artifact and compare changed-file hashes.
Seek eligible independent review without dismissing existing objections. The
known separate identity freshness defect and previously blocked identity,
speech and Memory writes are not fixed by this independent Skills increment.

A green source suite is not deployment, sandbox/egress qualification, external
publisher trust or product release approval. Confirm the source and independent
acceptance states separately. Do not merge, release or enable execution merely
because `verify_local_audit()` reports a consistent chain.
