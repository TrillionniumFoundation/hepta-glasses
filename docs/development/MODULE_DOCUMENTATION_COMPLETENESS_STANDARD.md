# Module documentation completeness standard

Status: mandatory semantic review standard for all 26 registered modules.  
Applies to: owner-authored primary documents, generated module handoff pages, contracts, tests and operational runbooks.

Generated pages under `docs/modules/<module>/README.md` prove navigation and registry consistency. They do not, by themselves, prove that a module has a complete technical design. A module is “detailed-documentation complete” only when its owner-authored documentation satisfies this standard and an eligible independent reviewer checks it against the exact implementation, contracts and tests.

An author, maintainer, automation job or coordination review may assess that material is substantial, but that assessment is not `SEMANTIC_COMPLETE_SOURCE`. Completion is an accepted evidence state, not a descriptive adjective.

## 1. Required engineering dimensions

Every module's primary technical document must contain substantive, module-specific treatment of all dimensions below.

### 1.1 Purpose, responsibility and non-goals

Define the module's job, the decisions it owns, the decisions it must not make, its trusted callers, and its relationship to device, mobile, cloud, provider, model, Skill, MCP, Codex, release and external-authority boundaries.

### 1.2 Component and source map

List entry points, internal components, source roots and runtime dependencies. Identify composition roots, process boundaries, native boundaries, durable stores, provider adapters and generated code. A directory listing without responsibility mapping is insufficient.

### 1.3 Public interfaces and contracts

Document every externally or cross-module visible API, event, channel, schema, command, error class and receipt. Include field types, required/optional semantics, size limits, version, authority identity, examples and compatibility rules. Machine contracts remain normative where prose disagrees.

### 1.4 State machine and invariants

Name all durable and in-memory states, legal transitions, terminal states and invariants. Include generation fencing, pair/side ownership, authority expiry, revocation, cancellation and stale-result rules where applicable. Diagrams must identify which component is allowed to commit each transition.

### 1.5 Concurrency and atomicity

Specify locks, transactions, queues, worker pools, ordering, coalescing, idempotency keys, uniqueness domains, backpressure and capacity exhaustion. Distinguish process-local serialization from cross-process, database, provider and physical-device atomicity.

### 1.6 Failure, retry, reconciliation and recovery

For each failure window, state whether no effect occurred, an effect may have occurred, or an effect is authoritatively committed. Define retry safety, quarantine, readback, reconciliation, crash recovery, restart behavior and operator escalation. A timeout must never be silently translated into “failed” when a write may have escaped.

### 1.7 Configuration, compatibility, migration and rollback

List every security- or behavior-relevant setting, default, hard bound, persisted policy identity, toolchain/runtime version and environment dependency. Describe compatible changes, breaking changes, offline migrations, mixed-version prohibitions, rollback conditions and anti-rollback requirements.

### 1.8 Operations, observability and SLOs

Define startup/shutdown, health, readiness, maintenance, capacity, rotation, backup, restore, deletion, incident and rollback procedures. List privacy-safe metrics, logs, traces, correlation identifiers, alerts and SLOs. Avoid raw audio, credentials, notification bodies, sensitive transcripts, precise location and personal accessibility data.

### 1.9 Security, privacy and abuse cases

Identify assets, trust boundaries, attacker capabilities, prompt-injection/untrusted-content treatment, credential/key custody, data classes, retention, consent, export, deletion, regional processing and abuse controls. State what source tests cannot establish.

### 1.10 Verification and acceptance

Map each invariant to positive, negative, malformed-input, concurrency, cancellation, timeout, crash-window and migration tests. Separate unit, contract, integration, physical, assurance, pilot and release evidence. Include exact commands and acceptance thresholds where meaningful.

### 1.11 Ownership and change protocol

Name the accountable owner and required co-reviewers. Define which code, schema, configuration, provider, firmware or policy changes require documentation, contract, test, Gap Ledger, Evidence Index, migration and requalification updates.

## 2. Minimum content quality

A primary document fails semantic completeness when it:

- merely repeats the generated handoff template;
- lists files without explaining data flow and ownership;
- describes only the happy path;
- contains unresolved `TODO`, `TBD`, placeholder or “coming soon” claims in a required dimension;
- omits exact error meanings or retry safety;
- conflates local source tests with deployed, physical, independent or release evidence;
- describes a predecessor API, branch, status or provider profile as current;
- leaves compatibility, migration, rollback, security, privacy, observability or SLO behavior implicit;
- claims authority that the module cannot possess.

Document length is not an acceptance criterion. Concise precise specifications can pass; long copied prose can fail.

## 3. Module-specific mandatory additions

The following modules require additional detail beyond the shared dimensions.

| Module group | Mandatory module-specific material |
|---|---|
| `mobile-shell` | app lifecycle, navigation/state ownership, permission UX, accessibility, localization, process death and deep-link/relaunch behavior |
| `edge-runtime`, `policy-tool-gateway`, `audit-journal` | exact authority flow, journal-before-effect windows, durable recovery, capacity, checkpoint/anchor limits and reconciliation |
| `g1-transport`, `g1-protocol-features`, `digital-twin` | byte framing, MTU/chunking, ACK/NACK, pair/generation/side identity, queueing, firmware capability/version matrix, fault-model fidelity and physical limits |
| `assistant-speech`, `android-native`, `ios-native` | LC3/PCM format, finality, locale/device support, permission/interruption/background handling, stale audio fencing, provider retention and latency budgets |
| identity/model/realtime/capability services | authenticated ingress, tenant binding, database schema/state, final pre-send admission, revoke propagation, authoritative receipts and multi-instance limits |
| `skills-registry`, `memory`, `codex-worker`, `mcp-adapter` | package/data/process custody, sandbox/egress limits, consent/revocation, subject isolation, protocol negotiation and host compatibility |
| qualification, compatibility and governance modules | evidence identity, exact-head invalidation, source/binary distinction, version policy, branch settings, independent review and no-bypass semantics |
| `native-dependencies` | exact upstream commit/archive digest, supplier, license, patch inventory, build flags, ABI, sanitizer coverage, vulnerability owner, upgrade and rollback |
| external evidence modules | trust-root administration, authority seats, cryptographic preimages, filesystem/runtime custody, reviewer independence and aggregate acceptance |

## 4. Review protocol

For every module changed by a pull request:

1. Compare the live implementation, contracts, tests, primary document and generated page.
2. Check all eleven engineering dimensions, not only file existence or heading order.
3. Verify examples and commands against the exact head.
4. Record concrete omissions, contradictions and stale claims as review findings.
5. Require the accountable module owner to resolve or explicitly scope each finding.
6. Regenerate module pages when the canonical registry changes.
7. Run `python3 tools/generate_module_docs.py --check` and `python3 tools/validate_module_semantics.py`.
8. Run all seven canonical jobs on the unchanged final head.
9. Do not mark documentation complete from the author's assertion, a coordination-PR approval, or an automated character-count check alone.
10. Bind the final module decision to the exact source head, primary-document digest, applicable contract/test inventory, accountable owner and independent review ID.

A reviewer of a cross-repository coordination or index change certifies only the reviewed delta. That review cannot retroactively certify every inherited module implementation.

## 5. Assessment and completion states

A module may be recorded as:

- `STRUCTURAL_ONLY`: registry, generated page and references exist;
- `SEMANTIC_PARTIAL`: substantive design exists but one or more required dimensions, current-state reconciliations or independent module-specific review bindings are incomplete;
- `PROVISIONAL_SUBSTANTIVE_ASSESSMENT`: an author or maintainer believes all dimensions appear substantial, but the exact independent module-specific review binding has not yet been accepted; this is not completion and must not be promoted as such;
- `SEMANTIC_COMPLETE_SOURCE`: all dimensions are implemented and independently reviewed against the exact source/contracts/tests, with the accepted review binding recorded;
- `OPERATIONS_QUALIFIED`: operational procedures and controlled integration evidence exist;
- `PHYSICAL_OR_EXTERNAL_QUALIFIED`: required provider/device/vendor facts are independently evidenced;
- `RELEASE_QUALIFIED`: exact release candidate satisfies all applicable assurance and distribution gates.

`SEMANTIC_COMPLETE_SOURCE` requires, at minimum, an accepted record containing:

- module ID and accountable owner;
- repository, exact commit and tree;
- primary-document path and digest;
- applicable contract and test inventory digests;
- independent reviewer identity, review ID, decision and timestamp;
- resolved findings and explicit residual limitations;
- confirmation that the reviewer is not merely approving an index/coordination change.

Without that record, a module remains `SEMANTIC_PARTIAL` or, at most, `PROVISIONAL_SUBSTANTIVE_ASSESSMENT`.

These documentation states do not replace the canonical product maturity model. The product remains bounded by the least mature required evidence axis.
