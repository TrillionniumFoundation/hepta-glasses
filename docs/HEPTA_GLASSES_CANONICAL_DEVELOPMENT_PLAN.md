
# Hepta Glasses canonical development plan

Revision: `2026-08-30-g1`

## 1. Mission

Convert the imported G1 companion demo into the edge portion of a distributed AI-native glasses
OS. Preserve the proven device integration, separate device mechanics from AI semantics, and make
all real effects deterministic, bounded, recoverable, auditable, and independent of model output.

## 2. Non-negotiable invariants

1. Model and Codex output are proposals, never final execution authority.
2. The mobile bundle contains no permanent model-provider or account credential.
3. Every mutation is journaled before effect and has an idempotency fingerprint.
4. Timeout or disconnect is indeterminate and requires reconciliation.
5. A decision lease is task/device/action-bound, short-lived, and normally single-use.
6. R4 capabilities are denied in the consumer profile.
7. Codex runs only in isolated read-only or workspace-write environments; full access is forbidden.
8. Source tests cannot be promoted into real-device, production, pilot, or release claims.

## 3. Work packages

### G0 — truth and governance

Deliver canonical docs, Gap Ledger, evidence registry, schemas, repository validator, CI,
CODEOWNERS, and PR template. Gate: source truth is explicit and no provider key enters the client.

### G1 — deterministic device substrate

Deliver device HAL, packet codec, dual-leg coordinator, capability/version negotiation contract,
G1 digital twin, golden vectors, disconnect/NACK/timeout injection, and per-leg receipts. Gate:
replay does not produce a duplicate logical write and partial success is explicit.

### G2 — edge runtime

Deliver hash-chained audit, durable task state, restart recovery, cancellation, deadlines,
idempotency, policy, decision leases, tool registry, journal-before-effect execution, and receipts.
Gate: corrupt journal or mismatched replay fails closed.

### G3 — identity and cloud control

Deliver production identity broker, device registry and attestation, short-lived model/realtime
tokens, remote revoke, rate limits, and account recovery. Gate requires deployed service and
credential-rotation evidence; source stubs do not close it.

### G4 — realtime interaction

Deliver streaming voice, VAD, partial transcript, barge-in, cancellation, network fallback,
privacy indicators, and measured latency/power/thermal SLOs. Gate requires physical Android/iOS
and G1 evidence.

### G5 — capability tool OS

Deliver production phone adapters, schema validation, prompt-injection defenses, approval UI,
reconciliation, and mutation receipts. Gate requires negative tests and real external-system
reconciliation evidence.

### G6 — Codex specialist lane

Deliver isolated worker allocation, Codex SDK or non-interactive launcher, one task/workspace/
identity, bounded execution, no device credentials, patch/test evidence, and maintainer review.
The source launcher in this package closes the repository-side safety substrate; deployed worker
identity and service credentials remain external.

### G7 — skills and memory

Deliver signed skill manifests, static and dynamic validation, user-approved memory, export and
delete, data-class restrictions, skill revoke, and retention evidence.

### G8 — pilot and release

Deliver device soak, fault matrix, privacy/security review, signed packages, SBOM/provenance,
staged rollout, kill switch, rollback drill, app-store/release approval, and pilot telemetry.

## 4. Acceptance evidence levels

- E0: design or static contract.
- E1: unit and negative tests.
- E2: digital twin, replay, and fault injection.
- E3: local integration.
- E4: exact-head CI.
- E5: physical phone plus G1 evidence.
- E6: pilot telemetry and operational drill.
- E7: independent security, privacy, or legal review.

A gate may require multiple levels. Lower evidence never substitutes for a required higher level.

## 5. Current package scope

The `ai-native-foundation-v1` package implements G0, the source portion of G1/G2, the mobile model
boundary, a development gateway, a read-only MCP surface, and the source Codex worker boundary.
It intentionally leaves physical-device, production identity/credential, firmware, privacy,
pilot, release, and repository-setting evidence blocked rather than relabeling it as complete.

## 6. Closeout rule

Every gap has one of these states:

- `CLOSED_SOURCE`: source acceptance criteria and tests exist.
- `CLOSED_VERIFIED`: required external/device evidence exists.
- `BLOCKED_EXTERNAL`: hardware, credentials, deployment, legal, or pilot input is absent.
- `BLOCKED_ADMIN_SETTING`: repository setting cannot be changed through source.
- `BLOCKED_UPSTREAM`: firmware/vendor access is absent.
- `OPEN`: actionable source work remains.

A package is source-closed when no `OPEN` item remains for its declared scope. It is not product-
closed while any required `BLOCKED_*` item remains.
