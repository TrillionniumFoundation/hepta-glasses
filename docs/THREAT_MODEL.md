# Threat model

## Assets

Microphone/transcript data; device identity and attestation; user identity and short-lived tokens; OAuth handles; notifications/calendar/location; task/audit/memory records; model prompts and responses; Skill packages and trust roots; Codex workspaces; mobile signing and firmware signing outside this repository.

## Trust boundaries

1. G1 firmware/BLE radio to mobile HAL.
2. Native platform channels to Flutter and edge runtime.
3. Edge runtime to control-plane token and realtime brokers.
4. Control plane to model/realtime providers and OAuth systems.
5. Tool Gateway to capability adapters and external authoritative state.
6. Skill package to registry/runtime.
7. Codex worker to repository/build systems.
8. Release service to signing material and deployment channels.

## Principal threats and controls

| Threat | Control |
|---|---|
| BLE replay or duplicate write | sequence, idempotency, per-leg receipt, reconciliation |
| Partial left/right application | explicit degraded state, no silent success |
| Provider key extraction | provider-neutral client, one-time bootstrap, server-side exchange |
| Stolen or cloned phone | attestation interface, subject/device binding, lost/revoke state |
| Token replay | short TTL, token ID, session/device binding, one-time bootstrap |
| Prompt injection from notification/web/document | untrusted trust class, exact human confirmation digest, narrow registry |
| Model widens authority | external lease issuance, exact action/argument binding, R4 deny |
| Timeout duplicates effect | journal-before-effect, external ID, authoritative reconciliation |
| Sensitive logging | metadata/digest-only audit and repository scans |
| Malicious Skill | publisher trust root, signature, package digest, domain/capability/data consent, revoke |
| Memory overreach | purpose/data consent, TTL, forbidden classes, export/delete |
| Codex workspace escape | canonical root, read-only/workspace-write only, bounded environment/network |
| Codex self-release | no BLE/signing/merge authority, independent review and release gate |
| False release claim | exact-head SBOM/provenance and non-overridable product evidence gate |

Unknown tools, invalid schemas, stale generations, expired/replayed tokens, inconsistent journals, mismatched fingerprints, untrusted mutation authority, unauthorized domains, revoked Skills/devices/sessions, and R4 requests fail closed.
