from __future__ import annotations

import unittest

from adapters.mcp.hepta_glasses_mcp_server import MODERN_PROTOCOL, handle_request


class McpServerTest(unittest.TestCase):
    def test_modern_discovery(self) -> None:
        result = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}
        )
        self.assertIn(MODERN_PROTOCOL, result["result"]["supportedVersions"])

    def test_lists_deterministic_read_only_tools(self) -> None:
        result = handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        names = [tool["name"] for tool in result["result"]["tools"]]
        self.assertEqual(
            names,
            ["device.get_state", "task.get_status", "display.preview_card"],
        )
        self.assertTrue(
            all(tool["annotations"]["readOnlyHint"] for tool in result["result"]["tools"])
        )

    def test_preview_never_claims_physical_write(self) -> None:
        result = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "display.preview_card",
                    "arguments": {"title": "Status", "body": "Ready"},
                },
            }
        )
        structured = result["result"]["structuredContent"]
        self.assertFalse(structured["physical_device_written"])

    def test_unknown_tool_is_rejected(self) -> None:
        result = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "device.write", "arguments": {}},
            }
        )
        self.assertEqual(result["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
