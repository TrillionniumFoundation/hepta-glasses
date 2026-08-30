#!/usr/bin/env python3
"""Small dependency-free MCP server for Hepta Glasses development tools."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterator, Mapping

MODERN_PROTOCOL = "2026-07-28"
LEGACY_PROTOCOL = "2025-11-25"
SUPPORTED_PROTOCOLS = (MODERN_PROTOCOL, LEGACY_PROTOCOL)
MAX_REQUEST_BYTES = 64 * 1024
SERVER_INFO = {"name": "hepta-glasses-development", "version": "0.1.0"}


@dataclass(frozen=True)
class RpcError(Exception):
    code: int
    message: str
    data: Any = None


TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "device.get_state",
        "description": "Return the bounded development device-state snapshot.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "task.get_status",
        "description": "Return a development task status by explicit task identifier.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"task_id": {"type": "string", "maxLength": 128}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "display.preview_card",
        "description": "Preview bounded display pages without writing to a physical device.",
        "inputSchema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 128},
                "body": {"type": "string", "maxLength": 2048},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
)


def response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, error: RpcError) -> dict[str, Any]:
    document: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": error.code, "message": error.message},
    }
    if error.data is not None:
        document["error"]["data"] = error.data
    return document


def _params(document: Mapping[str, Any]) -> Mapping[str, Any]:
    params = document.get("params", {})
    if not isinstance(params, Mapping):
        raise RpcError(-32602, "Invalid params")
    return params


def _arguments(params: Mapping[str, Any]) -> Mapping[str, Any]:
    arguments = params.get("arguments", {})
    if not isinstance(arguments, Mapping):
        raise RpcError(-32602, "Invalid tool arguments")
    return arguments


def _text_result(document: Mapping[str, Any]) -> dict[str, Any]:
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": dict(document),
        "isError": False,
    }


def _preview_pages(title: str, body: str) -> list[str]:
    content = "\n".join(part for part in (title.strip(), body.strip()) if part)
    runes = list(content)
    lines = ["".join(runes[index : index + 24]) for index in range(0, len(runes), 24)]
    if not lines:
        lines = [" "]
    return ["\n".join(lines[index : index + 5]) for index in range(0, len(lines), 5)]


def call_tool(name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if name == "device.get_state":
        if arguments:
            raise RpcError(-32602, "device.get_state takes no arguments")
        return _text_result(
            {
                "source": "development-snapshot",
                "physical_device_attached": False,
                "left": "unknown",
                "right": "unknown",
                "mutation_authority": False,
            }
        )
    if name == "task.get_status":
        task_id = arguments.get("task_id")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 128:
            raise RpcError(-32602, "task_id is required")
        if set(arguments) != {"task_id"}:
            raise RpcError(-32602, "Unknown task.get_status arguments")
        return _text_result(
            {
                "task_id": task_id,
                "status": "not_connected_to_runtime",
                "source": "development-adapter",
            }
        )
    if name == "display.preview_card":
        title = arguments.get("title")
        body = arguments.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise RpcError(-32602, "title and body are required")
        if len(title) > 128 or len(body) > 2048:
            raise RpcError(-32602, "display preview input too large")
        if set(arguments) != {"title", "body"}:
            raise RpcError(-32602, "Unknown display.preview_card arguments")
        pages = _preview_pages(title, body)
        return _text_result(
            {
                "pages": pages,
                "page_count": len(pages),
                "physical_device_written": False,
            }
        )
    raise RpcError(-32601, "Unknown tool")


def handle_request(document: Any) -> dict[str, Any] | None:
    if not isinstance(document, Mapping):
        return error_response(None, RpcError(-32600, "Invalid Request"))
    request_id = document.get("id")
    if document.get("jsonrpc") != "2.0" or not isinstance(document.get("method"), str):
        return error_response(request_id, RpcError(-32600, "Invalid Request"))
    method = document["method"]
    if request_id is None:
        # Notifications are accepted without emitting a response.
        return None

    try:
        if method == "server/discover":
            return response(
                request_id,
                {
                    "resultType": "complete",
                    "supportedVersions": list(SUPPORTED_PROTOCOLS),
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                    "instructions": "Read-only development tools; no physical mutation authority.",
                },
            )
        if method == "initialize":
            params = _params(document)
            requested = params.get("protocolVersion")
            if requested is None:
                selected = MODERN_PROTOCOL
            elif requested in SUPPORTED_PROTOCOLS:
                selected = requested
            else:
                raise RpcError(
                    -32602,
                    "Unsupported protocol version",
                    {"supportedVersions": list(SUPPORTED_PROTOCOLS)},
                )
            return response(
                request_id,
                {
                    "protocolVersion": selected,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": "Read-only development tools; no physical mutation authority.",
                },
            )
        if method == "ping":
            return response(request_id, {})
        if method == "tools/list":
            return response(request_id, {"tools": list(TOOLS)})
        if method == "tools/call":
            params = _params(document)
            name = params.get("name")
            if not isinstance(name, str):
                raise RpcError(-32602, "Tool name is required")
            return response(request_id, call_tool(name, _arguments(params)))
        raise RpcError(-32601, "Method not found")
    except RpcError as error:
        return error_response(request_id, error)


def bounded_request_lines(stream: BinaryIO) -> Iterator[bytes | None]:
    """Yield bounded request bytes; ``None`` denotes one discarded oversized line."""

    while True:
        line = stream.readline(MAX_REQUEST_BYTES + 2)
        if not line:
            return
        has_newline = line.endswith(b"\n")
        payload_size = len(line) - (1 if has_newline else 0)
        oversized = payload_size > MAX_REQUEST_BYTES
        if not has_newline and len(line) == MAX_REQUEST_BYTES + 2:
            oversized = True
            while line and not line.endswith(b"\n"):
                line = stream.readline(MAX_REQUEST_BYTES + 2)
        if oversized:
            yield None
            continue
        yield line[:-1] if has_newline else line


def main() -> int:
    for raw_line in bounded_request_lines(sys.stdin.buffer):
        if raw_line is None:
            result = error_response(None, RpcError(-32600, "Request too large"))
        elif not raw_line.strip():
            continue
        else:
            try:
                document = json.loads(raw_line.decode("utf-8"))
                result = handle_request(document)
            except (json.JSONDecodeError, UnicodeDecodeError):
                result = error_response(None, RpcError(-32700, "Parse error"))
            except Exception:
                result = error_response(None, RpcError(-32603, "Internal error"))
        if result is not None:
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
