# P0–P3 implementation and acceptance work package

Status: source implementation candidate; no aggregate completion or release approval.
Accountable coordination: repository-admin and release. Required co-reviewers:
mobile, runtime-security, device-runtime, ai-platform, cloud-security and privacy.

This package begins implementation across the four review priorities and records
the remaining acceptance work. It does not create a second module registry, change the Gap Ledger to closed, or promote
an author assessment into independent module acceptance. The active inventory
remains `docs/modules/modules.json`; documentation acceptance remains governed
by `MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md`.

## Candidate custody

The starting source is commit `5d502128286ed3523fcb0a7b92573df69f99f100`,
tree `057c9ca71ee8011d2c42cf9e6f83e40f6982c80c`, the inspected head of PR #125.
This work belongs on a separate successor branch, not directly on `main`.
Obtain the successor's live commit/tree from Git, not a copied status sentence.
Every successor invalidates predecessor CI, source artifacts and exact-head
approval. This document does not assert that the seven jobs have passed.

The inspected predecessor run `34561625142` failed in Flutter dependency
retrieval and the iOS native-test lane; source evidence was skipped. A dependency
authorization error is not proof of an SDK incompatibility. An iOS job timeout
is not proof that a local-network permission warning caused the failure. Use
fresh unchanged-head logs and the selected source inventory to locate the cause.

## P0 — trusted development baseline

### Source changes in this increment

`tools/ios_ci.py` now requires explicit integer values for all four top-level
xcresult counts. A missing passing count is not inferred from a zero failing
count. Any skipped test, zero execution, inconsistent arithmetic, or disagreement
with the current source inventory rejects qualification. Additional xcresult
metadata is allowed, but nested count fields cannot replace the top-level ones.
The canonical workflow uses `validate-result --root .` for the one-target,
one-Debug-configuration RunnerTests profile. A future parameterized or multiple
configuration test profile must revise the inventory contract explicitly.

The prior validator was reproduced locally accepting both of these invalid
summaries: all seven tests skipped, and only total/failure counts present. The
regression suite preserves those counterexamples, invalid scalar types, nested
spoofing, partial execution, malformed inventories and bounded JSON parsing.

All three mobile dependency steps use `flutter pub get --enforce-lockfile`.
An authorization, integrity or resolution failure still fails; there is no token
substitution, package-host fallback, cache purge, automatic upgrade or retry-until-
green behavior. Flutter analysis treats warnings and informational diagnostics
as failures. The iOS lane retains RunnerTests and adds individual test deadlines
(120 seconds default, 180 seconds maximum) and a 300-second simulator readiness
wait. A deadline is a failure, never a reason to omit the test. The seven job
names, exact-SHA checkout, read-only permissions, history scan, native sanitizers
and six prerequisites of source-evidence are retained.

### P0 acceptance still required

Run all seven jobs on one unchanged successor, inspect the exact-head source
artifact and obtain an eligible independent approval. Investigate any remaining
authorization failure without printing environment variables, credentials or
verbose authenticated HTTP exchanges. Investigate the actual timed-out native
test with its source selector and xcresult; do not remove the test or assert an
unobserved root cause. Local Python helper tests are not Flutter or XCTest runs.

## P1 — current specifications and the product path

The shared guide now points to the one active registry and distinguishes legacy
reference profiles from the current durable model, identity, realtime,
capability, signed-Skills and Memory specifications. Its 22 module sections have
explicit stable anchors. `services/qualification/module_document_links.py` is
called by the canonical module validator for primary fragment references. It
rejects missing, duplicated, example-only, comment-only and non-heading-bound
targets. This is navigation consistency, not proof of all eleven engineering
dimensions. It does not claim to validate every historical secondary link.

The G1 source already contains the typed schema-v3 command/wire/effect/readback
matrix in `G1_PROTOCOL_COMMAND_MATRIX.md`. The older depth-audit request to add a
per-command byte/ACK/retry table must be read in light of that implementation;
remaining work is current-state consolidation, review, firmware confirmation and
physical evidence, not re-creating an already existing matrix.

### Product path to qualify

The acceptance path is: authenticated subject and session; current paired device
and connection generation; explicit user intent; policy and single-use lease;
durable preparation; current-generation microphone/final transcript; authenticated
Hepta gateway; final live authority checks; admitted display effect on required
legs; typed receipt; user-visible completion or uncertainty; bounded recovery.

These are acceptance stages, not a replacement for existing wire-state names.
No new authenticated product ingress, platform verifier, KMS, ASR tenant or mobile
lease issuer is installed by the source changes in this work package. A trusted
Python dataclass and a client-provided consent field are not identity evidence.
The durable model library, development HTTP endpoint and mobile gateway boundary
must be composed deliberately; their separate existence is not integration.

| Boundary | Required owner behavior | Failure and recovery requirement |
|---|---|---|
| App startup and relaunch | mobile composes durable journal and current authority once | Storage/key/identity failure disables mutations; a relaunch does not restore opt-in history or extend authority |
| Identity to lease | cloud-security authenticates subject/device/session; runtime-security binds exact arguments | Revocation/expiry before dispatch denies; no unsigned or client-asserted proof |
| Microphone to ASR | mobile-ai accepts only current-generation audio and actual finality | Permission denial, interruption, timeout and unsupported platform are distinct; partial text never becomes final by timeout |
| Model request | ai-platform revalidates after credential/TLS waiting and before content send | No automatic replay of an uncertain foreground generation; local cancellation is not remote termination |
| Model answer to device | runtime treats output as untrusted data and reacquires effect authority | No model text can supply a lease, user presence or a tool confirmation |
| Dual-leg display | device-runtime preserves per-leg effect certainty | One-leg success is not pair completion; a missing ACK is not a safe full retry |
| Process death and recovery | owning component retains prepared records, generations and denials | Recover by authoritative readback under the applicable scope; missing payload is not permission to resend |

User-visible states must distinguish not executed, confirmed, pending/unknown,
partially applied and revoked locally. Unknown effects expose a bounded recovery
or support path rather than a generic retry button. Permission-denied screens
need a direct settings/retry action that rechecks authority; accessibility labels
must announce uncertainty and the affected side without reading private content
into diagnostics. Locale/device support must be explicit. Android's ticket-bound PCM-to-ASR source path remains fail closed without its
live authenticated bootstrap and qualified speech tenant; it must not be
substituted with a fixture. iOS framework finality does not establish every locale/device pairing.

### Module-by-module residual work

The owner for each row is the corresponding current registry owner. These rows
are work assignments, not accepted module-review records.

| Module | Next implementation/specification and acceptance increment |
|---|---|
| mobile-shell | lifecycle/navigation ownership, permission and recovery UX, process death, deep links, accessibility and localization |
| edge-runtime | dependency graph, cancellation/resource budgets, complete recovery walkthrough and extension procedure |
| policy-tool-gateway | complete decision table and real identity/biometric composition; exact invariant-to-test mapping |
| audit-journal | format/migration, capacity/rotation, backup exclusion and anchor/rollback drills |
| g1-transport | platform sequence diagrams, firmware capability matrix, physical queue/reconnect/readback evidence |
| g1-protocol-features | review existing schema-v3 matrix; vendor confirmation and real device coverage |
| assistant-speech | LC3/PCM/ASR finality, locale matrix, interruption/background behavior, privacy and latency measurement |
| android-native | qualify existing ticket-bound PCM-to-ASR source with real bootstrap/tenant, permission/OEM lifecycle, signing and attestation integration |
| ios-native | resolve native-test failure and qualify OS/device/locale/interruption behavior |
| digital-twin | explicit scenario/fidelity matrix and mapping to physical qualification limitations |
| model-gateway-service | real authenticated ingress/tenant composition, bounded operations and independent provider qualification |
| identity-control-plane | account authorization, actual broker/KMS/platform proof, lost-device recovery and revoke consumers |
| realtime-control-plane | consolidate current v4 state/migrations; real provider, session lifetime and cleanup operations |
| capability-control-plane | enabled-adapter inventory, authenticated leases/OAuth custody and encrypted recovery-payload design |
| skills-registry | current restricted execution profile, root administration, package custody and running-task revocation |
| memory | actual per-subject cipher/KMS, backup/deletion propagation and clock-failure deletion procedure |
| codex-worker | real namespace/seccomp/cgroup/identity/egress deployment and compromise exercise |
| mcp-adapter | framing/error/lifecycle specification and tested host/protocol compatibility matrix |
| qualification-release | source-to-binary evidence lifecycle, physical custody, promotion and rollback drills |
| contracts-compatibility | supported producer/consumer version pairs, deprecation and migration ownership |
| repository-governance | current live setting readback, eligible reviewers and emergency procedure without bypass |
| native-dependencies | upstream revision/digest, patches/licenses/ABI, vulnerability owner and upgrade/rollback proof |
| external-evidence-authentication | operated out-of-band trust roots and authentic issuer/acceptance records |
| latest-head-ci-custody | runner/queue incidents and retained-artifact recovery with exact-head custody |
| authority-quorum-review-integrity | trusted runtime deployment and independently accepted verifier profile |
| agent-os-plugin | real host install/uninstall/rollback and version compatibility tests |

The existing `SEMANTIC_PARTIAL` assessments are not promoted by this package.
Each completed module still needs an independent exact-source/document/contract/
test review binding under the existing completeness standard.

## P2 — sustained operation and recovery

`services/qualification/model_capacity.py` adds an operator-only read-only
observer for the actual model-gateway v2 table/policy layout. It reads persisted
limits, request-state counts, the combined cancellation/session-denial budget,
and exhausted unresolved readbacks in a single SQLite read transaction. It does
not instantiate a provider, return subject/provider identifiers, refund quota,
compact rows, delete tombstones, reset suspension or extend deadlines.

Thresholds of 80% and 95% are diagnostic warning levels, not admission policy or
measured production capacity. Exhausted/suspended state stays visible. Missing
files are never created; missing tables, unknown versions and malformed policy
are errors, not empty capacity. Tests use real SQLite, concurrent uncommitted
writers and actual schema fixtures. The full-repository suite also contains a real-gateway constructor test that
asserts observation causes no provider work; its execution is not reported as
passing by this document.

See `../operations/PRIORITY_EXECUTION_RUNBOOK.md` for capacity, uncertain effect,
backup/restore, privacy and operator escalation. This observer is a first
operational increment, not a metrics exporter or complete operations platform.
Encrypted recovery payloads, deployed KMS, deletion propagation, cross-service
revocation, safe archival and external anti-rollback remain implementation and
integration work, not merely paperwork to be accepted later.

## P3 — external qualification before ecosystem expansion

Use the existing `docs/EXTERNAL_CLOSURE_PROGRAM.json`, external-evidence contracts,
trust-registry administration and release gates. The runbook below supplies an
execution/checklist handoff; it does not mint authority or accepted evidence.

Actual device/firmware, model and speech tenants, KMS/attestation, credential
incident closure, independent assurance, signing, pilot, rollback and store
facts must be supplied by their real owners. Neither an uploaded checklist nor
a green source test closes these requirements. No production deployment, signing,
provider-account mutation, protection change, self-approval or merge is part of
this source increment.

## Verification and handoff

From a full clean checkout:

```bash
python3 -m unittest services.qualification.test_ios_ci -v
python3 -m unittest services.qualification.test_module_document_links -v
python3 -m unittest services.qualification.test_model_capacity -v
python3 tools/generate_module_docs.py --check
python3 tools/validate_module_semantics.py
python3 tools/validate_source_coverage.py
```

Then execute the unchanged seven-lane canonical workflow. Do not substitute the
commands above for the full service/mobile/native/history/evidence jobs. The
local affected-path workspace cannot qualify the absent Flutter SDK, Xcode,
physical devices or deployed integrations. Keep a successor Draft until its
exact-head jobs, artifact inspection and eligible independent review are complete.

### Primary tool references checked for this increment

- Dart locked dependency retrieval: https://dart.dev/tools/pub/cmd/pub-get
- XCTest timeout semantics: https://developer.apple.com/documentation/xctest/xctestcase/executiontimeallowance

The repository's fixed source contracts and observed toolchain remain the
acceptance subject; a documentation link alone is not execution evidence.

## Successor identity correction after the first CI run

The first run of this work on PR #126 was rejected because the inherited current-successor pointer still named PR #125. This successor updates the three expected PR/head-branch/base-branch identifiers, the machine pointer, current-state prose and repository regression expectations together. All verification functions and the independently qualified PR #101 tuple remain unchanged. The live head comparison is retained; no environment override, ignored failure, inherited approval or historical Artifact transfer is introduced. The additional pointer tests use inert API fixtures and prove only the local acceptance/rejection boundary, not live baseline qualification. A separate follow-up repairs the two Flutter fixture initializing-formal lint diagnostics without changing test assertions.
