# Architecture

```text
Even G1 left/right legs
  microphone / touch / display / battery / firmware protocol
                  |
                  | bounded BLE frames, ACK/timeout, sequence and trace
                  v
Device HAL + Packet Codec + DualLegCoordinator
                  |
                  | versioned event/task/tool/display contracts
                  v
Mobile Edge Execution Authority
  Event Bus       Task Engine       Audit Journal
  Policy Engine   Decision Leases   Tool Gateway
  Context Filter  Display Composer  Recovery/Reconciliation
        |                                  |
        | opaque capability request        | short-lived authenticated API
        v                                  v
Phone Capability Adapters             Cloud Control Plane
calendar/reminder/notification        Device Registry / Attestation
location/storage/accessibility        Key Ring / Token / Revocation
opaque OAuth credential handles       Rate Limits / Realtime Broker
        |                                  |
        | authoritative receipt            | one-time bootstrap
        v                                  v
External systems                    Provider Adapter / Realtime session
                                           |
                                           v
                                  Isolated Codex workers
                                  one task/workspace/identity
```

## Authority boundaries

- G1 firmware is a device endpoint, not an Agent authority.
- Flutter UI submits intent and displays state; it does not decide authorization.
- Mobile Edge Runtime is final authority for BLE and local device effects.
- Cloud Control Plane is authority for identity, token, revoke, provider routing, and long-running task allocation.
- Capability adapters hold opaque server-side OAuth handles; the model never receives refresh tokens.
- Codex produces plans, patches, test results, and Skill candidates; it cannot directly mutate a G1, release firmware, or merge its own PR.

## Fast interaction lane

```text
wake/gesture
  -> audio ingress and privacy indicator
  -> one-time realtime bootstrap
  -> provider session established server-side
  -> partial transcript / model proposal
  -> bounded tool proposal
  -> policy and lease
  -> deterministic capability or display execution
  -> receipt
```

Barge-in increments the session generation. Events from an older generation are stale and rejected, preventing a cancelled response from committing later output.

## Deliberative Codex lane

```text
Durable task
  -> isolated worker allocation
  -> exact repository/workspace binding
  -> read-only or workspace-write sandbox
  -> bounded network/runtime/output
  -> patch and tests
  -> source validation
  -> independent maintainer review
  -> separate release authority
```

## Skill and memory lane

A Skill is unavailable until publisher, signature, package digest, capability set, data classes, domains, timeout, and risk pass admission. New capabilities or data classes on upgrade require re-consent. Memory is bound to subject and purpose, excludes secret/raw-audio/credential classes, has TTL, and supports export and deletion.

## Failure semantics

- Timeout is indeterminate, not proof of failure.
- Same idempotency key and fingerprint returns the existing receipt.
- Same key with a different fingerprint fails closed.
- One-leg success is degraded and requires reconciliation.
- Invalid journal linkage blocks recovery.
- Expired, consumed, mismatched, or stale-generation authority is rejected.
- Untrusted content cannot authorize a mutation.
- Revoked subject, device, session, token, or Skill loses authority immediately.

## Evidence architecture

Physical device processes emit JSONL trace events. The qualification evaluator produces a content-addressed report. CI generates a source SBOM and provenance. The product release gate requires exact source, governance, physical-device, review, drill, signing, and pilot evidence in one machine-readable bundle.
