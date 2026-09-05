# Codex specialist worker

The worker accepts a typed task envelope and constructs a fixed non-interactive Codex invocation.
It supports only `read-only` and `workspace-write`, creates an ephemeral thread, fixes the working
directory below an operator-owned root, bounds runtime/output, and filters the child environment.
The prompt cannot add CLI flags, change the executable, choose another workspace root, or inject
credentials.

The source test uses `--dry-run`; it does not claim that Codex is installed, authenticated, or
reachable in a deployed worker. Production allocation, per-task identity, egress policy, secrets,
resource isolation, patch custody, and review remain deployment evidence.
