"""Stdio MCP server. The only tool is start_ingestion, which creates input.sqlite."""

import json
import sys

from server.pipeline import start_ingestion

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "fnol-input", "version": "1.0.0"}

START_INGESTION = {
    "name": "start_ingestion",
    "description": "Start FNOL input ingestion and create input.sqlite, including the duplicates column.",
    "inputSchema": {"type": "object", "properties": {}},
}


def handle(message):
    if not isinstance(message, dict) or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
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
    return _error(msg_id, -32601, "method not found")


def _call_tool(msg_id, params):
    if params.get("name") != "start_ingestion":
        return _error(msg_id, -32602, "unknown tool")
    try:
        summary = start_ingestion()
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": f"{exc.__class__.__name__}: {exc}"}], "isError": True},
        }
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"content": [{"type": "text", "text": json.dumps(summary)}], "isError": False},
    }


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None):
    """Read one JSON-RPC message per line and write one response per line."""
    incoming = sys.stdin if stdin is None else stdin
    outgoing = sys.stdout if stdout is None else stdout
    for line in incoming:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
        else:
            response = handle(message)
        if response is None:
            continue
        outgoing.write(json.dumps(response, ensure_ascii=False) + "\n")
        outgoing.flush()
