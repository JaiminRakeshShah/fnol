"""Stdio MCP server for Step 3. Tool: start_routing."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fnol_rules.pipeline import start_routing

PROTOCOL = "2024-11-05"
SERVER_INFO = {"name": "fnol-rules", "version": "1.0.0"}

START_ROUTING = {
    "name": "start_routing",
    "description": (
        "Fetch claims (≤3 attempts), store canonical claims JSON in input.sqlite, "
        "and route cases with AUTO-TRIAGE-01. Requires intake revisions. "
        "Pass selected_policy_version from Step 2."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "case_id": {
                "type": "string",
                "description": "Optional. Omit to route all cases with a latest input revision.",
            },
            "selected_policy_version": {
                "type": ["string", "null"],
                "description": "Policy version from Step 2. null forces manual_review.",
            },
            "policy_available": {
                "type": "boolean",
                "description": "False when policy service was unavailable (Step 2).",
                "default": True,
            },
        },
    },
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
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [START_ROUTING]}}
    if method == "tools/call":
        return _call_tool(msg_id, message.get("params") or {})
    return _error(msg_id, -32601, "method not found")


def _call_tool(msg_id, params):
    if params.get("name") != "start_routing":
        return _error(msg_id, -32602, "unknown tool")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _error(msg_id, -32602, "arguments must be an object")
    try:
        summary = start_routing(
            case_id=args.get("case_id"),
            selected_policy_version=args.get("selected_policy_version"),
            policy_available=bool(args["policy_available"]) if "policy_available" in args else True,
        )
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": f"{exc.__class__.__name__}: {exc}"}],
                "isError": True,
            },
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


if __name__ == "__main__":
    serve()
