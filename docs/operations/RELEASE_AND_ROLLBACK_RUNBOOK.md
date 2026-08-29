# Release, kill-switch, and rollback runbook

## Source release evidence

The `source-evidence` CI job runs after repository, Flutter, and boundary jobs. It creates:

- `source-sbom.spdx.json`;
- `source-provenance.json`;
- `source-release-bundle.json`;
- `source-evidence-summary.json`.

## Product release gate

Populate `evidence/templates/product-release-bundle.template.json`, then run:

```bash
python3 tools/evaluate_release_gate.py \
  --bundle evidence/release/<release>.json \
  --mode product
```

There is no override mode.

## Kill-switch drill

Independently disable model sessions, realtime bootstrap, mutating capabilities, a Skill, a device, and a release cohort. Confirm read-only status and user-visible recovery remain available where safe.

## Rollback drill

- Freeze new mutations.
- Reconcile in-flight effects.
- Roll mobile/control-plane configuration to the last approved release.
- Verify schema and journal compatibility.
- Confirm revoked sessions and devices remain revoked.
- Re-run smoke and duplicate-effect checks.

## Staged rollout

Internal operators → 5–10 user cohort → 20–50 user pilot → broader cohort. Promotion requires crash-free threshold, zero duplicate effects, SLO pass, no unresolved high-severity finding, and a successful rollback rehearsal.
