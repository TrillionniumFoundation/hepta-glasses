# Reverse source ownership and current-state projection

Owner: architecture / repository-governance. This supplements the active blocker
execution plan without inventing a new G-number or rewriting frozen G8 evidence.

## Inputs and inheritance

`MODULE_COVERAGE.json` extends `G10_MODULES.json`, which extends G9 and then G8.
The loader flattens the inherited 25 IDs plus `agent-os-plugin`. Extensions add
previously omitted helper/build/test paths and module-local guides to existing
IDs; they do not falsely introduce a second owner for the same module.
Cycles, duplicate IDs, unknown extension targets, empty references and escaping,
linked or missing paths fail. Every module must still reference actual source,
documentation, tests, contracts and an explicit external gate.

## Reverse coverage algorithm

Read the checkout's tracked files with `git ls-files -z`; do not infer inventory
from the registry. Inspect all tracked files under lib, android, ios, services,
adapters, plugins, tools, contracts, schemas, .github, third_party and test.
An unknown source path fails even when every existing registry entry is valid.
The longest matching source prefix wins. Equally specific source owners require
an explicit registered override; tests referenced by multiple modules are shared.
Directory boundaries are exact, so `lib/a` cannot silently claim `lib/abc`.

The Android native dependency subtree has an explicit native-dependencies owner.
The shared external-evidence executable has an explicit G10 review-integrity
owner. New modules under unclaimed service roots cannot hide behind a global
`services/` fallback. Tests and platform build scaffolding have declared owners.
This initial source-root scope does not claim standalone web/desktop support,
asset provenance, arbitrary future top-level directories or semantic API coverage.
Changes to the scope must be reviewed rather than represented as product closure.

## CI and commands

```bash
python3 tools/validate_source_coverage.py
python3 -m unittest services.qualification.test_source_coverage
python3 tools/repository_snapshot.py
```

The actual-checkout coverage assertion runs through the existing service-test
discovery in `repository-contracts`. It is not an optional manual checklist and
adds no new workflow identity. The seven canonical contexts remain unchanged.
Fixture tests prove orphan detection using a real miniature Git index, sibling
prefix separation, ambiguity, explicit overrides, shared tests, inheritance cycles,
escaping references, missing references and symbolic links.

## Current state without self-attestation

`repository_snapshot.py` refuses tracked changes, reads commit/tree directly from
Git, recomputes flattened module/source counts and combines G8/G9/G10/remediation
gap rows. Duplicate IDs fail. It outputs status counts and the actual OPEN IDs.
It deliberately emits `ci_status=not_observed`, independent review not observed,
and release authorization false. This is not a CI receipt and does not fabricate
an approval from local environment variables or hand-written SHA values.

Collect GitHub jobs, artifact digests and eligible review records separately for
the reported exact head. Changes after collection require a fresh qualification.
Store generated observations outside source or as CI artifacts; do not continually
push updated head-marker files and invalidate the evidence they describe.

`CURRENT_STATE.md` remains the historical G8 narrative and its 22-module count is
not the flattened current total. The README and this projection identify the
active supplement. The historical zero-open counts must never conceal OPEN
production-code, semantic-documentation or main-adoption work in
`REMEDIATION_GAP_LEDGER.json`.

## Claim ceiling and remaining documentation work

This tool proves path ownership and reference existence, not that every function
is documented or tested. It does not infer coverage from filename, assertion
count, a 700-character paragraph or a file named widget_test. HG-0088 remains OPEN
until every module's interfaces, state/error/configuration/migration/operations
matrix and cross-language conformance tests are reviewed. The plugin and the
changed reference runtime have new concrete local guides; the other modules
still inherit their existing central guides and ADRs.

Physical, provider, signing, legal/privacy/accessibility assurance, vendor and
repository-administrator authority remain outside this source projection.
