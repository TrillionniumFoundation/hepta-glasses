# Privacy, security, and legal review checklist

## Privacy

- Raw audio default deletion verified.
- Transcript and answer retention are explicit and user-visible.
- Memory is opt-in, purpose-bound, data-class-bound, exportable, individually deletable, and fully deletable.
- Logs contain identifiers, timings, sizes, categories, and digests—not raw prompts, transcripts, answers, credentials, contacts, notification bodies, or locations.
- Provider retention, abuse monitoring, residency, subprocessors, and deletion semantics are documented for the deployed tenant.

## Security

- Mobile binary contains no provider master key, refresh token, release key, or Codex credential.
- Platform attestation, device revoke, session revoke, key rotation, and account recovery drills pass.
- Prompt injection cannot widen tool or capability authority.
- Capability timeout reconciliation produces no duplicate effects.
- Codex worker compromise cannot reach another user, production secrets, BLE, signing, or release authority.
- Skill signature, upgrade re-consent, network domain, revoke, and package digest checks pass.

## Legal and product

- Upstream BSD notice is retained.
- Third-party native libraries and distribution licenses are reviewed.
- Recording, notice, consent, accessibility, location, notification, biometric, and child-safety requirements are reviewed for launch jurisdictions.
- Marketing claims distinguish distributed companion OS from vendor firmware ownership.

Each reviewer signs an evidence record with scope, exact commit/tree, findings, exceptions, and expiration date.
