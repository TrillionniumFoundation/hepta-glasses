
# Privacy model

## Data classes

| Class | Examples | Default handling |
|---|---|---|
| Public | product metadata, non-user protocol version | ordinary telemetry |
| Personal | locale, preferences, calendar titles | minimize and encrypt |
| Sensitive | transcript, notifications, location, contacts | task-scoped and redacted |
| Secret | provider keys, refresh tokens, signing keys | never enter mobile prompts/logs/source |

## Retention defaults

- Raw audio: process in memory and delete after the active session unless the user explicitly
  records it.
- Partial transcript: session memory only by default.
- Completed transcript and model answer: not retained by the runtime unless the user enables
  history; existing UI history must be treated as user-visible local data.
- Working task state: retained until task completion and bounded recovery expiry.
- Audit metadata: retain action identifiers, policy decisions, and hashes; avoid raw content.
- User-approved memory: encrypted, inspectable, individually deletable, and revocable.
- Permanent credentials: cloud or OS secure storage only, never the audit journal.

## User controls required before pilot

- microphone and cloud-processing indicators;
- inspect/delete/export memory and history;
- revoke a device or skill;
- disable cloud sync;
- restrict a skill's data classes;
- view recent Agent actions and receipts;
- delete the account and associated task state.

## Logging

Logs may contain trace IDs, task IDs, event types, timings, byte counts, error categories, and
redacted hashes. Logs must not contain raw audio, transcript text, model answers, authorization
headers, provider responses, tokens, or credentials.
