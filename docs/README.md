
# Hepta Glasses documentation index

## Canonical current truth

1. `HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md` — normative implementation sequence and gates.
2. `CURRENT_STATE.md` — exact demonstrated source state and explicit non-claims.
3. `PRODUCT_BOUNDARY.md` — glasses, edge, cloud, model, Codex, and execution-authority boundaries.
4. `ARCHITECTURE.md` — component and data-flow architecture.
5. `CAPABILITY_MODEL.md` — risk tiers, decision leases, and mutation admission.
6. `THREAT_MODEL.md` — trust boundaries, threats, and mitigations.
7. `PRIVACY_MODEL.md` — data classes, retention defaults, and user controls.
8. `GAP_LEDGER.yaml` — machine-readable gaps and evidence ownership.
9. `EVIDENCE_INDEX.yaml` — source and future device evidence registry.

A later plan or ADR must state what it supersedes and update `CURRENT_STATE.md`, the Gap Ledger,
and the relevant machine-readable contract in the same change.

## Architecture decisions

- `adr/ADR-0001-distributed-os-boundary.md`
- `adr/ADR-0002-codex-authority-boundary.md`
- `adr/ADR-0003-edge-runtime-language.md`

## Evidence

Source evidence is retained under `evidence/`. Source evidence proves only the exact source or CI
state it names; it is not evidence of a real G1 device effect, production credentials, signed
firmware, privacy compliance, a pilot, or a public release.
