# ADR-0005: Cancel obsolete CI runs by pull-request or branch identity

- Status: accepted for G9 source
- Date: 2026-09-02
- Extends: G8 source evidence and repository-governance contracts

## Context

Every source-evidence packet must bind one exact commit and tree. The workflow therefore exports the live pull-request head SHA, checks out that object explicitly, and verifies `git rev-parse HEAD` before every job.

The former concurrency group also used the exact commit SHA:

```text
hepta-glasses-<workflow>-<head-sha>
```

That appears precise but defeats `cancel-in-progress`: every push creates a different concurrency group, so old pull-request heads continue building and waiting for scarce macOS runners. Several obsolete iOS jobs can remain queued while the only relevant latest head waits behind them. Old artifacts are non-authoritative, but they still consume capacity, confuse operators, and delay current evidence.

## Decision

Workflow concurrency is owned by the pull request number, or by branch name for non-pull-request events:

```text
hepta-glasses-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref_name }}
```

`cancel-in-progress: true` remains mandatory. A new push to the same pull request now cancels the previous workflow run rather than allowing multiple obsolete heads to proceed.

This scheduling identity is not source identity. Every canonical job continues to:

1. derive `SOURCE_HEAD_SHA` from the pull-request head or event SHA;
2. check out that exact SHA with full history and no persisted credentials;
3. compare `git rev-parse HEAD` to `SOURCE_HEAD_SHA` before qualification;
4. generate source evidence whose summary is checked against `SOURCE_HEAD_SHA`.

`tools/validate_production_authority.py` rejects SHA-keyed concurrency and requires the latest-head group. `services/qualification/test_ci_latest_head_custody.py` verifies both stale-run cancellation and exact-head checks in all seven jobs.

## Alternatives rejected

- **Commit-SHA concurrency:** never cancels an older head because every push receives a new group.
- **No concurrency control:** permits duplicate jobs and competing artifacts for the same pull request.
- **Branch-only source evidence:** scheduling identity would be mistaken for immutable source identity.
- **Cancel without in-job SHA verification:** a mutable branch checkout could qualify a different object from the requested head.
- **Self-modifying remediation workflow:** grants CI write authority over the source it is supposed to inspect.

## Consequences

At most one current workflow run per pull request or non-PR branch proceeds under the new workflow definition. Runs created under the old SHA-keyed definition may require GitHub to finish or an administrator to cancel them, but subsequent pushes no longer reproduce the backlog.

Any change to triggers, concurrency, checkout identity, exact-head verification, or artifact binding must update the validator, regression test, governance documentation, and gap ledger together.
