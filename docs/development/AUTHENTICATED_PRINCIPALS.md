# Unified authenticated principals for model, speech and mutations

Status: HG-0087 identity source integration. The repository now provides one
framework-neutral adapter that projects a currently verified account/device/
session decision into the three narrow principals consumed by model, speech and
mutation ingress. Live account tenancy, KMS/HSM, Android/Apple attestation,
persisted active-pair service and witnessed deployment remain external.

Implementation:

- `services/control_plane/authenticated_principals.py`
- `services/model_gateway/model_ingress.py`
- `services/model_gateway/speech_ingress.py`
- `services/control_plane/mutation_authority.py`

Tests:

- `services/control_plane/test_authenticated_principals.py`
- `services/model_gateway/test_model_ingress.py`
- `services/model_gateway/test_speech_ingress.py`
- `services/control_plane/test_mutation_authority.py`

## One access interpretation

The deployment supplies two independently protected services:

1. `DurableAccessAuthority.verify_access` validates the bearer against current
   subject, registered phone/device, session, audience, scope, expiry, policy,
   user-presence, biometric and revocation state.
2. `ActivePairAuthority.resolve_pair` returns the active G1 pair bound to that
   exact subject, registered device and session, with a bounded expiry.

The adapter recognizes only these exact audience/scope pairs:

| Ingress | Audience | Required scope | Pair lookup |
|---|---|---|---|
| Model | `hepta-model-gateway` | `model.generate` | no |
| Speech | `hepta-speech-bootstrap` | `speech.bootstrap` | yes |
| Mutation | `hepta-mutation-authority` | `mutation.authorize` | yes |

Crossing an audience with another scope fails before access verification. The
client request cannot add a scope, choose a subject/device/session, assert user
presence, supply biometric proof, select a policy hash or name an active pair.

## Access and pair validation

`VerifiedAccessClaims` must contain bounded canonical identifiers, a unique
scope tuple, a SHA-256 policy hash, booleans for current user-presence/biometric
facts and an absolute expiry after trusted host time. Provider exceptions and
malformed claims become `identity_access_denied` without upstream text.

Model access does not need a physical pair and becomes `ModelPrincipal` with the
same subject/session/audience/scopes and consent expiry.

Speech and device mutations require a second exact pair read. The pair record
must match access subject, registered phone/device and session; be active; expire
after a fresh post-lookup clock sample; and not outlive access. Pair resolver
exceptions, malformed records, mismatches and expiry become
`identity_pair_denied`. Clock rollback between access and pair reads fails
closed.

The effective speech/mutation expiry is:

```text
min(access expiry, active-pair expiry)
```

Speech receives this expiry explicitly, so the ingress rejects and revokes a
provider ticket that would outlive it. Mutation authority targets the exact pair
identity as its `device_id`; its server lease can therefore match the mobile
runtime's physical-effect device identity instead of the registered phone ID.

## Failure and recovery

| Failure | Result |
|---|---|
| Unknown audience/scope pair | `identity_audience_scope_invalid` |
| Token authority exception or malformed access claims | `identity_access_denied` |
| Access expired or wrong scope/audience | `identity_access_denied` |
| Pair resolver exception | `identity_pair_denied` |
| Pair subject/device/session mismatch | `identity_pair_denied` |
| Pair inactive, expired or outliving access | `identity_pair_denied` |
| Clock invalid or rolled back | `identity_clock_invalid` |

No fallback principal is generated. A model, speech or mutation ingress maps
these bounded failures to its own unauthenticated/denied response and performs no
provider or physical effect. Recovery requires a fresh access verification and,
where applicable, a fresh active-pair binding; cached principals are not
perpetual authority.

## Deployment contract

The access authority must be backed by the durable identity/session/token/
revocation implementation and real KMS/HSM/platform-attestation services. The
pair authority must be an authenticated server-side record synchronized with the
mobile G1 connection identity; it must not trust a pair string from the request
body. Both services require durable revocation propagation, trusted time,
operator-owned storage, retention and recovery procedures.

Long-lived streams and mobile token registries must consume revoke events. A
request-time principal check cannot retract bytes already delivered or prove
remote provider termination. Speech provider revoke/readback, model remote
cancellation and physical BLE reconciliation keep their separate authority.

## Evidence ceiling

Deterministic source tests prove type/shape checks, exact audience/scope mapping,
pair equality, expiry narrowing, lookup-time freshness, clock rollback and
exception sanitization. They do not prove a live account tenant, real attestation,
KMS/HSM key custody, active-pair service deployment, cross-service revoke latency,
physical G1 identity, provider tenancy or independent acceptance.
