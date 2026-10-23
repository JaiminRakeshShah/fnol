"""HTTP human-review boundary for Azure.

Exposes pending / approve / reject / audit against the same mock state that
``tools/runtime.py`` uses locally. On Azure, Container Apps Easy Auth must
require the Entra app role Claims.Reviewer before these routes are reachable.
This process never invents approval; it only applies an already-authenticated
reviewer identity from the request.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from tools.runtime import audit, connect  # noqa: E402

REQUIRED_ROLE = "Claims.Reviewer"


def _state_path() -> Path:
    return Path(os.environ.get("FNOL_MOCK_STATE", ROOT / ".state" / "mock.sqlite"))


def _roles_from_headers(headers) -> set[str]:
    """Read roles Easy Auth injects. Local/dev may set X-Fnol-Roles for tests."""
    roles: set[str] = set()
    raw = headers.get("X-Ms-Client-Principal") or headers.get("x-ms-client-principal")
    if raw:
        try:
            import base64

            decoded = json.loads(base64.b64decode(raw + "=="))
            claims = decoded.get("claims") or []
            for claim in claims:
                if isinstance(claim, dict) and claim.get("typ") in {"roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"}:
                    val = claim.get("val")
                    if isinstance(val, str) and val:
                        roles.add(val)
        except Exception:
            pass
    explicit = headers.get("X-Fnol-Roles") or headers.get("x-fnol-roles")
    if explicit:
        roles.update(part.strip() for part in explicit.split(",") if part.strip())
    return roles


def _reviewer_name(headers) -> str:
    for key in (
        "X-Ms-Client-Principal-Name",
        "x-ms-client-principal-name",
        "X-Fnol-Reviewer",
        "x-fnol-reviewer",
    ):
        value = headers.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown-reviewer"


def create_server(host: str = "0.0.0.0", port: int = 8090, state: Path | None = None) -> ThreadingHTTPServer:
    state_path = Path(state) if state is not None else _state_path()
    require_role = os.environ.get("FNOL_REVIEWER_REQUIRE_ROLE", "1").strip() != "0"

    class Handler(BaseHTTPRequestHandler):
        server_version = "fnol-reviewer/1.0"

        def log_message(self, fmt, *args):
            return

        def _json(self, status: int, body):
            raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            if not require_role:
                return True
            return REQUIRED_ROLE in _roles_from_headers(self.headers)

        def do_GET(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/health":
                self._json(200, {"status": "ok", "service": "reviewer"})
                return
            if not self._authorized():
                self._json(403, {"error": "forbidden", "required_role": REQUIRED_ROLE})
                return
            if path == "/v1/pending":
                with connect(state_path) as db:
                    rows = [dict(x) for x in db.execute(
                        "SELECT id, case_id, draft, hash, status, reviewer FROM reviews WHERE status='pending'"
                    )]
                self._json(200, rows)
                return
            if path == "/v1/audit":
                with connect(state_path) as db:
                    rows = [dict(x) for x in db.execute("SELECT * FROM audit ORDER BY seq")]
                self._json(200, rows)
                return
            self._json(404, {"error": "not_found"})

        def do_POST(self):
            path = urlparse(self.path).path.rstrip("/") or "/"
            if not self._authorized():
                self._json(403, {"error": "forbidden", "required_role": REQUIRED_ROLE})
                return
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "v1" and parts[1] in {"approve", "reject"}:
                review_id = parts[2]
                action = parts[1]
                status = "approved" if action == "approve" else "rejected"
                reviewer = _reviewer_name(self.headers)
                with connect(state_path) as db:
                    db.begin_immediate(f"review:{review_id}")
                    row = db.execute(
                        "SELECT id, case_id, draft, hash, status, reviewer FROM reviews WHERE id=?",
                        (review_id,),
                    ).fetchone()
                    if not row or row["status"] != "pending":
                        self._json(409, {"error": "review_not_pending"})
                        return
                    db.execute(
                        "UPDATE reviews SET status=?,reviewer=? WHERE id=?",
                        (status, reviewer, review_id),
                    )
                    audit(
                        db,
                        "human_" + status,
                        row["case_id"],
                        review_id=review_id,
                        reviewer=reviewer,
                        draft_hash=row["hash"],
                    )
                self._json(200, {"status": status, "review_id": review_id, "reviewer": reviewer})
                return
            self._json(404, {"error": "not_found"})

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="FNOL reviewer HTTP boundary")
    parser.add_argument("--host", default=os.environ.get("FNOL_HTTP_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FNOL_HTTP_PORT", "8090")))
    parser.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)
    server = create_server(host=args.host, port=args.port, state=args.state)
    print(f"reviewer HTTP on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
