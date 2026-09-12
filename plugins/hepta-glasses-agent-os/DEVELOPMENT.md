# Agent OS plugin: development and operational boundary

Owner: developer-platform. Lifecycle: development_reference. Registry:
`docs/MODULE_COVERAGE.json`, module `agent-os-plugin`. This plugin is now owned
separately from the MCP server it launches; it does not grant production access.

## Responsibility and non-responsibility

The plugin packages `.codex-plugin/plugin.json` and `.mcp.json`. The latter
starts `python3 adapters/mcp/hepta_glasses_mcp_server.py` with unbuffered output.
It supplies discovery and read-only development tools, not a live mobile runtime.
The process has no authorized BLE, microphone, account, firmware, signing or
release interface. Never add user/provider credentials to the configuration.

## Interfaces and data flow

Host plugin loader -> MCP configuration -> Python stdio server -> bounded
JSON-RPC request -> deterministic tool -> JSON response on stdout. Resolve the
relative executable argument from the repository root, not the plugin directory.
Python and the repository working directory are operator-controlled prerequisites.
No shell command interpolation is used in the configuration.

| Tool | Arguments | Result and authority ceiling |
|---|---|---|
| `device.get_state` | Empty object only | Development snapshot, both sides unknown, physical device absent, mutation authority false |
| `task.get_status` | Nonempty `task_id`, at most 128 characters | `not_connected_to_runtime`; not a durable task-service query |
| `display.preview_card` | `title` <=128, `body` <=2048 characters; exact fields | Deterministic pages and count, `physical_device_written=false` |

The implementation declares protocol versions `2026-07-28` and `2025-11-25`;
these are source declarations, not independently verified host compatibility.
Requests are limited to 64 KiB. Preview wraps by Unicode code points into 24-code-
point lines and five-line pages; it is not pixel/font or firmware layout proof.

## Lifecycle and concurrency

The host starts one server process and owns its stdin/stdout pipes. Initialization,
capability discovery and calls are protocol requests. The server processes its
bounded input stream; there is no background device session, provider connection,
credential refresh or persistent user state. Terminating the process stops this
development adapter, not an external action. Stdout must contain only protocol
messages. Use redacted stderr for any future diagnostics.

## Failure semantics

Missing Python, wrong working directory or missing adapter file: process startup
fails; repair the host configuration rather than installing a privileged bridge.
Unknown methods/tools and invalid parameters return bounded JSON-RPC errors;
unknown fields must not expand capabilities. Malformed/oversized input must not
be reinterpreted as a tool call. A timeout is not evidence of a physical effect
because no physical effect path exists in this profile. A future mutating profile
requires a new contract, not a change to a read-only annotation alone.

## Local verification

From the repository root:

```bash
python3 -m unittest discover -s adapters -p 'test_*.py'
python3 -m unittest services.qualification.test_source_coverage
python3 tools/validate_source_coverage.py
python3 adapters/mcp/hepta_glasses_mcp_server.py
```

For a manual stdio smoke check, send an `initialize` request, then `tools/list`
and a `tools/call` for `device.get_state`. Confirm the returned tool list matches
this document and the response denies physical-device authority. Do not use
production account data in the smoke check. Host plugin install/uninstall and
cross-version compatibility must be witnessed separately.

## Change and rollback contract

Change the manifest/configuration, server contract, tests and this guide together.
Retain a reviewed previous plugin package to roll back host installation. A
server-path change requires a launch test from a clean repository checkout.
A new tool must have exact input/output validation, negative tests, owner and
privacy classification. A mutating tool additionally requires authenticated
identity, deterministic leases, durable audit, receipts and reconciliation;
that is outside this development profile. No self-merge or release authority is
provided by this plugin.
