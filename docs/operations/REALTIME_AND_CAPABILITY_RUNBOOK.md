# Realtime and capability runbook

## Realtime bootstrap

The mobile client sends a short-lived Hepta access token. The broker verifies subject, device, audience, scopes, expiry, rate limit, and revocation before issuing a one-time bootstrap ticket. A server-side provider adapter exchanges the ticket for a realtime provider session. Provider master credentials never cross into the phone bundle.

## Cancellation and barge-in

Every response belongs to a session generation. Barge-in increments the generation and closes audio output for the prior generation. Transcript, tool, display, and completion events from an older generation are rejected.

## Capability credentials

OAuth refresh tokens remain server-side behind opaque handles. A model can propose a typed operation but cannot select a credential body. Mutations require exact argument digest confirmation and an unexpired Decision Lease. Untrusted content cannot act as confirmation.

## Indeterminate completion

A local timeout does not authorize retry. The adapter first queries the external system by its idempotency key or external ID. It returns an authoritative receipt before another mutation can be admitted.
