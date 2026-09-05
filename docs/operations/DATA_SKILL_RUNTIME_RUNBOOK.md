# Restricted R0 data Skill runtime operations

Owner: skills. Design: `docs/development/DATA_SKILL_RUNTIME.md`.
Contract: `contracts/data-skill-runtime-v1.json`. HG-0087/skills remains OPEN.

## Admission and invocation

Install and resolve packages only through the production-composed
`SignedSkillRegistry` with externally governed publisher keys and authenticated
exact-manifest consent. Do not construct `CheckedSkill` from client JSON or call
the runtime with a substitute registry object. The runtime's type check is a
source guard, not a hostile Python-process security boundary.

Enable this runtime only for signed manifests with `risk_tier=R0`, empty
`capabilities`, empty `network_domains`, and a canonical JSON entrypoint. Reject
requests to reinterpret Python, JavaScript, shell, WASM or native files. Do not
add an opcode that opens files, sockets, subprocesses, dynamic imports, reflection
or host callbacks without a new threat model, contract, tests and independent
review.

Classify invocation data before calling the runtime. The declared invocation data
classes must be a subset of the signed manifest. Authentication, purpose consent,
data minimization and subject routing remain host responsibilities. Pass exact
built-in JSON objects only. Do not pass live custom mappings, lazy collections or
objects with user-defined iteration/serialization behavior. Do not put
credentials, raw audio or secrets into this R0 path merely because the VM has no
egress opcode.

## Input capture, cancellation, saturation and failures

The runtime copies and validates caller containers into one fresh built-in graph,
then serializes only that graph. It does not validate one graph and later reopen
the caller's mutable containers for serialization. Treat
`skill_vm_input_invalid` as the only contract result for unsupported types,
cycles, concurrent-copy failures, invalid Unicode, out-of-range values and input
bounds. Never retry by bypassing capture or handing the interpreter the original
mutable object.

Use a finite caller timeout and, when the request lifecycle has an explicit
cancellation signal, pass a dedicated `threading.Event`. A pre-set event is
rejected before input or registry work. The timeout starts before input capture;
a second checkpoint runs before the first registry resolve, so capture time cannot
silently extend the verifier budget. The signed manifest timeout can only shorten,
never replace or refresh, the original caller deadline. The VM retains checks
around every finite instruction and before result release.

Do not pass package-controlled clocks, events or custom JSON objects. Treat
`skill_vm_cancelled`, `skill_vm_deadline_expired`, format, reference, type, size
and policy errors as terminal for that invocation. Registry verification is
bounded separately; this runtime does not kill a noncooperative registry worker or
supply process isolation.

The runtime has no background queue and no partial result. A process crash loses
only pure in-memory computation. Re-run only after authenticating the caller and
resolving current registry authority again. Never convert a computed value into a
mutation without a separate current capability decision and final effect gate.

Registry resolution is performed before and after interpretation. Revocation,
expiry or version change during execution withholds output. Preserve the registry
database and package bytes for incident analysis; do not bypass final resolution,
patch the event sequence or cache an earlier `CheckedSkill` as execution authority.

## Logging and privacy

Log fixed error codes, Skill ID, bounded timing and aggregate counts only. Do not
log program bytes, invocation data, output, package contents, consent records or
publisher key material. `output_sha256` is a local integrity identifier, not
anonymization, provider evidence or a permission token.

The runtime persists no task data. Host logs, crash dumps, tracing, swap and caller
storage still require normal privacy controls. The VM does not implement Memory
retention, deletion propagation or encrypted package custody.

## Validation and change control

Run:

```bash
python3 -m unittest services.skills.test_data_vm -v
python3 -m unittest services.skills.test_signed_registry -v
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m compileall -q services/skills
```

The data-VM regression suite must include deterministic mutations at the input
capture/serialization boundary and assertions that pre-cancelled or pre-resolve
expired invocations make zero registry calls. Keep a concurrent mutation stress
probe as supplemental robustness evidence, not as a substitute for deterministic
tests.

Then run every canonical repository, Flutter, Android, iOS, sanitizer, boundary
and source-evidence lane on one unchanged head. Inspect the exact-head artifact and
obtain eligible independent review. The local VM tests do not establish publisher
root administration, arbitrary-code isolation, network-namespace enforcement,
production KMS, mobile integration or physical product qualification.

Keep the PR Draft until the broader acceptance plan is satisfied. Do not add a
fallback to arbitrary execution when a program fails validation. There is no
emergency override.
