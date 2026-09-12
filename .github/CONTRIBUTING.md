# Contributing to Hepta Glasses

Hepta Glasses spans Flutter, Android, iOS, native audio code, Python services, contracts, qualification and repository governance. Changes are accepted by exact source identity, executable verification and independent review—not by prose claims or local success alone.

## 1. Choose the correct source object

Before editing, identify the live pull request or branch that owns the work. The default branch may remain an older protected baseline while a successor is under review. Record the base SHA and current head SHA. Do not copy fixes between divergent branches without documenting the actual source/delta relationship.

Never reuse CI, artifacts or approvals from another head. Any commit, including documentation-only changes, creates a new exact-head candidate.

## 2. Keep changes reviewable

Prefer one coherent change with a bounded authority surface. Avoid combining unrelated mobile, cloud, native, evidence and governance work. For a large program, use a dependency-ordered series of small pull requests with explicit base branches and no hidden evidence transfer.

A pull request must explain:

- purpose and non-goals;
- affected modules and accountable owners;
- interfaces, contracts and state transitions changed;
- failure, retry, reconciliation and migration effects;
- security, privacy and evidence-ceiling impact;
- tests run and tests still external;
- rollback or supersession behavior;
- exact blockers that remain.

## 3. Update all affected truth surfaces

When behavior or a claimed invariant changes, update the affected source, contract, tests, owner-authored module document, module registry, generated handoff, Gap Ledger, Evidence Index, current state, migration/runbook and release template in the same reviewed candidate where applicable.

Generated pages do not replace owner-authored technical specifications. Apply `docs/development/MODULE_DOCUMENTATION_COMPLETENESS_STANDARD.md` during review.

Do not introduce `TODO`, `TBD`, placeholder or “coming soon” text into a required engineering dimension. State a real external gate instead of pretending an unavailable production integration is implemented.

## 4. Local verification

Run the applicable focused suites, then the repository-wide checks available in your environment. Typical commands include:

```bash
python3 tools/validate_repository.py
python3 tools/validate_repository_metadata.py
python3 tools/validate_production_authority.py
python3 tools/generate_module_docs.py --check
python3 tools/validate_module_semantics.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-fatal-infos
flutter test
```

Native and platform changes additionally require the Android, iOS and sanitizer paths defined in `.github/workflows/ci.yml`. Local execution is useful but does not replace the seven-job exact-head GitHub run and content-verified artifact.

## 5. Security and privacy

Follow `.github/SECURITY.md`. Never commit or paste:

- provider keys, tokens, refresh tokens or signing material;
- private Ed25519 keys or repository-administration credentials;
- raw audio, sensitive transcripts, notification bodies, calendar contents, location history or accessibility data;
- proprietary firmware or recovery material not authorized for disclosure;
- test-only authority reachable from production code;
- synthetic receipts presented as provider, hardware, vendor, review or release evidence.

Use fixed safe error codes and privacy-safe metadata. Hashing a low-entropy identifier is not anonymization.

## 6. Effect and recovery semantics

Every mutating path must preserve these distinctions:

- rejected before effect: retry may be safe after current authority is reacquired;
- effect may have occurred: return an indeterminate result and require authoritative reconciliation;
- authoritatively committed: return a typed receipt bound to exact arguments and effect identity.

Timeout, callback loss, disconnect, process death and missing acknowledgement are not proof of non-execution. Do not add blind retries. Bind requests to subject/device/task/action/arguments, idempotency identity, deadline and current generation or provider namespace as required.

## 7. Review and merge

The implementing identity must not self-approve. The eligible reviewer must inspect the exact final head, relevant source and contracts, negative paths, evidence ceiling and generated artifact. A predecessor approval does not transfer.

Do not merge by directly moving `main`, relaxing branch policy, dismissing valid objections, using administrator bypass, creating synthetic status, force-pushing or deleting evidence-bearing branches. Merge only through the ordinary protected path after the canonical checks and approval requirements are satisfied.

## 8. External and release work

Source changes can prepare adapters, schemas, validators, templates and runbooks. They cannot manufacture:

- provider/KMS/attestation receipts;
- physical G1 measurements;
- firmware-vendor authority;
- independent security/privacy/legal/accessibility/safety approval;
- production signing, pilot, rollback, rollout or store approval;
- an independently administered out-of-band trust registry.

Attach or reference those facts only through the authenticated external-evidence process. The complete product release gate has no override.
