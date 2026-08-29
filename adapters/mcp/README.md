# Hepta Glasses MCP development adapter

This dependency-free stdio server exposes only three deterministic development tools. It supports
modern discovery and the previous initialization flow so clients can negotiate safely. Every
listed tool is read-only; `display.preview_card` produces a preview and never writes to a physical
G1 device. The adapter does not contain user credentials, model credentials, BLE handles, account
mutation authority, or a hidden shell.
