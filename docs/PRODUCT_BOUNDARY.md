
# Product boundary

## Product definition

Hepta Glasses OS is a distributed AI-native system, not a claim that the current repository is a
standalone glasses firmware. It has four planes.

### Glasses device plane

The G1 device supplies microphone input, touch and gesture events, display output, connection and
battery state, and firmware-defined protocol behavior. It must not retain model master keys,
OAuth refresh tokens, unrestricted shell authority, or a general Codex workspace.

### Edge runtime plane

The companion phone owns device transport, task state, policy, audit, display composition,
short-lived capability use, cancellation, and recovery. Flutter is a human interface and event
subscriber, not final execution authority.

### Cloud control plane

The cloud plane owns user identity, device registration, short-lived session issuance, model
routing, remote revocation, durable long-running task coordination, rate limiting, and provider
secrets. A development loopback gateway is not a production substitute.

### Codex specialist plane

Codex handles coding-focused diagnosis, patch proposals, protocol work, skill candidates, tests,
and other long-horizon engineering tasks inside isolated workspaces. It does not directly mutate
the physical device, publish firmware, merge its own changes, read permanent user credentials, or
bypass the deterministic Tool Gateway.

## Authority matrix

| Capability | Glasses | Flutter UI | Edge runtime | Model | Codex worker | Cloud control |
|---|---:|---:|---:|---:|---:|---:|
| Capture device event | yes | observe | normalize | no | no | no |
| Display card proposal | no | yes | compose/commit | propose | propose | no |
| BLE write | firmware endpoint | no | final authority | no | no | no |
| Tool intent | no | submit | validate | propose | propose | route |
| Permanent provider secret | no | no | no | n/a | no | yes |
| Decision lease issuance | no | request | verify/consume | no | no | yes/local policy |
| Mutation journal | no | observe | yes | no | no | aggregate |
| Firmware publish | no | no | no | no | proposal only | separate release authority |

## Consumer profile exclusions

The consumer profile does not expose unrestricted shell, arbitrary filesystem access, credential
reads, payments, account mutation, automatic message sending, firmware flashing, or Codex
full-access execution. New tools default to unavailable until a registered schema, risk tier,
policy rule, test, and receipt contract exist.
