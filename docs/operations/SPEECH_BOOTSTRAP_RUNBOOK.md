# Speech bootstrap operations runbook

Owner: mobile-ai/cloud. Source: `services/model_gateway/speech.py`.
Design: `docs/development/SPEECH_BOOTSTRAP_CUSTODY.md`.
HG-0087 speech remains OPEN.

## Deployment

Stop and drain every old process before deploying this API change. Construct the
gateway with a trusted host clock and the reviewed `provider_binding`; do not
re-create the former caller-supplied `now` behavior through request data or a
closure over client timestamps. Confirm the broker implementation exposes the
expected tenant binding when available.

The current speech database does not have an externally anchored schema or
anti-rollback version. Preserve the SQLite file and WAL journals. Do not delete
`minting`, `indeterminate` or revoked rows to make startup or quota checks pass.
This release does not claim rolling mixed-version safety.

## Normal bootstrap

Authenticate subject/session/generation and paired-device identity before calling
the gateway. `bootstrap` reserves quota and custody locally before broker work.
Only an `issued` result returned by the function may be delivered to the intended
speech transport. Never log or persist the returned bearer token.

A broker response must match the configured provider binding and original expiry
and audio-size envelope. Treat `speech_provider_ticket_invalid`, clock errors and
binding mismatch as denial; do not modify expiry or retry mint under a new
bootstrap ID to make the request pass.

## Revocation and races

`revoke_session` first commits local denial, then calls the broker. The broker
revoke operation must be idempotent. A bootstrap that finishes minting after a
concurrent revoke performs another remote revoke before returning an error, since
the first revoke may have run before the late ticket existed.

`speech_remote_revoke_pending` means local state is denied but remote deletion is
not confirmed. Retry only through the authorized session-revocation procedure;
do not report it as successful remote cancellation and do not re-enable the
bootstrap. Genuine provider evidence is required for a remote-cleanup claim.

## Crash and unknown mint outcome

Use `pending_recovery()` through an authenticated operator surface. `minting` or
`indeterminate` means the broker outcome is unknown or incomplete. The gateway
will not mint another ticket for that same session while such custody exists.
The safe repository-level action is session denial/revocation plus provider-side
investigation; there is no automatic readback or background retry in this slice.

If storage is unavailable or a transaction fails, do not acknowledge a successful
bootstrap or revoke. Preserve the original database for investigation. Whole-file
snapshot rollback, encryption and durable remote revoke outbox/retry are not
provided here.

## Validation

Run at minimum:

```bash
python3 -m unittest services.model_gateway.test_speech_custody -v
python3 -m compileall -q services/model_gateway
```

On the final unchanged repository head also require the canonical repository,
service, adapter, Flutter, Android, iOS, sanitizer, boundary-scan and source-
evidence jobs defined by the repository plan. Local fixture-broker tests are not
live ASR/provider, physical-device or independent product evidence.

## Remaining production work

Still required: Android PCM-to-ASR, live broker/provider readback, authenticated
mobile/session integration, real tenant credentials, stream finality/privacy,
retention and deletion policy, durable remote revoke recovery, operational
observability, device/locale/latency/accuracy qualification and independent
acceptance. Do not mark the aggregate speech or HG-0087 row CLOSED from this
bootstrap-custody repair alone.
