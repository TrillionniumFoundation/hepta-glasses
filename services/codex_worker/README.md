# Codex specialist worker and bounded external-task supervision

The worker accepts a typed task envelope and constructs a fixed non-interactive
Codex invocation. It supports only `read-only` and `workspace-write`, creates an
ephemeral thread, fixes the working directory below an operator-owned root,
bounds runtime/output, filters the child environment, and uses the configured
network-isolation wrapper when network access is disabled. The prompt cannot add
CLI flags, change the executable, choose another workspace root, or inject
credentials.

`task_supervisor.py` is a separate, reusable trusted-host primitive for external
process custody. It binds one absolute executable through held no-follow file and
parent descriptors, rejects symlink, hard-link, foreign-owner, non-executable and
group/world-writable inputs, and executes the held object through `/proc/self/fd`.
A sealed memfd passes the child specification to an isolated Python launcher,
which sets `PR_SET_NO_NEW_PRIVS`, umask `077`, CPU/address-space/file-size/open-
file/process rlimits, and then replaces itself with the configured executable.
No shell is used, inherited descriptors are closed, and the target receives only
a bounded explicit environment plus a private temporary HOME/TMPDIR.

The supervisor places the launcher and all descendants in one process group.
Cancellation, wall-clock timeout, or combined output overflow sends `SIGKILL` to
the whole group and synchronously reaps the leader. This also covers the case
where the leader exits before a descendant that still holds stdout/stderr. A
committed start is never represented as successful termination merely because
the leader exited.

Run:

```bash
python3 -m unittest services.codex_worker.test_worker -v
python3 -m unittest services.codex_worker.test_task_supervisor -v
```

The supervisor tests execute real local programs and cover shell-injection
resistance, executable-object custody, insecure executable rejection, sanitized
environment/input, rlimits, output overflow, cancellation, timeout, forked
children and a group leader that exits before its descendant.

## Evidence and deployment boundary

The task supervisor closes the source-level forced-termination and basic process
resource-bound subproblem. It is **not** a complete arbitrary-code sandbox: it
does not create seccomp filters, mount/user/network namespaces, a filesystem
jail, capability-mediated I/O, broker-exclusive egress, per-task credentials, or
hostile-kernel isolation. `RLIMIT_NPROC` is per operating-system user and is not a
standalone tenant boundary. Invoke this component from a dedicated trusted
worker process and combine it with reviewed OS isolation before running
publisher-controlled Python, JavaScript, WASM or native code.

The original Codex source test uses `--dry-run`; it does not claim Codex is
installed, authenticated, or reachable in production. Real allocation,
identity, egress, secrets, patch custody, compromise exercises, independent
review, exact-head CI/artifact and release governance remain separate evidence.
