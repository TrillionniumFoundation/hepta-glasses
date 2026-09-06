# Broker verdict lifetime at final identity enrollment

Owner: cloud-security. Scope: HG-0087/identity source correction, not production
attestation qualification. Main design: `docs/development/DURABLE_IDENTITY.md`.
Broker wire contract: `contracts/identity-authority-v1.json` (unchanged).
Regression: `services/control_plane/test_identity_enrollment_freshness.py`.

## Defect and implementation

The predecessor checked the broker verdict before calling `accept_attestation`,
but passed only the challenge, proof digest and receipt reference into the store.
The challenge could remain valid after the shorter broker verdict had expired.
The actual predecessor and real SQLite reproduce an active device at time 1002
for a verdict expiring at 1001 and challenge expiring at 1120.

`DurableIdentityAuthority.enroll` now snapshots the broker's scalar verdict fields
and passes its ORIGINAL `verified_at` and `expires_at` to the final store call.
The store requires two additional keyword arguments: `verified_at` and
`verification_expires_at`. Neither has a default. A receipt-only caller fails
rather than silently constructing a new verification lifetime from local time.
The broker response already includes both timestamps; its wire format is unchanged.

A shared `_attestation_window` check enforces integer timestamps and:

```text
current_time - 120 <= verified_at <= current_time
current_time < verification_expires_at <= persisted_challenge_expiry
```

The authority checks on receipt, and the store checks again under its write lock
after resolving the exact persisted challenge. After device insertion and nonce
consumption, the store samples its trusted clock again and checks the same window
before leaving the transaction. A backward movement between the two store samples
also rejects admission. The final failure rolls back BOTH writes; it does not
return an active device or consume the still-unspent challenge. Existing-device
re-enrollment follows the same final check without replacing prior device data.

No broker network call holds the store transaction. No raw proof, nonce, broker
payload or new private credential is persisted. Existing subject/device revocation,
challenge binding, single use, proof-recovery and token-signing checks remain.
This patch introduces no new table, schema version, cryptographic algorithm,
activation permission or independently trusted `verified` flag.

## Callers, recovery and deployment

`accept_attestation` is a trusted internal repository API, not a public endpoint.
Only the authenticated verifier composition may supply these times. Merely
constructing the keyword arguments in client JSON authenticates no platform
proof. Production account authorization and the real Android/Apple verifier
remain separate requirements.

Update every direct store caller to forward the original trusted verdict times.
Do not replace them with `now`, extend the broker deadline, fall back to the
challenge expiry, or retry the same stale verdict to make admission pass. The
existing 32 store regressions use explicit inert fixture timestamps; their
assertions are retained. The public `enroll` signature is unchanged.

Database component `identity` remains version 1 and requires no data migration.
Stop/drain old application workers for this code rollout: an unchanged database
marker cannot fence old binaries still using the defective path. This is not a
rolling-upgrade, clock-synchronization or external anti-rollback mechanism.
Already-enrolled devices are not automatically reclassified by this repair;
any investigation of prior affected enrollments needs actual operator evidence.

On a freshness error, do not create a session/token from the rejected result.
Preserve the database and obtain a new genuinely verified proof/verdict through
the trusted flow, while checking the challenge and current account/device state.
If a storage operation fails, no success is acknowledged. The service must handle
storage/clock incidents without deleting tombstones or patching timestamps.

## Verification and limits

Run the existing identity suites and the new enrollment suite, then full repository
checks and all seven current-head CI lanes. The new tests use actual SQLite,
independent connections, lock waiting, write triggers, snapshot mutation checks
and a subprocess exit after rollback. Broker responses are inert fixtures, not
live platform attestation, KMS service or independent acceptance evidence.

The final time sample is a last application-level check before SQLite commit;
it does not make clock sampling and commit physically atomic or prevent arbitrary
scheduler delay, a malicious clock or whole-database restoration. The guarantee
is that a stale verdict observed at either store check is not admitted and both
local writes roll back together. Token issuance semantics are unchanged.

HG-0087 remains OPEN for real KMS/HSM/platform verification, account recovery,
authenticated mobile composition and downstream revocation consumers. The known
review objection requires eligible independent review of the published fix;
implementer tests are not permission to dismiss it or merge the PR.

Primary transaction reference: https://www.sqlite.org/lang_transaction.html
