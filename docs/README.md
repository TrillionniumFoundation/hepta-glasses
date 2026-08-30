# Hepta Glasses documentation index

The canonical plan revision is `2026-08-30-g5`. Read documents in this order:

1. [`CURRENT_STATE.md`](CURRENT_STATE.md) — what is demonstrated now and what remains blocked.
2. [`HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`](HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md) — invariants, gates, evidence levels, and closure order.
3. [`GAP_LEDGER.yaml`](GAP_LEDGER.yaml) — machine-readable source and external gap truth.
4. [`EVIDENCE_INDEX.yaml`](EVIDENCE_INDEX.yaml) — allowed evidence locations and anti-substitution rules.
5. [`PRODUCT_BOUNDARY.md`](PRODUCT_BOUNDARY.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`THREAT_MODEL.md`](THREAT_MODEL.md), [`PRIVACY_MODEL.md`](PRIVACY_MODEL.md), and [`CAPABILITY_MODEL.md`](CAPABILITY_MODEL.md).

Development closure records:

- [`development/G3_G8_SOURCE_CLOSURE.md`](development/G3_G8_SOURCE_CLOSURE.md)
- [`development/G4_SOURCE_CLOSURE.md`](development/G4_SOURCE_CLOSURE.md)
- [`development/G5_AUDIT_CLOSURE.md`](development/G5_AUDIT_CLOSURE.md)

Operational runbooks:

- [`operations/DEVICE_QUALIFICATION_RUNBOOK.md`](operations/DEVICE_QUALIFICATION_RUNBOOK.md)
- [`operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md`](operations/PRODUCTION_CONTROL_PLANE_RUNBOOK.md)
- [`operations/REALTIME_AND_CAPABILITY_RUNBOOK.md`](operations/REALTIME_AND_CAPABILITY_RUNBOOK.md)
- [`operations/REPOSITORY_GOVERNANCE_RUNBOOK.md`](operations/REPOSITORY_GOVERNANCE_RUNBOOK.md)
- [`operations/CREDENTIAL_INCIDENT_RUNBOOK.md`](operations/CREDENTIAL_INCIDENT_RUNBOOK.md)
- [`operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md`](operations/PRIVACY_SECURITY_REVIEW_CHECKLIST.md)
- [`operations/RELEASE_AND_ROLLBACK_RUNBOOK.md`](operations/RELEASE_AND_ROLLBACK_RUNBOOK.md)

A document, source test, simulator, digital twin, or source CI artifact cannot close a gate that explicitly requires physical, deployed, administrative, vendor, independent, signing, pilot, or release evidence.
