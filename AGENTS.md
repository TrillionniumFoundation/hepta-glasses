# Codex operating contract for Hepta Glasses OS

## Scope

Work only inside this repository and preserve `UPSTREAM.md` and `LICENSE`. Treat the canonical plan, Current State, Gap Ledger, Evidence Index, schemas, and contracts as current truth.

## Required behavior

- Revalidate exact base, head commit, and tree before every package.
- Continue in one isolated package branch/PR; never merge your own PR.
- Do not claim physical device, production credentials, vendor firmware, independent review, pilot, or release closure from source tests or the digital twin.
- Keep model, realtime, Skill, MCP, and Codex output outside final execution authority.
- Journal mutations before effect and preserve idempotency across retry, restart, and reconciliation.
- Never add provider keys, OAuth refresh tokens, signing keys, KMS material, account credentials, raw audio, or sensitive transcripts to source, fixtures, logs, prompts, or artifacts.
- Never introduce sandbox bypass, unrestricted full access, hidden mutation MCP tools, or self-merge.
- Preserve bounded payloads, queues, scopes, domains, deadlines, cancellation, generation fencing, and fail-closed recovery.
- A source gate may close only with exact-head evidence. A blocked external gate moves only with its required E5–E7 evidence.

## Required checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m compileall -q services adapters tools
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

For source-evidence generation:

```bash
CI_REPOSITORY_CONTRACTS=success CI_FLUTTER=success CI_SECRET_SCAN=success \
python3 tools/build_source_evidence.py --output-dir build/evidence
python3 tools/evaluate_release_gate.py \
  --bundle build/evidence/source-release-bundle.json --mode source
```
