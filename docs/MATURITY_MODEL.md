# Hepta Glasses maturity model

Status: canonical maturity vocabulary for source, integration, hardware, pilot, and release claims.

The project previously used terms such as “open”, “closed”, “source closed”, and “production” across different documents. Those terms remain valid where contracts already depend on them, but they do not express the full product lifecycle. This model prevents a repository implementation from being mistaken for a deployed or released product.

## Ordered maturity stages

### 1. `design_draft`

Responsibilities, boundaries, data classes, interfaces, risks, and acceptance criteria are documented. Source may be absent or incomplete. Design review is not implementation evidence.

### 2. `source_implemented`

The scoped behavior exists in source with deterministic positive and negative tests. Referenced contracts and module documentation are synchronized. This corresponds to `CLOSED_SOURCE` where the gap ledger uses that term.

It does not establish exact-head CI, deployment, physical compatibility, real provider behavior, signing, or release.

### 3. `ci_qualified`

One unchanged source head completes every required non-empty CI job, produces a content-addressed artifact bound to the exact commit and tree, passes independent artifact verification, and receives an eligible exact-head review.

A later source or base change returns the successor to `source_implemented` until it is independently requalified. CI qualification is at most E4.

### 4. `integration_qualified`

The exact candidate is deployed in a controlled integration environment using real service identities, durable stores, KMS/secret references, provider tenants, OAuth registrations, revocation paths, telemetry, backup/recovery, and failure drills.

Mocks, loopback gateways, test-only authority, or local environment variables do not satisfy this stage.

### 5. `physical_device_qualified`

Signed mobile binaries and declared physical handset/G1 hardware/firmware matrices pass protocol, latency, reliability, RF-loss, power, thermal, privacy, cancellation, recovery, and soak scenarios with `synthetic=false` evidence.

Simulators, emulators, digital twins, packet replay, and unsigned screenshots do not satisfy this stage.

### 6. `pilot_qualified`

An approved pilot uses the exact signed candidate and production-like infrastructure. Success thresholds, privacy notice, support, incident handling, kill switch, rollback, accessibility, safety, reliability, latency, crash, power, and thermal results are measured and accepted by named authorities.

A pilot plan without execution or synthetic telemetry does not satisfy this stage.

### 7. `released`

The unchanged candidate has:

- complete protected-main governance and exact-main evidence;
- accepted external authority evidence under an out-of-band trust registry;
- production identities, providers, OAuth, KMS/HSM, and attestation;
- signed binaries, binary SBOM, provenance, and attestations;
- physical and pilot qualification;
- independent security, privacy, legal, accessibility, and safety acceptance;
- staged rollout and rollback authority;
- applicable store or distribution approval;
- a product release gate result that passes without override.

## Independent maturity axes

A module or release can have different maturity on separate axes:

| Axis | Examples |
|---|---|
| Source | design, implementation, deterministic tests |
| Governance | branch policy, eligible review, protected adoption |
| Service integration | tenant, identity, KMS, OAuth, receipts, recovery |
| Hardware | signed builds, physical G1 matrix, power, thermal, soak |
| Assurance | security, privacy, legal, accessibility, safety |
| Distribution | signing, pilot, rollout, rollback, store approval |

The overall product maturity is bounded by the least mature required axis. A high score in source governance cannot compensate for absent physical evidence; a successful pilot cannot compensate for an unreviewed source change.

## Promotion and regression rules

Promotion requires machine-verifiable evidence for the target stage and its exact candidate identity. Prose, issue checkboxes, screenshots, status labels, and administrator assertions cannot promote maturity.

The following events regress affected axes until requalification:

- source, dependency, workflow, contract, or base movement;
- provider tenant, key, OAuth registration, policy, or deployment change;
- binary, signer, entitlement, application ID, firmware, or hardware-matrix change;
- unresolved high/critical assurance finding;
- trust-registry, reviewer set, acceptance context, or release-policy change;
- failed rollback, revoke, recovery, kill-switch, or store review.

## Relationship to evidence levels

- E0–E3 can support `design_draft` and `source_implemented`.
- E4 is required for `ci_qualified`.
- E5 is required for controlled service and physical qualification.
- E6 is required for independent assurance and pilot acceptance.
- E7 is required for final signed release and distribution authority.

Evidence levels never auto-promote a scope outside the identities, claims, time, environment, and artifacts they bind.
