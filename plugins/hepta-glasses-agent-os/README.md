# Hepta Glasses Agent OS plugin

The plugin exposes the repository's read-only development MCP adapter. It does not connect Codex
directly to BLE, microphones, user accounts, firmware, signing material, or production release
systems. Complex source tasks are delegated to the isolated worker under `services/codex_worker`;
all physical effects remain outside this plugin and require a separate deterministic authority.

Launch from the repository root so the relative MCP adapter path resolves correctly.
