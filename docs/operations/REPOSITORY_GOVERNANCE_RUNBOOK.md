# Repository governance runbook

The canonical branch-protection payload is
`contracts/main-branch-protection-v1.json`. It is an exact security contract,
not a documentation example.

## Canonical policy

The active contract requires all seven canonical status checks and binds each
one to GitHub Actions application ID `15368`:

- `repository-contracts`
- `flutter`
- `android-native`
- `ios-native`
- `native-sanitizers`
- `secret-and-boundary-scan`
- `source-evidence`

It also requires strict base synchronization, administrator enforcement, one
Code Owner approval, stale-review dismissal, approval by someone other than
the most recent pusher, conversation resolution, linear history, no force
push, no branch deletion, no pull-request bypass actor, an unlocked branch,
no fork syncing while locked, and the declared branch-creation and push
restriction policy.

`services/qualification/governance.py` treats the contract as closed-world.
Unknown, missing, duplicated, weakened, wildcard-app, wrong-app, malformed, or
unread fields fail validation. A stronger-looking but different policy does
not silently inherit approval from this exact contract.

## Apply

Use a short-lived administrator token from a trusted operator environment.
The token must never enter source, an issue, pull request, Actions artifact,
ordinary log, command history, or evidence package.

```bash
HEPTA_REPO_ADMIN_TOKEN='<short-lived-token>' \
python3 tools/repository_governance.py --apply
```

`--apply` sends the canonical payload and then performs a fresh API GET of the
same branch-protection endpoint. It never accepts an offline snapshot as
post-apply evidence. Combining `--apply` and `--snapshot` is rejected before
any network mutation.

Local contracts, offline snapshots, and GitHub responses are limited to one
MiB and decoded as strict UTF-8 JSON. UTF-8 BOMs, duplicate object members,
non-finite numbers, malformed JSON, non-object roots, symlinked local inputs,
oversized responses, and unexpected HTTP failures fail closed.

## Verify only

Use a read-capable token for a fresh API observation:

```bash
HEPTA_REPO_ADMIN_TOKEN='<read-capable-token>' \
python3 tools/repository_governance.py
```

An offline snapshot is accepted only for deterministic verifier tests or an
independent replay of already captured bytes:

```bash
python3 tools/repository_governance.py \
  --snapshot evidence/governance/<date>/branch-protection.json
```

The verifier requires all of these predicates to pass:

- canonical closed-world contract shape
- strict required checks
- exact seven-context set with no duplicates
- exact GitHub Actions application binding for every check
- exact approval count
- stale-review dismissal
- Code Owner review
- most-recent-push approval
- empty pull-request bypass allowances
- administrator enforcement
- exact push restrictions
- linear history
- force push disabled
- branch deletion disabled
- declared branch-creation policy
- conversation resolution
- declared branch-lock policy
- declared fork-sync policy

## Independent readback and no-bypass observation

The apply identity and the independent governance observer must be distinct
where the authority model requires separation. After a successful apply,
capture a second complete API readback and separately inspect repository and
inherited rulesets. An empty classic bypass allowance does not prove that a
different applicable ruleset has no bypass actor.

The independent packet records:

- repository, branch, exact source commit and tree
- canonical contract SHA-256
- collection timestamp and API version
- sanitized complete branch-protection response
- verifier output with no missing predicate
- repository and inherited ruleset summaries
- operator identity/role and independent observer identity/role
- immutable evidence location and digest

Never include authorization headers, tokens, private keys, secret values, raw
provider credentials, or unrestricted administration material.

## Admission boundary

A passing source test proves only that the repository can evaluate a complete
readback. The administrator transaction remains open until the policy is
actually applied, independently observed, and accepted. Source code, a public
`protected=true` summary, screenshots, synthetic statuses, self-review,
administrator bypass, or an offline snapshot cannot close that authority
gate.
