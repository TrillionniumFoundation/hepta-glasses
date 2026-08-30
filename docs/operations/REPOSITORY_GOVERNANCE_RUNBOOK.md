# Repository governance runbook

The canonical `main` protection contract is `contracts/main-branch-protection-v1.json`. Source automation may generate, apply, and verify the request, but the gate remains `BLOCKED_ADMIN_SETTING` until GitHub returns the active protected-branch/ruleset state.

## Required `main` controls

- strict required checks: `repository-contracts`, `flutter`, `android-native`, `ios-native`, `native-sanitizers`, `secret-and-boundary-scan`, and `source-evidence`;
- at least one independent approval and CODEOWNER review;
- last-push approval and stale-review dismissal;
- all conversations resolved;
- admin enforcement and linear history;
- force push and branch deletion disabled.

## Apply and verify

Use a short-lived repository-admin token in a controlled environment with `tools/repository_governance.py`. Never store the token or API response containing sensitive headers. Verify the returned configuration against the canonical contract and save a redacted content-addressed response under `evidence/governance/<date>.json`.

## Merge custody

The implementing agent may prepare and update a PR but may not approve or merge it. The independent maintainer must inspect the exact head, evidence artifact, new dependency inventory, historical credential summary, and unresolved external gates. After merge, rerun exact-head CI on the resulting `main` commit; pre-merge evidence cannot be promoted to post-merge evidence.

Any temporary weakening must be time-bounded, independently approved, recorded, and automatically restored. A manual statement that protection is enabled is not evidence.
