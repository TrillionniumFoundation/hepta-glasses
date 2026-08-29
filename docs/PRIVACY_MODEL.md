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
- Partial transcript: session memory only.
- Completed transcript/answer: local history only when user-enabled; never metadata audit content.
- Working task state: bounded recovery retention.
- Audit: identifiers, decisions, timings, sizes, error classes, and content digests—not content.
- User memory: explicit subject/purpose/data-class consent, TTL, export, individual delete, purpose revoke, and subject delete.
- Forbidden memory classes: raw audio, credential, and secret.
- OAuth/provider/signing material: OS secure storage, KMS/HSM, or server credential vault only.

## Production requirements

Encrypted persistent memory, key rotation, backup/deletion semantics, regional retention, provider retention, abuse monitoring, subprocessor inventory, user export/delete UI, device/Skill revoke, and account deletion require deployed evidence and independent review.
