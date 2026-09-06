# Authenticated speech bootstrap and mobile ASR runbook

Owner: mobile-ai/cloud. Source-integrated; external deployment and product
qualification remain blocked. Design:
`docs/development/SPEECH_BOOTSTRAP_CUSTODY.md`. Contract:
`contracts/realtime-speech-custody-v2.json`.

## Deployment prerequisites

Do not expose `SpeechBootstrapIngress` until the injected identity verifier uses
current durable subject/device/session/revocation state and enforces audience
`hepta-speech-bootstrap` plus scope `speech.bootstrap`. A client-supplied subject,
verified flag, session claim or pair claim is never authority.

Configure one reviewed provider binding and a trusted host UTC clock. The broker
must bind mint requests to subject, session ID, assistant generation, pair digest,
locale, PCM format, audio limit and absolute expiry. Provider credentials and the
returned short-lived bearer token must not enter source, mobile build defines,
ordinary logs, SQLite or long-term telemetry.

Stop and drain every old process before deploying the server or mobile API
change. Preserve the SQLite file and WAL. Do not delete `minting`,
`indeterminate`, `issued`, `consumed` or revoked rows to make a session reusable.
Do not restore a snapshot predating revocation or consumption. Mixed-version
operation is unsupported.

The product mobile build remains fail-closed without a runtime speech-bootstrap
URL and authenticated token provider. Compiled development speech tokens are
rejected in product mode. A source-configured endpoint is not evidence of a live
provider tenant.

## Normal flow

1. Authenticate the account/device/session and obtain current pair identity from
   the server-owned session record.
2. Accept a bounded request body containing only session ID, assistant generation,
   pair identity and locale.
3. Verify body session/pair exactly match the server principal before provider
   work.
4. Call `bootstrap_for_delivery`; it reserves quota before mint, validates the
   exact provider ticket and commits `consumed` before returning it.
5. The mobile client validates session, assistant generation, pair, locale,
   HTTPS endpoint, expiry and audio limit.
6. Flutter rechecks the captured BLE connection generation and pair immediately
   before `startEvenAI`.
7. Android native admission checks both generations and the selected ready pair.
8. G1 right-leg LC3 frames are decoded and streamed into that exact session.
9. Normal stop finalizes; cancel clears/fences the session without fabricating a
   transcript.
10. Accept only an exact provider final response bound to session, assistant
    generation, BLE generation and pair.

Never retry a lost successful bootstrap response under the same session ID. The
server has already consumed it. Revoke/investigate the old session and create a
new authenticated assistant session only after the current policy permits it.

## Provider transport contract

The Android endpoint must use HTTPS with no URL credentials, query, fragment,
redirect or non-443 port. The response must be `application/json`, bounded to
32 KiB and strict UTF-8. It contains exactly:

```json
{
  "session_id": "opaque-session",
  "generation": 1,
  "connection_generation": 1,
  "pair_identity": "Pair_7",
  "is_final": true,
  "transcript": "bounded final text"
}
```

Duplicate/unknown fields, stale binding, partial output, malformed JSON, empty
transcript, oversized body or wrong content type are terminal denial for that
result. Do not forward provider error bodies or partial text to the user as a
final transcript.

The provider must treat revoke as idempotent and expose authoritative readback or
receipts before deployment acceptance. The current repository source does not
implement that provider-side control plane.

## Cancellation, disconnect and races

A normal recording stop requests finalization. User cancellation, barge-in,
connection loss, a newer assistant session or teardown calls the cancellation
path. Android clears buffered PCM and fences worker output; iOS ends/cancels the
system recognition task without emitting a fabricated final event.

If BLE connection generation or pair identity changes after bootstrap issuance,
start is denied and the ticket must not be reused. If the connection changes
during recording, native disconnect cancels the session and stale PCM is dropped.
Cancellation after request bytes have left the device does not prove remote
termination, deletion or refund.

`revoke_session` commits local denial before the remote call. A ticket that
finishes minting after a concurrent revoke remains locally revoked and triggers a
second idempotent remote revoke. `speech_remote_revoke_pending` means local denial
is durable but remote cleanup is unconfirmed.

## Crash and unknown outcome

Use `pending_recovery()` only through authenticated operator access. `minting` or
`indeterminate` means provider mint may or may not have occurred. `issued` means
provider material existed but client delivery/consumption did not complete under
the safe delivery helper. None of these states permits automatic remint.

For each unresolved session:

1. block new bootstrap under the same session ID;
2. inspect provider-authoritative state using protected operator credentials;
3. commit local session revoke;
4. perform idempotent remote revoke;
5. retain provider receipt/digest without token or transcript content;
6. open a fresh assistant session only after current identity and policy checks.

Storage failure is fail-closed. Preserve the original database and WAL. The
current component has no automatic background worker, encrypted metadata volume,
trusted anti-rollback anchor or durable remote revoke outbox; production must add
and exercise them.

## Privacy and observability

Permitted operational fields are opaque session IDs, generation numbers, pair
hashes, provider-binding ID, safe reason code, byte counts, duration buckets and
state transitions. Do not log bearer tokens, authorization headers, endpoint
credentials, raw PCM, transcripts, provider response bodies or personal pair
identifiers.

Set alerts for quota exhaustion, clock failure, provider-binding mismatch,
indeterminate/issued recovery backlog, remote revoke pending, final-response
binding failure, repeated BLE generation churn and speech finalization timeout.
An alert is not an authoritative provider receipt.

## Validation

Run at minimum:

```bash
python3 -m unittest \
  services.model_gateway.test_speech_custody \
  services.model_gateway.test_speech_ingress -v
python3 -m compileall -q services/model_gateway
flutter test test/runtime/model_gateway_test.dart \
  test/runtime/ios_speech_finalization_contract_test.dart
cd android && ./gradlew testDebugUnitTest
```

On the final unchanged head require all seven canonical jobs non-empty and
successful, then independently verify the exact-head source artifact. Source
fixtures and simulator builds are not live provider or physical-device evidence.

## External acceptance still required

Before enabling a production profile, obtain and authenticate:

- live speech-provider tenant and exact endpoint/model/locale configuration;
- KMS/HSM-backed service identity and Android/Apple attestation integration;
- provider mint, revoke, timeout and readback receipts;
- encrypted metadata/backup policy and anti-rollback controls;
- physical Android/iOS + G1 latency, accuracy, cancellation, locale, privacy,
  power, thermal and soak reports;
- independent security/privacy review and release acceptance.

Do not mark the product or aggregate HG-0087 complete from source integration or
CI alone.
