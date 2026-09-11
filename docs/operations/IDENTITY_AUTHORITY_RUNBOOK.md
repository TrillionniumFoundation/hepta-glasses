# Durable identity authority operating contract

Status: source candidate, not deployed. Owner: cloud-security. This runbook does
not grant a tenant, KMS/HSM key, platform-verifier approval or mobile permission.
Follow the active blocker plan and retain HG-0087 OPEN for the missing integrations.

## Prerequisites and configuration

Use a trusted Linux host with root-owned non-writable `/usr/bin/openssl`, memfd
sealing and `/proc/self/fd`. The account service must authenticate users and
perform appropriate enrollment/step-up checks before subject, device or session
admission. No model or arbitrary client JSON may call store methods directly.

Provision local persistent SQLite storage under a restrictive owner-controlled
directory, with operational volume encryption and controlled backups. Do not use
`:memory:`, shared network filesystems or stale restored databases. Select and
persist issuer, allowed scopes and TTL policy. Protect the policy configuration;
it is not a per-request override. The library has no HTTP account server or
production launcher to deploy independently.

Deploy a real authority broker implementing the two paths in
`contracts/identity-authority-v1.json`. It must authenticate workload identity,
actually verify Android/Apple proofs, and use the intended KMS/HSM signing key.
Populate an out-of-band public Ed25519 key set with KIDs, validity windows and
revocation state. A key returned inside a signing response is never a trust root.
Set exact HTTPS host and short-lived workload credential callback. No credentials
belong in source, logs, examples, fixtures or ordinary artifacts.

## Startup and normal handling

Open `DurableIdentityStore` with the reviewed policy; schema or policy mismatch
must stop admission. Do not change a version marker to silence a failure.
Construct `PinnedEd25519Verifier`, `HttpsAuthorityBroker` and
`DurableIdentityAuthority` in the trusted service composition. Do not silently
fall back to the reference HMAC token service or unverified store admission.

At startup inspect `pending_tokens(limit=100)`. Interrupted preparing or
indeterminate tokens are non-active. Revoke their IDs through authorized recovery,
then allow a fresh token to be issued under a currently valid session. Do not
promote old rows or reuse an old signature to appear successful.

Create challenges only for authenticated and authorized enrollment. Pass the
exact issued challenge and proof to `enroll`. Only a correctly bound, fresh broker
verdict can reach atomic challenge consumption. Store proof digests and permitted
metadata, never the raw proof or challenge nonce in logs.

Create sessions under reviewed audience/scope policy. Issue tokens through the
full authority composition, not `commit_token` from a client assertion. On every
request verify signature, expected audience, nonempty required scopes and current
persistent authority. A successful token check does not authorize a future
physical action without the edge lease/policy/generation checks.

## Revocation and recovery drills

Exercise token, session, device and subject revocation separately. In every drill,
start signing, revoke through another database connection, and confirm no active
token is returned after the late signature. Reopen the database and confirm denial
persists. Revoke unknown device IDs while enrollment is in flight and confirm the
late verifier cannot create them.

Poll `events_after(cursor, limit=100)` through an authorized internal consumer.
Persist the consumer cursor only after downstream revokes are applied
idempotently. Verify websocket/realtime/model/capability consumers actually
terminate affected authority; merely reading an event is not completion evidence.
Downstream integration remains an open task in this increment.

Lost-device replacement requires a separately reviewed step-up recovery workflow.
Ordinary registration deliberately cannot revive a revoked ID or replace its
bound proof. Do not edit the database to get around that requirement. The old
sessions and token records must remain invalid when a replacement is admitted.

## Key rotation and outages

Provision and review the new public verification key before changing active KID.
Retain a valid old verification key only for the approved overlap interval. New
issuance must not outlive its key or session; revoked/expired/future keys fail
closed. Restart with a new immutable key map through the protected service
configuration. Never accept response-supplied keys, key aliases or unsigned tokens.

During broker outage stop new proof/signature admission. Existing tokens require
current local verification and durable authority checks; do not extend expiry.
Timed-out workers retain permits until exit. Repair provider connectivity and
isolation; do not increase worker counts indefinitely or infer remote failure
from a local timeout. Errors must remain redacted and must not dump provider bodies.

## Storage capacity, migration and rollback

Monitor admission-table row counts, pending tokens, revoke-feed lag, SQLite lock
contention, disk use and broker worker saturation. Revocation deliberately remains
available at the admission capacity limit. Apply authenticated ingress rate limits
so new-work or unknown-ID revocation requests cannot fill storage unchecked.

Before a migration, quiesce writers and take a SQLite-consistent controlled backup.
Validate a non-production copy, review policy changes explicitly and restart
admission only after recovery checks. Never restore stale revocation data into a
live service; forward repair or reconcile current authority first. Application
rollback must preserve schema and revocation compatibility. Full database loss,
multi-region recovery and cryptographic backup erasure require separate procedures.

## Verification and acceptance

Run targeted identity tests plus the full repository/metadata/coverage/handoff,
service/adapter, Flutter, native, sanitizer and history gates on one unchanged
source head. Obtain and inspect its content-addressed source artifact and seek
eligible independent review. Actual broker/platform/KMS identity, lost-device,
rotation and downstream revoke drills require their real redacted evidence.

No token, nonce, raw proof, private key or sensitive transcript should be attached
to qualification reports. Record only approved identifiers, test conditions,
source and deployment identities, timestamps, redacted failure codes and observed
outcomes. Unit-test signatures and fake broker verdicts remain source evidence,
not physical, provider or release authority.
