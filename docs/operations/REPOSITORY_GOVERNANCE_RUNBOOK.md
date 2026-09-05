# Repository governance runbook

The canonical protection payload is `contracts/main-branch-protection-v1.json`.

## Apply

Use a short-lived administrator token that is not stored in GitHub Actions logs or repository secrets unless organization policy explicitly permits it:

```bash
HEPTA_REPO_ADMIN_TOKEN='<short-lived-token>' \
python3 tools/repository_governance.py --apply
```

The command applies and then verifies strict required checks, one approval, stale-review dismissal, CODEOWNER review, admin enforcement, linear history, no force pushes, no deletion, and conversation resolution.

## Verify only

```bash
HEPTA_REPO_ADMIN_TOKEN='<read-capable-token>' \
python3 tools/repository_governance.py
```

Store the redacted GitHub protection response and command result as `evidence/governance/<date>.json`. The source contract alone does not close the admin-setting gate.
