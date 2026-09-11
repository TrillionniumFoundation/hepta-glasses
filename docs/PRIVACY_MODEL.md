# Privacy model

## Data classes

| Class | Examples | Default handling |
|---|---|---|
| Public | protocol and product metadata | ordinary telemetry |
| Personal | locale, preferences, calendar titles | minimize, purpose-bind, encrypt in production |
| Sensitive | transcripts, notifications, location, contacts | task-scoped, redacted, explicit capability |
| Secret | provider keys, refresh tokens, signing/KMS keys | never enter mobile prompts, logs, memory, or source |

## Defaults

- Raw audio: memory-only processing and deletion after the active session unless the user explicitly records it.
- Partial transcript: active-session memory only.
- Completed transcript/answer history: **disabled by default on every application start**. An explicit in-app opt-in permits process-memory history only; disabling history immediately clears every retained question, answer, and selection, and process exit clears it implicitly.
- Persistent transcript/answer history: unavailable in the current source candidate. It must not be introduced until encrypted storage, explicit purpose/data-class consent, retention, export, deletion, backup exclusion, and migration behavior are implemented and independently reviewed.
- Working task state: bounded recovery retention.
- Audit: identifiers, decisions, timings, sizes, error classes, and content digests—not content.
- User memory: explicit subject/purpose/data-class consent, TTL, export, individual delete, purpose revoke, and subject delete.
- Forbidden memory classes: raw audio, credential, and secret.
- OAuth/provider/signing material: OS secure storage, KMS/HSM, or server credential vault only.

## Consent invariants

1. Rendering a transcript or answer does not itself authorize history retention.
2. Model, Skill, MCP, notification, document, webpage, or transcript content cannot enable history.
3. History consent is a direct user action, is not persisted by the current implementation, and therefore returns to disabled after restart.
4. Opt-out is destructive for process-memory history and must not leave hidden copies in audit, logs, analytics, crash reports, or task metadata.
5. Audit and telemetry may record only history-state transitions and aggregate counts; they must never contain transcript or answer content.

## Production requirements

Encrypted persistent memory, key rotation, backup/deletion semantics, regional retention, provider retention, abuse monitoring, subprocessor inventory, user export/delete UI, device/Skill revoke, account deletion, and independently verified consent UX require deployed evidence and independent review.
