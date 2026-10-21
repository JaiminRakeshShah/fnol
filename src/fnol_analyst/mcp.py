"""Minimal stdio MCP client for one FNOL step server.

Calls on the same server are serialized with a lock: one request line, one
response line. Different servers are separate processes and can run at once.
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any


class ServerError(RuntimeError):
    def __init__(self, server: str, tool: str, message: str):
        super().__init__(f"{server}.{tool}: {message}")
        self.server = server
        self.tool = tool


class StdioServer:
    def __init__(self, name: str, command: list[str], *, cwd=None, env=None):
        self.name = name
        self._lock = threading.Lock()
        self._next_id = 0
        self._proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        info = self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
        self.server_info = info.get("serverInfo", {})

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
            if params is not None:
                message["params"] = params
            assert self._proc.stdin is not None and self._proc.stdout is not None
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        if not line:
            raise ServerError(self.name, method, "server closed its output")
        response = json.loads(line)
        if response.get("id") != msg_id:
            raise ServerError(self.name, method, "response id did not match request")
        if "error" in response:
            raise ServerError(self.name, method, str(response["error"].get("message")))
        return response.get("result") or {}

    def list_tools(self) -> list[str]:
        return [tool["name"] for tool in self._request("tools/list").get("tools", [])]

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one tool and return its JSON summary. A tool error is raised."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        text = "".join(
            part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
        )
        if result.get("isError"):
            raise ServerError(self.name, tool, text)
        try:
            summary = json.loads(text)
        except json.JSONDecodeError:
            raise ServerError(self.name, tool, "tool returned non-JSON text") from None
        if not isinstance(summary, dict):
            raise ServerError(self.name, tool, "tool summary was not an object")
        return summary

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
                self._proc.wait()
