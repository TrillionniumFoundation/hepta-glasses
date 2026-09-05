# Production control-plane runbook

## Required production substitutions

The reference HMAC key ring is a source contract, not a key-management deployment. Production must provide:

1. KMS/HSM-backed active and verification keys with key IDs.
2. Android Play Integrity and Apple App Attest/DeviceCheck verifier implementations, or an approved equivalent.
3. Device registry persistence with subject/device uniqueness and lost/revoked states.
4. Token/session/device/subject revocation persistence and propagation.
5. Account recovery and device replacement workflow with step-up authentication.
6. Per-subject/device/IP rate limits and abuse monitoring.
7. Audit export that excludes token bodies, prompts, transcripts, and credentials.

## Rotation drill

- Add a new signing key ID.
- Issue new tokens only with the new key.
- Verify old unexpired tokens during the overlap window.
- Revoke a selected session and confirm immediate denial.
- Retire the old key after the maximum token TTL.
- Attach issuer logs, key IDs, timestamps, and verification results to the evidence bundle; never attach key material.

## Lost-device drill

- Mark the device `lost` in the registry.
- Revoke device and active sessions.
- Confirm model, realtime, capability, memory, and Codex entry points reject it.
- Confirm a replacement device requires fresh attestation and user authorization.
