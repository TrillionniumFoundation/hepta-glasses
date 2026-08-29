
# Hepta Glasses OS current state

Last updated: 2026-08-30

Baseline before the AI-native foundation package:

- repository: `TrillionniumFoundation/hepta-glasses`
- branch: `main`
- commit: `32178d3cb4ae38c2ef91db05bde836838c274259`
- tree: `f01ea2e305f5c1d54e8328c9028940e28519cb6e`
- upstream import: Even Realities `EvenDemoApp`, recorded in `UPSTREAM.md`
- main branch protection observed disabled at the baseline

## Demonstrated source state

The repository contains a Flutter application with Android and iOS native integrations for:

- left/right G1 BLE transport;
- LC3 audio decoding and RNNoise source;
- speech-recognition event channels;
- microphone start/stop commands;
- text pagination and G1 display packets;
- notification and bitmap transfer;
- a companion UI and local question history.

The AI-native foundation adds source implementations for:

- typed runtime contracts and JSON Schemas;
- canonical JSON and SHA-256 audit digests;
- file-backed and in-memory append-only audit journals;
- recoverable task lifecycle and idempotency;
- risk-tier and decision-lease admission;
- journal-before-effect tool execution and receipts;
- deterministic packet fragmentation and reassembly;
- dual-leg mirrored writes with bounded retry and replay protection;
- a deterministic G1 digital twin with disconnect, timeout, and NACK injection;
- backend model-gateway abstraction and legacy client adapters;
- privacy-safe logging in the current EvenAI flow;
- a safe Codex non-interactive worker launcher;
- a read-only MCP development server;
- CI, repository validation, and negative tests.

## Explicit non-claims

This source state does not prove or claim:

- ownership or modification of the G1 firmware, bootloader, secure boot, or OTA signing path;
- stable operation on a physical G1 device;
- production OpenAI, realtime, OAuth, or model-gateway credentials;
- Android/iOS background-lifecycle closure on production builds;
- production-grade user identity, device attestation, remote revocation, or account recovery;
- public-release privacy, legal, accessibility, safety, or app-store approval;
- a completed soak test, pilot, staged rollout, rollback drill, or public release;
- branch protection, because repository settings cannot be changed by the source package itself.

Those facts remain external evidence items in `GAP_LEDGER.yaml`.

## Current execution authority

Model output is an untrusted proposal. The `ToolGateway` is the source-level execution boundary.
It validates the registered tool, risk tier, authenticated context, decision lease, deadline, and
idempotency fingerprint. Mutating tools append a `tool.prepared` journal record before invoking a
handler. The consumer profile denies R4 tools.

## Current model boundary

The mobile code no longer contains direct DashScope or DeepSeek provider URLs or permanent
provider-key names. Compatibility classes route through `ModelGatewayRegistry`. Development may
use an explicitly configured loopback gateway. Production must inject short-lived runtime tokens
from an identity broker; compile-time development tokens are rejected in product mode.

## Current Codex boundary

The Codex worker source invokes stable non-interactive `codex exec` semantics through a bounded
launcher. It accepts only `read-only` or `workspace-write`, uses an ephemeral session, disables
network by default, rejects paths outside the configured workspace root, caps runtime and output,
and never permits full-access or sandbox-bypass flags. No Codex worker can directly own a G1 BLE
handle or production credential.
