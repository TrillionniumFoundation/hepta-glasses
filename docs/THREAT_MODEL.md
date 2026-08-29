
# Threat model

## Assets

- microphone and transcript data;
- device identity and pairing state;
- user identity, OAuth state, and short-lived tokens;
- notification, calendar, location, and reminder data;
- task and audit records;
- model prompts and responses;
- Codex workspaces, patches, and test artifacts;
- release and firmware-signing material outside this repository.

## Trust boundaries

1. G1 firmware and BLE radio to mobile transport.
2. Native Android/iOS platform channels to Flutter and edge runtime.
3. Edge runtime to cloud identity/model services.
4. Runtime or control plane to MCP servers and Codex workers.
5. Codex workspace to repository and build systems.
6. Release service to signing material and deployment channels.

## Principal threats and controls

| Threat | Control |
|---|---|
| BLE replay or duplicate write | sequence, bounded retry, idempotency, reconciliation |
| Partial left/right application | per-leg receipt, degraded state, no silent success |
| Provider key extraction from APK | no provider key or provider endpoint in mobile client |
| Prompt injection from notifications/web/documents | untrusted-data labeling, narrow tools, deterministic policy |
| Model widening its own authority | external lease issuance and exact action constraints |
| Lease replay | single-use consumption and durable receipt |
| Timeout causing duplicate side effect | journal-before-effect and authoritative status lookup |
| Sensitive transcript logging | privacy-safe logger and repository scan |
| Malicious MCP server | read-only default, explicit tool registry, no inferred authority |
| Codex workspace escape | canonical path check, read-only/workspace-write only, network off |
| Codex sandbox bypass | product validator forbids full access, yolo, and bypass flags |
| Cross-user task access | task/device/subject binding; production identity broker required |
| Journal tampering | SHA-256 chain and recovery integrity check |
| Stolen device | remote revocation and device attestation remain production blockers |

## Fail-closed rules

Invalid protocol frames, unknown tools, stale sessions, expired leases, inconsistent journal
links, mismatched idempotency fingerprints, untrusted workspace paths, and R4 requests are denied.
No fallback may convert denial into an unrestricted shell, raw BLE write, direct provider request,
or hidden approval path.
