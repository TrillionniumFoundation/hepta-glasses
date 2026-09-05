# Cloud provider source boundary and exact-byte declarations

Status: source-policy correction for the failed model candidate; independent
review and new exact-head CI still required. Owner: repository-governance.
Implementation: `tools/server_provider_boundary.py`, called from
`tools/validate_repository.py` and the existing secret-and-boundary CI job.
Contract: `contracts/server-provider-boundary-v1.json`. Regression suite:
`services/qualification/test_server_provider_boundary.py`.

## Failure, architecture and scope

Run 33941953758, job 101241002747, failed its repository validator on the model
candidate 9f9b5aa. The old scanner prohibited provider host markers and key names
in every scanned directory, including the cloud service. It therefore rejected
`responses_provider.py` and its existing wire tests before any service tests ran.
The workflow separately duplicated this global pattern. This is not evidence
that the model tests failed; the downstream tests were skipped.

The product definition assigns provider connections and long-lived provider
credentials to the cloud control plane, not the glasses, mobile runtime, MCP,
plugin or Codex worker. The active HG-0087 plan requires concrete provider
implementations. A blanket cloud-directory exclusion would be too broad. Hiding
host strings, removing tests, changing endpoint spelling or omitting the boundary
job would not repair that mismatch. This change instead declares exactly which
already-published cloud bytes may contain which architectural markers.

There is no change to the model adapter, its tests, consumer ingress, credential
handling, deployment routing or runtime authorization. No live provider request
or credential is used by this correction. All production slices remain OPEN.
This package does not include the separately platform-blocked R0 executor or
previously blocked identity, speech or Memory changes.

## Declaration contract and API

The contract contains exactly a version, contract ID and four entries. Each entry
has exactly `path`, `sha256` and `role`. Duplicate JSON keys, missing/extra rows,
unknown fields, wrong types, path variants, wildcards and changed roles fail.
The helper fixes the only supported slots in source; a JSON entry cannot invent
a new source path, add a pattern exception or choose a new provider.

| Fixed path | Role | Permitted marker only |
|---|---|---|
| `services/model_gateway/responses_provider.py` | cloud_transport | The existing OpenAI API host marker |
| `services/model_gateway/test_responses_provider.py` | wire_regression | That host marker and the existing inert provider key-name negative test |
| `services/control_plane/google_calendar.py` | capability_transport | The fixed Google Calendar API host marker only |
| `services/control_plane/test_google_calendar.py` | capability_wire_regression | The same Calendar host marker only |

The test key name is not a key value. It appears in an existing negative test
proving the provider does not consume environment overrides. An actual provider
credential, private key, GitHub token or execution bypass is not permitted by
this declaration. A new provider, a new runtime path or any changed file requires
an explicit reviewed source/contract update; there is no runtime override.

`ServerProviderBoundary(root)` reads and validates the declaration.
`inspect(relative_path, raw_bytes, patterns)` hashes and scans the same immutable
bytes. It never trusts a filename plus an earlier independent read. All original
patterns still run; only a matching marker category/value inside its fixed slot
can pass the exact-byte declaration. Private-key/token/bypass patterns have no
slots and are never exempt, even if a digest is deliberately updated.
`finish()` requires all four declared sources actually to have been scanned once.
A stale hash, absent file or duplicate scan is an error, not a silent exemption.

Source reads reject noncanonical paths, links, nonregular files, oversize reads,
invalid UTF-8 and identity/size changes while reading. The declaration is limited
to 8 KiB and source text reads to 8 MiB. The checkout and host are still trusted;
these checks are not a hostile-kernel or complete filesystem snapshot boundary.
No scanned directories or tests are excluded. All six original scan roots and
all original forbidden pattern categories are retained.

## Direct-import guard and its limits

For Python outside `services/model_gateway/`, the helper rejects direct imports
of the concrete provider module, including absolute imports, relative imports,
parent-module named imports and parent-module star imports. Syntax errors fail
closed. Each concrete transport is restricted to its own service root: the
Responses module to `services/model_gateway/`, and the Calendar module to
`services/control_plane/`. Neither service gets permission to import the other's
concrete provider. The new Calendar host marker is checked even if a caller only
passes the original five pattern categories; there is no new caller-side opt-out.

This is a static direct-import fence, not a complete whole-program analysis.
Dynamic imports, reflection, arbitrary new network clients, maliciously altered
validators and privileged host behavior require separate review and runtime
controls. The consumer package/build boundary, production-authority checks,
credential scanner and independent review remain required. Exact-byte approval
is repository source policy, not an external authority signature or deployment
credential. Changing both code and its hash cannot manufacture independent
acceptance. No product or release gate is declared closed by this file.

## CI integration and failure behavior

Both repository validation and the secret-and-boundary job call the same Python
boundary logic, so they cannot disagree about cloud declarations. The original
secret/bypass/consumer-authority checks remain in the shell block, including the
additional evidence directory secret scan. The shell guard now fails explicitly
on a match or a grep error, and suppresses matching content. Negation inside a
multi-command `set -e` block must not be relied on as a fail-fast assertion.

The seven job names, exact-head checkout, source evidence dependencies, artifact
binding, action pins, full test discovery, history scan and platform lanes are
unchanged. There is no workflow skip or automatic pass. A failed parent run is
historical evidence only. Source changes require a new complete unchanged-head
run and artifact inspection; prior green platform results do not transfer.

## Operations, migration and regression verification

When changing an approved cloud file, review its full diff, transport behavior,
credential path and tests first. Update only that entry's SHA-256 after the actual
bytes are settled, run the boundary and full repository suites, then request
eligible independent approval. Do not update a hash to bypass an unresolved
security objection. No general directory registration or emergency override is
supported by this version. A new provider profile requires explicit policy and
contract development, not inserting arbitrary JSON entries.

Run:

```bash
python3 -m unittest services.qualification.test_server_provider_boundary -v
python3 -c "from tools.validate_repository import validate_boundaries; validate_boundaries()"
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/validate_source_coverage.py
python3 tools/validate_module_handoff.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
```

The regression suite recreates the three original findings and exercises the
actual updated validator and actual CI shell block against temporary fixtures.
It rejects copied consumer providers, undeclared services, changed bytes, other
provider markers, widened declarations, credential/bypass material, symlinks,
invalid encoding and direct imports across the service boundary. It also checks
that consumer test authority, evidence secrets and grep I/O errors fail the CI
block without reflecting matched content. Fixtures are inert, not credentials.
Local affected-path testing is not a full repository checkout or seven-lane CI.
Full compatibility, signed-device/provider qualification, complete protected-main
settings and independent review remain separate acceptance requirements.

## Calendar increment validation

The Calendar source and its wire tests must match their independently enumerated
hash slots. `services/qualification/test_calendar_provider_boundary.py` adds
copied-source and cross-service import regressions. Existing boundary test
fixtures now copy every declared file while preserving all forty original tests.
The runtime provider remains an authenticated-host component, not a consumer API.
No scheduler, OAuth consent service, production credential or real event is
introduced by these declarations. Static fences do not prevent dynamic imports
or a privileged host from changing validators; independent review remains required.
