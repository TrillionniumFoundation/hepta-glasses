# Authenticated speech bootstrap, mobile PCM custody and finality

Status: HG-0087 speech **source-integrated / external-blocked**. The repository
implements the server custody, authenticated ingress, Flutter admission boundary,
Android decoded-PCM path and cross-platform final/cancel semantics. Live provider,
production identity, physical-device and independent evidence remain outside
source authority. Aggregate HG-0087 remains OPEN.

Primary implementation:

- `services/model_gateway/speech.py`
- `services/model_gateway/speech_ingress.py`
- `lib/runtime/model_gateway.dart`
- `lib/services/evenai.dart`
- `android/app/src/main/kotlin/com/example/demo_ai_even/speech/AndroidPcmAsr.kt`
- `android/app/src/main/kotlin/com/example/demo_ai_even/speech/AndroidSpeechSession.kt`
- `android/app/src/main/kotlin/com/example/demo_ai_even/bluetooth/BleManager.kt`
- `ios/Runner/SpeechStreamRecognizer.swift`

Contract: `contracts/realtime-speech-custody-v2.json`. Operations:
`docs/operations/SPEECH_BOOTSTRAP_RUNBOOK.md`.

## Authority domains

Speech uses two separate generations and they must never be collapsed:

```text
assistant authority = (subject, session_id, assistant_generation)
device audio authority = (pair_identity, BLE connection_generation, side)
complete mobile speech authority = both domains + locale + absolute expiry
```

The server stores `SHA-256(pair_identity)` rather than the raw pair value. The
provider mint request binds subject, session, assistant generation, pair digest,
locale, audio format, maximum audio bytes and absolute expiry. The Android ticket
carries the assistant generation and the captured BLE connection generation
separately. A reconnect cannot lend old PCM to a new connection, and a new
assistant session cannot adopt an old provider result.

## Authenticated ingress

`SpeechBootstrapIngress` receives the raw Authorization header and bounded JSON
body from a trusted framework adapter. Its injected identity verifier returns a
`SpeechPrincipal` containing subject, session ID, pair identity, audience and
scopes based on current server-side identity/session/revocation state.

The client body contains only session ID, assistant generation, pair identity and
locale. Body session/pair must exactly match the principal; the subject, audience
and `speech.bootstrap` scope never come from client JSON. Duplicate members,
unknown fields, booleans used as numbers, malformed UTF-8, oversized bodies,
malformed principals and authentication exceptions fail before provider mint.
Upstream exception text and bearer material are not reflected.

The successful route calls `bootstrap_for_delivery`, which persists the issued
bootstrap as `consumed` before returning provider material. A lost HTTP response
therefore cannot make another mint safe. The same session ID cannot mint again in
`minting`, `indeterminate`, `issued`, `consumed` or `revoked` state. Recovery must
revoke/investigate the old session and create a newly authenticated session; it
must not replay the old request.

## Durable server state

SQLite WAL/FULL and `BEGIN IMMEDIATE` protect quota, reservation, session state
and revocation across local connections. A bootstrap is reserved as `minting`
before broker work and charges the UTC-day subject quota. Broker failure or an
invalid ticket after reservation becomes `indeterminate`; provider work is never
silently repeated.

A valid `ProviderSpeechTicket` requires:

- exact configured provider binding;
- HTTPS with hostname, no URL credentials/query/fragment and port 443/default;
- bounded printable bearer token;
- bounded provider ticket ID and maximum PCM bytes;
- expiry after current trusted host time and no later than requested expiry.

After broker return the gateway reacquires the write transaction and rechecks
reservation identity, local revocation, provider binding and expiry. A revoke
that races with mint leaves local state revoked and triggers another idempotent
remote revoke because the earlier remote call may have preceded ticket creation.
A failed second revoke returns `speech_remote_revoke_pending`; it never restores
local authority or claims remote deletion.

## Flutter and native admission

Flutter captures one authoritative `BleConnectionSnapshot` before starting the
assistant. Android first obtains an authenticated `SpeechBootstrap`; immediately
before native start it rechecks that BLE generation, pair identity and both-leg
readiness are unchanged. The MethodChannel call carries both generations, pair,
session, locale, endpoint, token, expiry and audio limit. Product builds reject a
compiled development speech token and remain unavailable until a runtime token
provider and gateway are composed.

Android native admission independently checks the ticket BLE generation and pair
against the selected ready G1 pair. `AndroidSpeechSession` owns one active
recognizer, serializes final provider work off the GATT/UI threads and fences late
completion with an internal epoch. Disconnect, reconnect, a newer start or cancel
invalidates the old session.

Only right-leg microphone frames with the exact expected G1 frame size are
decoded. The decoded PCM is delivered only after another generation/pair recheck.
No raw audio, provider token or transcript is persisted by this path.

## Provider final response

The Android HTTPS adapter sends one bounded PCM request with exact authority
headers and follows no redirects. It reads a bounded JSON response using strict
UTF-8 and a dependency-free exact parser. The final document must contain exactly:

```text
session_id
generation
connection_generation
pair_identity
is_final
transcript
```

Duplicate/unknown fields, partial results, wrong session, stale assistant or BLE
generation, wrong pair, empty/oversized transcript, invalid UTF-8, redirects,
wrong content type and oversized body fail closed. Only a positively bound final
transcript reaches the Flutter event channel.

## Cross-platform finality and cancellation

Normal stop requests finalization; cancellation is a distinct operation. Android
cancellation clears buffered PCM and fences any worker result. iOS cancellation
ends/cancels the system recognition task without emitting a fabricated final
transcript. On iOS only a framework-final result is delivered as final text;
timeout/error partials are discarded. Flutter accepts only a final event matching
the current assistant generation.

Cancellation prevents later admission and delivery but cannot prove deletion or
remote termination after bytes have already left the device. Provider revoke and
readback require their own authoritative receipts.

## Failure and recovery

| Failure | Durable/local result | Continuation |
|---|---|---|
| Identity/body mismatch | No mint | Reauthenticate; do not rewrite body authority |
| Broker timeout after reservation | `indeterminate` | Provider investigation and session revoke only |
| Lost bootstrap response | `consumed` | Do not remint; revoke/recover with a new session |
| BLE authority changes before start | Native start denied | Obtain a new bootstrap for a new assistant session |
| Disconnect during PCM | Session cancelled and late PCM fenced | Reconnect, then create a new authenticated session |
| Provider final binding invalid | No transcript delivered | Investigate provider; do not relabel partial data |
| Cancel during finalization | Late output withheld | Preserve cancellation; remote state remains separate |
| Storage failure | No success acknowledgement | Preserve database; fail service admission |

`pending_recovery()` includes unresolved `minting`, `indeterminate` and `issued`
sessions. It is an authenticated operator inventory, not a background retry or a
remote receipt. The current source does not yet install a durable remote revoke
outbox, encrypted database volume, whole-file anti-rollback anchor or provider
readback adapter.

## Configuration and migration

Ingress request size is 4 KiB. Provider response is 32 KiB and transcript 8 KiB.
Maximum bootstrap TTL is 300 seconds. Default PCM allowance is 960,000 bytes;
configured bounds are 3,200..16,000,000. Provider timeout is finite and at most
60 seconds. Subject daily issuance is bounded.

Do not run old and new binaries against one database. Existing unauthenticated or
unversioned speech state is not automatically promoted. Stop/drain old workers,
preserve unresolved and revoked rows, and use a reviewed migration. Never delete
consumed/revoked state or restore an older snapshot to make a session reusable.

## Verification and evidence ceiling

Required source regressions include server revoke/mint races, one-shot delivery,
quota concurrency, unknown outcome, provider binding, authenticated ingress,
malformed JSON/principal, mobile bootstrap binding/expiry, Android exact response
binding, stale BLE/assistant generations and iOS final/cancel behavior. Run the
complete seven-lane exact-head repository workflow after any change.

These tests use fixture identity and provider implementations. They do not prove
a live speech tenant, KMS/HSM/attestation deployment, remote revoke/readback,
provider retention/deletion, physical G1 latency/accuracy/locale/privacy/power,
independent acceptance or release. Those remain external/provider/product gates.
