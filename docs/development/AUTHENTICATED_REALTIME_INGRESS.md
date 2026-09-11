# Authenticated realtime provider ingress

Status: HG-0087/realtime source integration. The repository contains a bounded
fixed-endpoint HTTPS provider adapter and a framework-neutral authenticated
service ingress over the existing durable realtime state machine. This is source
implementation, not evidence that a production provider tenant, credentials,
network boundary or deployment exists.

Implementation:

- `services/control_plane/durable_realtime.py`
- `services/control_plane/authenticated_principals.py`
- `services/model_gateway/realtime_provider.py`
- `services/model_gateway/realtime_ingress.py`

Tests:

- `services/control_plane/test_realtime_custody.py`
- `services/control_plane/test_realtime_admission.py`
- `services/control_plane/test_realtime_recovery_budget.py`
- `services/control_plane/test_realtime_result_custody.py`
- `services/control_plane/test_realtime_provider_binding.py`
- `services/model_gateway/test_realtime_provider.py`
- `services/model_gateway/test_realtime_ingress.py`

## Authority boundary

The client supplies only an account bearer and the narrow operation body. It
cannot choose subject, registered device, active G1 pair, identity session,
audience, scope, provider binding, tenant or provider credential. The unified
principal adapter obtains current access claims from the durable access
authority and, for realtime, requires a fresh server-side active-pair lookup.
The resulting realtime principal binds:

- subject;
- exact active G1 pair identity;
- authenticated identity-session ID;
- audience `hepta-realtime-gateway`;
- scope `realtime.connect`; and
- expiry narrowed to the earlier of access and pair authority.

Pair resolution exceptions, mismatches, inactive state, expiry, authority
outliving access or clock rollback fail closed. No fallback principal or cached
perpetual authority is generated.

The ingress uses the authenticated identity-session ID as the durable realtime
session identity. `issue` accepts exactly an empty JSON object. `activate`
accepts exactly one opaque `ticket`; subject/session/device/provider fields in
the body are rejected before identity or provider work. `reconcile` and
`revoke` again accept only an empty object and address the authenticated session.

## Provider exchange

`HttpsRealtimeProvider` accepts one immutable HTTPS base URL and one persisted
provider/tenant binding. Userinfo, query, fragments, HTTP and non-443 ports are
rejected. Credentials come from an injected runtime token provider and must be
bounded printable bearer bytes. They are not written to SQLite, logs or
responses.

Each method performs exactly one network operation with no application retry:

| Local method | Provider operation | Accepted result |
|---|---|---|
| `activate` | `POST <base>/sessions` | exact bound active-session JSON |
| `reconcile_activation` | `GET <base>/sessions/by-client/<session>` | exact active-session JSON or bounded 404-as-unknown |
| `revoke` | `DELETE <base>/sessions/<provider-session>` | empty 204 or exact bound revoked JSON |

The adapter establishes TLS, invokes a service-owned pre-send authority callback,
and only then emits request bytes. This callback is the composition point for a
fresh identity/session/revocation and provider-policy check. Redirects, unknown
fields, duplicate keys, non-JSON content, wrong session/binding/state, oversized
responses, malformed lengths, invalid tokens and authority exceptions fail with
fixed codes and no upstream detail.

A provider 404 during readback returns `None`; the durable store deliberately
treats absence as uncertainty, not proof that activation never happened. Timeouts
or transport loss after dispatch remain indeterminate and consume the existing
bounded readback/revoke custody. The ingress never converts them into retry-safe
failure.

## State and recovery

The existing durable store remains authoritative for one-time ticket
consumption, generation fencing, exact attempt identity, provider/tenant
binding, monotonic revoke, bounded readback, contradictory-result quarantine and
the cleanup outbox. The new HTTP adapter does not duplicate or bypass that
state.

Operators must process the revoke outbox until authoritative remote termination
is observed. A local `revoked` row is not evidence that a provider stopped a
remote stream. Credential rotation or account/session revoke must also update
the injected token and pre-send authority sources; long-lived provider bytes
already delivered require provider-specific revoke/readback.

## Configuration

Production composition requires:

- a provider base URL under operator configuration, never client input;
- an immutable provider/tenant binding matching the durable database policy;
- a runtime access-token provider backed by the production credential vault;
- a reviewed TLS trust configuration;
- a pre-send authority callback backed by current durable identity and revoke
  state;
- trusted host time, retention and encrypted backup policy; and
- bounded worker, readback and revoke limits from the durable store.

No development token may be compiled into a product build. Missing endpoint,
credential, binding, authority callback or trusted deployment configuration must
leave the realtime surface unavailable.

## Evidence ceiling

Repository tests prove deterministic request shape, exact identity/pair mapping,
TLS-before-authority-before-send ordering, response binding, duplicate/redirect/
size rejection, durable uncertainty and error sanitization. They do not prove a
live provider tenant, actual TLS endpoint ownership, credential revocation,
remote cancellation latency, network egress exclusivity, encrypted operations,
physical Android/iOS/G1 behavior, production observability or independent
acceptance. Those remain authority-owned external evidence.
