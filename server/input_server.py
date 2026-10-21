"""Stdio MCP server. The only tool is start_ingestion, which creates input.sqlite."""

import json

from fnol_intake.pipeline import start_ingestion
from server.rpc import json_error, serve as serve_rpc, tool_text

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "fnol-input", "version": "1.0.0"}

START_INGESTION = {
    "name": "start_ingestion",
    "description": "Read the mock case list and store one immutable input revision per case.",
    "inputSchema": {"type": "object", "properties": {}},
}


def handle(message):
    if not isinstance(message, dict) or "method" not in message:
        return json_error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
    method = message["method"]
    if "id" not in message:
        return None
    msg_id = message["id"]
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [START_INGESTION]}}
    if method == "tools/call":
        return _call_tool(msg_id, message.get("params") or {})
    return json_error(msg_id, -32601, "method not found")


def _call_tool(msg_id, params):
    if params.get("name") != "start_ingestion":
        return json_error(msg_id, -32602, "unknown tool")
    try:
        summary = start_ingestion()
    except Exception as exc:
        return tool_text(msg_id, f"{exc.__class__.__name__}: {exc}", is_error=True)
    return tool_text(msg_id, json.dumps(summary))


def serve(stdin=None, stdout=None):
    serve_rpc(handle, stdin=stdin, stdout=stdout)
