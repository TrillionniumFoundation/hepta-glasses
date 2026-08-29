# Hepta Glasses OS current state

Last updated: 2026-08-30
Canonical plan revision: `2026-08-30-g2`

## Repository identity

Original audited base:

- repository: `TrillionniumFoundation/hepta-glasses`
- base branch: `main`
- base commit: `32178d3cb4ae38c2ef91db05bde836838c274259`
- base tree: `f01ea2e305f5c1d54e8328c9028940e28519cb6e`
- upstream import: Even Realities `EvenDemoApp`, recorded in `UPSTREAM.md`

The active implementation is maintained on the isolated PR branch named in PR #1. Every qualification run must use the exact current PR head and tree, not the original base or an earlier package commit.

## Demonstrated source state

The source tree contains:

- Flutter Android/iOS companion application and native G1 BLE/LC3 integration;
- deterministic packet codec, transport HAL, dual-leg coordinator, digital twin, retry and degraded receipts;
- typed task, intent, tool, lease, display, event, memory, realtime, and release contracts;
- hash-chained audit, recoverable task lifecycle, cancellation, idempotency, policy, and Tool Gateway;
- provider-neutral mobile model gateway boundary with no permanent provider key in the bundle;
- device registration, short-lived token, key rotation, revocation, rate-limit, and attestation-verifier interfaces;
- one-time realtime bootstrap, bounded scope/profile admission, privacy indicator state, and generation-fenced barge-in;
- typed capability adapters with exact-argument leases, untrusted-content separation, journal-before-effect, and reconciliation;
- signed Skill registry, capability/data/domain consent, upgrade re-consent, revoke, purpose-bound Memory, TTL, export, and deletion;
- isolated Codex worker launcher and read-only development MCP surface;
- physical-device trace evaluator for Android/iOS latency, packet loss, temperature, battery, duplicate effects, and fault coverage;
- source SBOM/provenance generator, source/product release gates, and branch-protection apply/verify tooling;
- CI, negative tests, evidence templates, and external gate runbooks.

## Current evidence

The current PR head has E1/E2/E4 evidence for the first foundation package. The second source-closure package must receive a new exact-head GitHub Actions result before its source claims become current.

## Explicit non-claims

The repository still does not prove:

- physical stability on an actual G1 paired to production Android and iOS builds;
- G1 firmware, bootloader, secure-boot, signing, OTA, or rollback authority;
- production KMS/HSM, device attestation, account recovery, provider tenancy, OAuth consent, or revocation deployment;
- production realtime credentials or deployed isolated Codex worker infrastructure;
- independent privacy, security, legal, accessibility, or vendor approval;
- Android/iOS release signing, store approval, staged rollout, pilot telemetry, kill-switch exercise, or rollback drill;
- active `main` branch protection until GitHub's branch-protection endpoint verifies the canonical contract.

These are tracked as explicit external gates. They may not be converted to source claims.

## Execution authority

Model, realtime, Skill, MCP, and Codex outputs are untrusted proposals. A mutation must pass typed schema validation, policy, exact lease binding, deadline, untrusted-content separation, idempotency, journal preparation, deterministic adapter execution, and authoritative reconciliation. R4 remains denied.

## Release truth

`tools/build_source_evidence.py` generates exact-head SBOM, provenance, and source bundle. `tools/evaluate_release_gate.py --mode source` validates repository evidence. `--mode product` additionally requires protected `main`, physical Android/iOS reports, independent reviews, drills, signing evidence, and pilot data. There is no override flag.
