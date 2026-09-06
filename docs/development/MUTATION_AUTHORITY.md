# Authenticated mobile mutation authority

Status: HG-0087 identity source integration. The server-side durable lease issuer
and mobile HTTPS verifier are implemented. Production account login, KMS/HSM,
platform attestation, live token delivery and independent deployment evidence
remain external. Aggregate HG-0087 remains OPEN.

Implementation:

- `services/control_plane/mutation_authority.py`
- `lib/runtime/mutation_authority.dart`
- `lib/main.dart`
- `lib/runtime/policy_engine.dart`
- `lib/runtime/tool_gateway.dart`

Tests:

- `services/control_plane/test_mutation_authority.py`
- `test/runtime/mutation_authority_test.dart`
- `test/runtime/production_authority_boundary_test.dart`

## Responsibility and boundary

The server converts a currently verified account/device/session principal into a
short-lived, exact, single-use `DecisionLease`. It is the only production source
path that may cause the mobile module to construct a lease. The model, Flutter
widget, notification content, Skill, MCP client, device callback and client JSON
cannot assert authentication, user presence, biometric proof or policy identity.

The mobile `HttpMutationAuthorityProvider` requests authority over HTTPS, verifies
the complete response against the original immutable request and returns either
that exact authorization or an unauthenticated fail-closed result. Network,
clock, token-provider, parsing, content-type or binding failure never creates a
partial lease.

`MutationAuthorityRegistry.current` is injected through the one mobile
composition root. With no configured endpoint, invalid configuration or no
runtime access token, it resolves to fail-closed behavior. Product mode rejects a
compiled development mutation token. A production account component may install
a dynamic `MutationAccessTokenProvider` after current login/attestation; logout or
revoke must reset it. The registry stores a provider, not a bearer token.

## Request and response binding

The mobile request contains:

```text
task_id
action
canonical arguments
risk_tier
absolute UTC deadline
```

Arguments are recursively snapshotted before token lookup or hashing. Unsupported
or non-canonical JSON is rejected. The canonical argument digest therefore cannot
change if a caller later mutates its original map or nested list.

The identity verifier returns a server-owned principal:

```text
subject
device_id
session_id
audience = hepta-mutation-authority
scope includes mutation.authorize
policy_hash
user_present
biometric_verified
absolute principal expiry
```

The request cannot choose any of these fields. The server action registry fixes
the required risk tier. Unknown actions, tier drift, missing user presence for R2,
missing current biometric proof for R3 and all R4 operations fail before lease
creation.

The response must contain exactly the original task, action, risk and argument
digest together with subject, device, policy, presence proofs, one lease ID,
exactly one allowed action, issue/expiry times and `single_use=true`. Mobile
acceptance requires:

- exact task/action/risk/digest equality;
- syntactically bounded subject/device/lease IDs and SHA-256 policy hash;
- `authenticated=true`;
- R2/R3 presence requirements;
- issue time no more than 30 seconds in the apparent future;
- expiry after current time, after issue and no later than the original deadline;
- R4 denial;
- no unknown/missing response fields.

Only after all checks does the decoder construct a `DecisionLease`. The server
response is transport authority from the authenticated Hepta service, not proof
that a third-party provider or independent reviewer accepted the operation.

## Durable issuance, idempotency and revocation

`MutationLeaseAuthority` uses local SQLite WAL/FULL and `BEGIN IMMEDIATE`. Its
persisted policy digest binds audience, required scope, action/risk mapping,
maximum lease lifetime and record capacity. Reopening a database under a changed
policy fails with `mutation_authority_policy_migration_required`; no silent reset
or reinterpretation is supported.

The lease fingerprint binds:

```text
subject + device + session + task + action + risk
+ argument digest + request deadline + policy hash
```

An exact duplicate returns the existing unexpired issued lease without creating a
second row. The same fingerprint after expiry or revocation is replay-denied; the
caller must create a fresh task/deadline under current policy. The database stores
only argument and fingerprint digests, not the arguments or bearer token.

Subject, device and session revocations are monotonic tombstones. Revocation and
transition of matching issued leases to `revoked` commit in one transaction.
Repeated revoke is idempotent. The identity verifier must itself reject revoked
access tokens, and downstream services must consume durable identity revocation
events; the local lease tombstone is not a remote session-termination receipt.

## Failure semantics

| Failure | Result |
|---|---|
| Missing/invalid runtime token | Unauthenticated mobile authorization |
| Identity verifier unavailable | 401/deny; no lease row |
| Unknown action or risk mismatch | 403/deny; no lease row |
| Presence or biometric proof absent | 403/deny; no lease row |
| Request/principal/deadline expired | Deny; no new authority |
| Database capacity/storage failure | No success; effect remains unadmitted |
| HTTPS timeout or malformed response | Unauthenticated mobile authorization |
| Response binding/time drift | Response discarded; no lease |
| Subject/device/session revoke | Matching local leases revoked; future issue denied |

A failed authority request occurs before `ToolGateway` preparation or a physical
write. It is therefore safe for the user to retry only by submitting a new intent
through current identity and policy. It is not permission to reuse an old lease.

## Configuration, migration and operations

Server defaults: 60-second maximum lease, 100,000 retained lease rows, exact
built-in action/risk policy and audience `hepta-mutation-authority`. Limits are
configuration identity. Operate SQLite only on trusted local storage; do not use
a network filesystem or restore a snapshot that predates revocation.

Mobile configuration uses `HEPTA_MUTATION_AUTHORITY_URL`. HTTPS is mandatory,
except explicit non-product loopback. `HEPTA_MUTATION_AUTHORITY_DEV_TOKEN` is
allowed only in non-product development. Production must configure the URL and
install a runtime token provider from the authenticated account/attestation flow.
No permanent account or provider secret belongs in build defines.

Stop old binaries before changing policy/schema. Preserve lease and revocation
rows. A migration must retain every unexpired/revoked identity and cannot convert
unknown legacy rows into reusable authority. Rollback to a permanently local or
test lease provider is prohibited.

Monitor only safe metadata: request/lease IDs, action, risk, reason code, latency,
expiry bucket, subject/device opaque IDs and counts. Do not log arguments,
bearer tokens, prompts, notifications or biometric material.

## Verification and evidence ceiling

Run the server, mobile boundary and complete repository suites. Regressions cover
exact response binding, deep argument snapshot, token registry revoke, URL policy,
persistent idempotency, presence/biometric requirements, duplicate JSON, policy
migration, revocation and absence of plaintext arguments/tokens in SQLite.

Source tests do not establish a live account tenant, KMS/HSM signing, Android or
Apple attestation, secure runtime token storage, multi-instance replicated lease
state, real revoke propagation, physical effects, independent assurance or E5-E7
product evidence. Those remain named deployment and external gates.
