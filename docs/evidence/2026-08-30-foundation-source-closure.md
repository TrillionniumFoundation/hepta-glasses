
# AI-native foundation source evidence

Date: 2026-08-30

Baseline: `32178d3cb4ae38c2ef91db05bde836838c274259`

This record covers the repository-side foundation package only. It records the presence of
canonical truth, typed schemas, deterministic device abstractions, audit/task/policy/tool runtime,
development model gateway, safe Codex launcher, MCP surface, tests, and CI configuration.

Required exact-head checks:

```bash
python3 tools/validate_repository.py
python3 -m unittest discover -s services -p 'test_*.py'
python3 -m unittest discover -s adapters -p 'test_*.py'
flutter pub get
flutter analyze --no-fatal-infos --no-fatal-warnings
flutter test
```

The GitHub Actions run associated with the PR head is the E4 record. This document is not evidence
of a physical G1 effect, production credentials, firmware access, privacy approval, a pilot, or a
release. Those remain explicitly blocked in the Gap Ledger.
