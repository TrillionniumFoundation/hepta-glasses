
# Codex operating contract for Hepta Glasses OS

## Scope

Work only inside this repository and preserve the exact upstream attribution in `UPSTREAM.md`
and `LICENSE`. Treat `docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md`, `docs/CURRENT_STATE.md`,
`docs/GAP_LEDGER.yaml`, and the machine-readable contracts under `schemas/` and `contracts/` as
canonical current truth.

## Required behavior

- Revalidate the exact base commit and tree before each package of work.
- Use an isolated branch or worktree. Do not merge your own pull request.
- Do not claim real-device, production credential, firmware, privacy, pilot, or release closure
  from source tests or the digital twin.
- Keep model output outside final execution authority.
- Journal mutations before effect and preserve idempotency across retry and restart.
- Never add a provider API key, OAuth refresh token, broker credential, or signing key to the
  mobile bundle, source tree, test fixture, log, prompt, or artifact.
- Never introduce `--dangerously-bypass-approvals-and-sandbox`, `--yolo`, or
  `danger-full-access` into a product path.
- Preserve bounded payloads, bounded queues, explicit deadlines, cancellation, and fail-closed
  recovery.

## Required checks

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

A gap may move to `CLOSED_SOURCE` only when its source acceptance evidence exists. Only external
or device evidence may move a `BLOCKED_*` item to `CLOSED_VERIFIED`.
