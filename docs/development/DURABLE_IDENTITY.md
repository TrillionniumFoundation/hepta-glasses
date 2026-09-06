# Durable identity and authenticated signing composition

Status: HG-0087 identity slice, partial implementation candidate. This source
increment adds real persistent repositories and an executable authenticated
broker client. It does not complete the aggregate production gap. The active
plan is `2026-09-03_BLOCKER_EXECUTION_PLAN.md`; machine progress is recorded in
`docs/HG0087_IMPLEMENTATION_STATUS.json`. No production tenant or key is created.

## Responsibility, composition and API

`services/control_plane/durable_identity.py` implements durable subject, device,
challenge, session, token, revocation, event and policy repositories. It reuses
`DurableDatabase`: SQLite WAL/FULL with write transactions before admission.
`services/control_plane/identity_authority.py` composes platform-proof verification,
remote signing, local Ed25519 verification and final durable authority admission.
The existing in-memory `identity.py` is not changed or relabeled as production.

```text
Authenticated account service and reviewed policy
 -> DurableIdentityStore.admit_subject / challenge
 -> DurableIdentityAuthority.enroll
 -> configured HTTPS platform verifier
 -> exact verdict binding and atomic challenge consumption
 -> durable device and session
 -> prepared token metadata
 -> configured HTTPS KMS/HSM signing broker
 -> pinned public-key Ed25519 verification
 -> final subject/device/session/token recheck
 -> HGAT2 token returned
```

Only the authenticated server calls this composition. `admit_subject`,
`create_session`, `accept_attestation` and `commit_token` are trusted repository
APIs, not public endpoints. A client-supplied `verified=true` or receipt string
must never be translated directly into a store call. `accept_attestation` does
not itself authenticate a proof; the production entrypoint is `enroll` with a
trusted broker. Account authentication and user enrollment authorization remain
integration prerequisites, not facts manufactured by this library.

| API | Caller supplies | Semantics |
|---|---|---|
| `admit_subject` | Subject derived from authenticated account identity | Idempotent active admission; terminal revoked subjects cannot return |
| `challenge` | Subject, device, platform, app and signer identity | Random single-use nonce; stored only by digest with expiry |
| `enroll` | Issued challenge and bounded platform proof | Exact broker verdict and freshness checks, then atomic enrollment |
| `create_session` | Bound subject/device, audience, allowed scopes and TTL | Persistent session; scopes cannot exceed protected allowlist |
| `issue` | Existing session, narrowed scopes and TTL | Prepare, sign remotely, verify actual signature, recheck authority, activate |
| `verify` | HGAT2 token plus expected audience and required scopes | Strict format/crypto checks and a consistent current durable authorization read |
| `revoke` | Kind and ID chosen by authorized service | Terminal tombstone, dependent-record invalidation and monotonic event |
| `events_after` | Consumer cursor and bounded limit | Durable ordered fanout feed; caller owns durable cursor/acknowledgement |
| `pending_tokens` | Bounded limit | Interrupted signing records; never automatically promoted |

The contract is `contracts/identity-authority-v1.json`. New tokens use `typ=HGAT2`,
`alg=EdDSA`, Ed25519, exact header/claim fields and canonical unpadded base64url.
There is no HS256/unsigned/legacy fallback. Do not advertise general JWT/OIDC
interoperability without a separate compatibility qualification.

## Immutable bindings and state

A device ID has one subject, platform, application ID and signer digest. An
existing active device with a different proof requires the separate recovery
workflow; ordinary registration never silently replaces its authority. A revoked
device cannot be revived by registration or by a late verifier response.

A session binds subject/device/audience/scopes and lifetime. Token scopes can only
narrow, and token expiry cannot exceed session expiry or the configured signing
key lifetime. Token IDs are random, globally unique database keys; a collision
fails the transaction rather than replacing an existing token.

```text
token: preparing -> active
           |
           +-> indeterminate
any applicable subject/device/session/token revocation -> revoked
```

Only `preparing` can enter `active`. The broker response must bind key ID,
algorithm, request ID and signing-input digest; its signature is then verified
against an externally provisioned public key. A final database transaction checks
all current authority and the exact persisted claims digest. A revoke during
signing, even through another database connection, prevents activation.

The process-local lock protects a connection, not distributed authority. SQLite
`BEGIN IMMEDIATE` serializes independent local connections/processes. This is not
a multi-region service or a supported network-filesystem deployment.

## Crypto and network boundary

`PinnedEd25519Verifier` snapshots a bounded immutable public-key map. Duplicate
public keys under aliases, wrong DER shape, expired/revoked/future keys, invalid
signatures, malformed canonical encoding, duplicate JSON keys and nonfinite
numbers fail closed. Public Ed25519 SPKI is exactly 44 bytes with the expected
algorithm identifier. No provider-returned public key is trusted automatically.

Verification reuses the repository's root-owned absolute `/usr/bin/openssl`
policy and minimal subprocess environment. Token components are passed through
sealed anonymous Linux memory descriptors, not temporary disk files. The
trusted kernel/process and system OpenSSL remain dependencies. Linux memfd,
seals and `/proc/self/fd` are required; unsupported hosts have no disk fallback.
This path never receives a production private signing key.

`HttpsAuthorityBroker` implements the versioned broker protocol, not the vendor
backends behind it. The operator configures an exact HTTPS host, with no URL
credentials, query, fragment, non-443 port or custom path. There is no automatic
redirect, environment proxy, caller TLS context or model-selected endpoint.
System certificate and hostname verification stay enabled. Workload credentials
come from an injected server-side callback and must be bounded ASCII without
control/whitespace characters; they are never stored or included in errors.

The client posts to `/v1/attestations/verify` and `/v1/signatures/ed25519`. Request
and response sizes are bounded, response type/length are checked, and ambiguous
or unavailable responses do not grant authority. The finite worker pool retains
a timed-out operation's permit until it exits. Socket timeouts and worker limits
bound resource use but cannot kill arbitrary Python code; deployment isolation
and provider-side deadlines still matter.

## Configuration, policy and migration

Constructor settings include issuer, protected allowed scopes, maximum rows per
admission table, maximum token TTL, trusted service clock, protected broker host,
workload identity callback and immutable public verification keys. Defaults are
100,000 rows per admission table, 900-second maximum token TTL, 120-second
challenge TTL, 8-second broker calls and 4 broker workers. Maximum challenge TTL
is 300 seconds, session TTL 86,400 seconds, scopes 32 and identifiers 256 chars.
These are defensive limits, not load-tested production capacities.

Component schema version is 1. It creates namespaced tables without importing or
silently converting an old reference registry. Unknown versions fail closed.
Issuer, allowed scopes and maximum token TTL are persisted as policy identity;
changing them requires an explicit reviewed migration. A different connection
cannot silently reinterpret the same database with another issuer or policy.

No raw nonce, bearer token, attestation proof or private key is stored in SQLite.
Subject/device IDs, claim digests, signing receipts, scopes and revocation events
are sensitive metadata; protect and encrypt the storage volume operationally.
The database itself is not encrypted by this increment. Memory encryption is a
separate HG-0087 slice and is not implied by identity persistence.

## Failure and recovery contract

| Failure window | Durable outcome | Recovery |
|---|---|---|
| Enrollment verifier unavailable | No device admission; unconsumed challenge may expire | Obtain a new bounded challenge/proof as required by provider semantics |
| Proof returns after device/subject revoke | Rejected enrollment | Never undo tombstone |
| Crash after token preparation | `preparing`, no active token | Revoke old ID, then issue fresh under current session authority |
| Signing timeout or invalid signature | `indeterminate`, no returned active token | Investigate broker; do not promote or replay old authority |
| Signature valid, final storage failure | No token returned; original transaction remains non-active | Repair storage, revoke unresolved ID, issue a fresh token |
| Revoke after successful issue | Token fails every subsequent durable verification | Consume fanout event to terminate long-lived downstream connections |
| Admission capacity reached | New admission rejected | Revocation remains permitted; reviewed archival/migration required |

Revocation events are idempotent and monotonically numbered. Consumers must apply
revokes idempotently and persist their own cursor only after handling. This
increment does not implement or prove every downstream consumer. A request-time
token check is not a perpetual lease and does not replace final edge policy,
user confirmation, single-use decision leases or device generation checks.

## Tests, operations and remaining work

The new tests exercise persistence/reopen, actual process exit, proof binding,
concurrent nonce consumption, subject/device collisions, scope/TTL narrowing,
all four revocation dimensions during signing, exact claims, key validity,
actual Ed25519 signatures, sealed memory, canonical parsing, transport validation,
worker capacity and recovery. Platform proof verdicts and network calls use
explicit test doubles; cryptographic signature verification uses actual OpenSSL.

```bash
python3 -m unittest services.control_plane.test_durable_identity services.control_plane.test_identity_authority -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
```

Runbook: `docs/operations/IDENTITY_AUTHORITY_RUNBOOK.md`. Full repository and
platform CI must still execute on the published exact head. Real KMS/HSM,
Android/Apple verification, step-up lost-device replacement, authenticated account
service, mobile identity-backed mutation authority and downstream revoke
consumers remain OPEN until implemented/integrated and separately qualified.
