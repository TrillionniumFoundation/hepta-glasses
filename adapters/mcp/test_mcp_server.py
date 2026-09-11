from __future__ import annotations

import io
import unittest

from adapters.mcp.hepta_glasses_mcp_server import (
    LEGACY_PROTOCOL,
    MAX_REQUEST_BYTES,
    MODERN_PROTOCOL,
    bounded_request_lines,
    handle_request,
)


class McpServerTest(unittest.TestCase):
    def test_modern_discovery(self) -> None:
        result = handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}}
        )
        self.assertIn(MODERN_PROTOCOL, result["result"]["supportedVersions"])

    def test_initialization_honors_supported_versions_and_defaults_modern(self) -> None:
        for requested in (MODERN_PROTOCOL, LEGACY_PROTOCOL):
            with self.subTest(requested=requested):
                result = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 10,
                        "method": "initialize",
                        "params": {"protocolVersion": requested},
                    }
                )
                self.assertEqual(result["result"]["protocolVersion"], requested)
        defaulted = handle_request(
            {"jsonrpc": "2.0", "id": 11, "method": "initialize", "params": {}}
        )
        self.assertEqual(defaulted["result"]["protocolVersion"], MODERN_PROTOCOL)

    def test_initialization_rejects_unknown_protocol(self) -> None:
        result = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            }
        )
        self.assertEqual(result["error"]["code"], -32602)
        self.assertEqual(
            result["error"]["data"]["supportedVersions"],
            [MODERN_PROTOCOL, LEGACY_PROTOCOL],
        )

    def test_request_reader_discards_oversized_line_without_unbounded_read(self) -> None:
        oversized = b"x" * (MAX_REQUEST_BYTES + 1) + b"\n"
        valid = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        self.assertEqual(
            list(bounded_request_lines(io.BytesIO(oversized + valid))),
            [None, valid[:-1]],
        )

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
