"""Webhook the reviewer calls after a human decision.

The analyst listens. It does not poll and it does not approve. One POST
copies that decision onto the draft and, for an approval, files the claim.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from fnol_analyst.client import AnalystClient, AnalystError


def advance_case(client: AnalystClient, case_id: str) -> dict[str, Any]:
    """Copy one human decision forward. File only an approval."""
    record = client.stores.output.latest_draft(case_id)
    if record is None:
        return {"case_id": case_id, "error": "draft_missing"}
    if record.status == "in_review" and record.review_id:
        try:
            polled = client.review_status(case_id)
        except AnalystError as exc:
            return {"case_id": case_id, "error": exc.error_code}
        if polled.get("status") != "approved":
            return {"case_id": case_id, "status": polled.get("status"), "filed": False}
    elif not (record.status == "approved" and record.outcome == "approved"):
        return {"case_id": case_id, "status": record.status, "filed": False}
    try:
        filed = client.file(case_id)
    except AnalystError as exc:
        return {"case_id": case_id, "status": "approved", "error": exc.error_code}
    return {"case_id": case_id, "status": filed.get("status", "approved"), "filed": True}


def notify_analyst(case_id: str) -> None:
    """POST the decided case to the analyst. The human decision is already saved."""
    base = os.environ.get("FNOL_ANALYST_URL", "").strip().rstrip("/")
    if not base or not case_id:
        print("analyst webhook skipped: FNOL_ANALYST_URL is unset", flush=True)
        return
    body = json.dumps({"case_id": case_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/v1/reviews/decided",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(response.read().decode("utf-8"), flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"analyst webhook failed: {exc}", flush=True)


def serve(host: str | None = None, port: int | None = None) -> None:
    """Listen for the reviewer webhook until the process is stopped."""
    host = host or os.environ.get("FNOL_HTTP_HOST", "0.0.0.0")
    port = port if port is not None else int(os.environ.get("FNOL_HTTP_PORT", "8080"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/health":
                self._json(200, {"status": "ok", "service": "analyst-follow"})
                return
            self._json(404, {"error": "not_found"})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path != "/v1/reviews/decided":
                self._json(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                case_id = payload["case_id"]
            except (ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "case_id_required"})
                return
            try:
                with AnalystClient() as client:
                    result = advance_case(client, case_id)
            except Exception as exc:
                self._json(500, {"case_id": case_id, "error": str(exc)})
                return
            print(result, flush=True)
            status = 200 if "error" not in result else 409
            self._json(status, result)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"analyst webhook on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
