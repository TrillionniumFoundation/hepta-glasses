# Product boundary

## Product definition

Hepta Glasses OS is a distributed AI-native system, not a claim that the current repository is a standalone glasses firmware. It has four planes.

### Glasses device plane

The G1 device supplies microphone input, touch and gesture events, display output, connection and battery state, and firmware-defined protocol behavior. It must not retain model master keys, OAuth refresh tokens, unrestricted shell authority, or a general Codex workspace.

### Edge runtime plane

The companion phone owns device transport, task state, policy, audit, display composition, short-lived capability use, cancellation, and recovery. Flutter is a human interface and event subscriber, not final execution authority. `lib/bootstrap/hepta_bootstrap.dart` is the mobile composition root; production startup remains fail closed while identity-backed mutation authority is unavailable.

### Cloud control plane

The cloud plane owns user identity, device registration, short-lived session issuance, model routing, remote revocation, durable long-running task coordination, rate limiting, and provider secrets. Current Python components are deterministic reference implementations. A development loopback gateway, in-memory registry, or in-memory capability adapter is not a production substitute.

### Codex specialist plane

Codex handles coding-focused diagnosis, patch proposals, protocol work, skill candidates, tests, and other long-horizon engineering tasks inside isolated workspaces. It does not directly mutate the physical device, publish firmware, merge its own changes, read permanent user credentials, or bypass the deterministic Tool Gateway.

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

## Supported current mobile capabilities

The source candidate supports bounded G1 connection and status, assistant display, manual text, bitmap transfer, notification/whitelist protocol paths, heartbeat, microphone admission, LC3 processing, deterministic local policy/audit, and a provider-neutral model-gateway boundary. Platform availability is constrained by `docs/PLATFORM_CAPABILITIES.json`; in particular, Android PCM-to-ASR is unavailable and fails closed.

Cloud identity, realtime, capability, Skills, Memory, qualification, release, MCP, and Codex components are contracts or deterministic reference implementations until their named deployment evidence exists.

## Legacy import exclusions

The imported demo and earlier plans mentioned social-post, OCR, and a separate `hepta_dashboard` surface. Those modules are **not present in the current source authority and are not supported consumer capabilities**. They were deliberately removed from the product boundary rather than represented by placeholder implementations:

- no `social_post_service` exists, and automatic message or social-post sending remains excluded;
- no mobile OCR service exists, and camera/document ingestion is not a current capability;
- no separate `lib/ui/hepta_dashboard.dart` exists; the current presentation entry point is `lib/views/home_page.dart`.

A Gap Ledger row closed as `REMOVED_FROM_PRODUCT_BOUNDARY` means the obsolete requirement was deleted from the supported product, not that the capability was implemented. Reintroducing any of these functions requires a new module entry, schema, data-class and privacy review, risk tier, policy rule, exact approval, receipt/reconciliation contract, tests, documentation, and external evidence where applicable.

## Consumer profile exclusions

The consumer profile does not expose unrestricted shell, arbitrary filesystem access, credential reads, payments, account mutation, automatic message sending, social posting, firmware flashing, or Codex full-access execution. New tools default to unavailable until a registered schema, risk tier, policy rule, test, and receipt contract exist.

## Firmware and release ceiling

This repository does not contain vendor-authorized G1 firmware, bootloader, secure-boot roots, firmware signing, OTA, recovery, or rollback authority. Source and CI evidence cannot establish physical protocol compatibility, production infrastructure, independent assurance, signed binaries, pilot outcomes, store approval, or release authority.
