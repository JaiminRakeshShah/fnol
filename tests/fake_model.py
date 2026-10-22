"""Fake injection-check models for tests: an in-process client and a Foundry-shaped HTTP endpoint."""

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock


class FakeModel:
    """``chat(system, user)`` with a fixed reply, or a raised error. Records each call."""

    model_id = "fake-model"

    def __init__(self, reply="clean", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def chat(self, system, user):
        self.calls.append({"system": system, "user": user})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.reply, input_tokens=10, output_tokens=1, guardrail_action=None)


@contextmanager
def fake_foundry(reply="clean"):
    """Serve the Foundry chat route and point FNOL_MODEL_PROVIDER=azure at it."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            body = json.dumps({
                "choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1},
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        "FNOL_MODEL_PROVIDER": "azure",
        "FNOL_FOUNDRY_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}",
        "FNOL_FOUNDRY_API_KEY": "test-key",
        "FNOL_CONTENT_SAFETY_ENDPOINT": "",
    }
    try:
        with mock.patch.dict(os.environ, env):
            yield env["FNOL_FOUNDRY_ENDPOINT"]
    finally:
        server.shutdown()
        server.server_close()
