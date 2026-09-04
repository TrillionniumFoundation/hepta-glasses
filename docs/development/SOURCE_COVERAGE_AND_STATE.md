# Reverse source ownership and current-state projection

Owner: architecture / repository-governance. This document supplements the active
blocker execution plan without inventing a new G-number or rewriting frozen G8
source evidence.

## Inputs and inheritance

`MODULE_COVERAGE.json` extends `G10_MODULES.json`, which extends G9 and then G8.
The loader flattens the inherited 25 IDs plus `agent-os-plugin`. Extensions add
previously omitted helper, build, test, and module-local documentation paths to
existing IDs. Cycles, duplicate IDs, unknown extension targets, empty or escaping
references, symbolic links, and missing paths fail closed. Every module retains
source, documentation, tests, contracts, lifecycle, owner, and external gates.

## Reverse coverage algorithm

The validator reads the checkout's tracked files with `git ls-files -z`; it does
not infer inventory from the registry. It inspects tracked files below `lib`,
`android`, `ios`, `services`, `adapters`, `plugins`, `tools`, `contracts`,
`schemas`, `.github`, `third_party`, and `test`. An unknown source path fails even
when every declared registry entry is internally valid.

The longest matching source prefix wins. Equally specific owners require an
explicit override; referenced tests may be shared. Directory boundaries are
exact, so `lib/a` cannot claim `lib/abc`. Android native dependencies and the
shared external-evidence entrypoint have explicit owners. No broad `services/`
fallback can hide a new module. This source-root scope does not claim standalone
web/desktop support, asset provenance, or semantic coverage of arbitrary future
top-level directories.

## Current-state projection

`repository_snapshot.py` refuses tracked changes, reads commit/tree directly from
Git, recomputes flattened module/source counts, and combines G8/G9/G10/remediation
gaps. Duplicate IDs fail. It deliberately reports CI and independent review as
not observed locally and release authorization as false. Generated observations
belong in CI artifacts or external custody, not in a self-attesting source file.

`CURRENT_STATE.md` remains the historical G8 narrative and its 22-module count is
not the flattened current total. README and this projection identify the active
26-module supplement. Historical zero-open counts must not conceal HG-0087,
HG-0089, or authority-owned external rows.

## Documentation and semantic handoff

HG-0088 is source-closed by the machine handoff registry, its 26 primary detailed
documents, exact module identity/order checks, required platform/evidence fields,
path validation, placeholder rejection, and cross-language canonical-JSON
vectors. That closure establishes a reviewable source handoff floor, not permanent
semantic completeness.

A module owner must still update interfaces, state/error/configuration/migration,
operations, tests, and evidence limits whenever implementation changes. The
validator cannot infer the truth of prose from file length alone. Reviewers must
reopen the applicable gap when an exported API, state transition, error meaning,
configuration key, migration, or operational invariant changes without matching
documentation and tests.

## Newly closed source defects

HG-0090 removes self-attested product release authority. Product mode now accepts
only a complete G10 validation result created under an out-of-band trust-registry
pin and bound to the exact source commit/tree.

HG-0091 preserves physical-trace acquisition order, rejects timestamp and capture-
sequence drift, groups packet loss by side/generation, enforces production sample
floors, and requires injected faults to be observed and recovered. These are
source controls only; they do not create physical evidence.

Physical devices, providers, signing authorities, independent assurance, vendor
rights, stores, and repository-administrator settings remain outside this source
projection.
