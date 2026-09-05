# Restricted R0 data Skill runtime

Status: incremental HG-0087/skills source implementation; skills and aggregate
HG-0087 remain **OPEN**. Owner: skills. Source:
`services/skills/data_vm.py`. Regression:
`services/skills/test_data_vm.py`. Contract:
`contracts/data-skill-runtime-v1.json`. Operations:
`docs/operations/DATA_SKILL_RUNTIME_RUNBOOK.md`.

## Responsibility and supported package profile

`DataSkillRuntime` executes a deliberately narrow class of already admitted
signed Skills: canonical JSON, acyclic, pure-data programs. It receives a real
`SignedSkillRegistry`, resolves the exact package before execution, interprets
only the signed entrypoint bytes, and resolves the same package again before
releasing output. A revoked, replaced, expired, dependency-invalid or otherwise
changed admission therefore cannot release a stale result.

This is **not** a Python, JavaScript, shell, WASM, native-code or plugin loader.
Package files are immutable byte snapshots from `CheckedSkill`; the runtime
selects one exact `.json` entrypoint and never extracts files, imports modules,
uses dynamic evaluation, starts a process, opens a file or socket, or calls a
package-supplied callback. Other package members remain inert data.

The accepted manifest profile is intentionally strict:

- `risk_tier` must be `R0`;
- `capabilities` and `network_domains` must both be empty arrays;
- each invocation declares its actual data classes, which must be a subset of
  the signed manifest's `data_classes`; and
- the entrypoint must be one exact package member ending in `.json`.

This implements a real zero-egress, no-effect execution subset by construction.
It does not make arbitrary publisher code safe and does not close the general
sandbox or capability-mediated executor requirement.

## Program contract

The entrypoint is canonical UTF-8 JSON with exactly:

```json
{
  "result": "output",
  "schema_version": 1,
  "steps": [
    {"id": "name", "op": "input", "path": ["name"]},
    {"id": "prefix", "op": "literal", "value": "Hello "},
    {"id": "output", "op": "concat", "items": ["prefix", "name"]}
  ]
}
```

Steps execute in array order. IDs are unique signed Skill names and may reference
only prior steps, so package-controlled loops and recursion do not exist. The
supported opcodes are:

| Opcode | Operation |
|---|---|
| `literal` | Admit one bounded plain JSON value |
| `input` | Traverse the defensively copied invocation by string keys or integer list indexes |
| `lower`, `upper` | Unicode string case transformation |
| `length` | Length of a string, list or object |
| `concat` | Concatenate previously computed strings |
| `array` | Build an array from prior values |
| `object` | Build an object from prior values and bounded field names |
| `equal` | Compare two prior plain JSON values |
| `select` | Select one prior value using a prior boolean |
| `slice` | Bounded nonnegative slice of a string or list |

Unknown opcodes, extra fields, forward references, duplicate IDs, malformed or
noncanonical JSON, missing paths and type mismatches fail closed. There is no
extension hook that can reinterpret an unknown opcode.

## Bounds, cancellation and determinism

Programs are limited to 64 KiB and 256 steps. Inputs and outputs are each limited
to 64 KiB canonical JSON. Collections are limited to 256 members, depth to 8,
node count to 2,048 and signed-integer magnitude to JavaScript's exact integer
range. Floating-point values are excluded to avoid cross-language and nonfinite
ambiguity. Each intermediate is independently bounded and cumulative canonical
working data is limited to 256 KiB.

The effective deadline is the smaller of the caller timeout and the signed
manifest `timeout_ms`. A trusted monotonic clock and optional `threading.Event`
are checked before and after every step and before result release. Because no
package opcode can perform I/O, spawn code, loop or invoke callbacks, package
work is cooperatively terminable at those finite checkpoints. Python process
scheduling and registry signature verification are still host operations; this
is not hard real-time or hostile-process containment.

Input is accepted only as exact built-in JSON types and is canonicalized before
the first registry resolution. Custom mappings, objects, surrogates, floats and
oversized integers cannot execute user-defined methods during interpretation.
Output is retained as immutable canonical bytes; the decoded `output` property
returns a fresh defensive object each time.

## State, revocation and failure semantics

The runtime stores no package, input, output or task state. The registry remains
the durable authority for publisher keys, exact consent, dependency binding,
version replacement and revocation. Execution performs:

1. exact registry `resolve(skill_id, package=...)`;
2. manifest/profile and entrypoint validation;
3. bounded pure interpretation under the original deadline/cancellation event;
4. a second exact registry resolve; and
5. snapshot equality plus final deadline/cancellation check before output.

If final resolution reports revocation or expiry, that fixed registry error is
returned and computed output is withheld. If the same Skill ID now has a different
admission event, document, file snapshot or consent expiry, the runtime returns
`skill_vm_admission_changed`. A revocation immediately after the last check cannot
atomically retract bytes subsequently returned; callers must not treat pure Skill
output as device, network, tool or mutation authority.

Crashes lose the in-memory computation and do not create a side effect to recover.
Callers may re-run a pure invocation only under current registry authority. The
runtime deliberately has no durable task queue, background thread, remote receipt
or claim that execution happened exactly once.

## Platform and evidence boundary

The implementation uses standard Python JSON, hashing, monotonic time and a
threading cancellation event. It has no Linux namespace/seccomp dependency and
therefore also does not claim to confine arbitrary native or interpreter code.
Its zero-egress property follows from the closed data instruction set, not from a
network namespace applied to publisher code.

The deterministic regression suite exercises valid programs, inert Python package
members, forbidden network/capability/risk declarations, strict canonical format,
reference and type errors, bounded input/output/working state, cancellation,
timeouts, final registry revocation and defensive output. Local tests use a typed
fixture registry resolver; the existing signed-registry suite separately verifies
actual Ed25519, SQLite, package and revocation behavior. Exact-head full repository
CI and independent review remain required.

## Remaining HG-0087 Skills work

Skills remains OPEN for arbitrary-code isolation, OS/process resource controls,
capability-mediated I/O, nonempty-domain egress enforcement, running external task
termination, authenticated consent service, external publisher-root governance,
externally witnessed transparency, encrypted package storage and independent
package/deployment qualification. This R0 VM must not be used to claim those
broader guarantees.
