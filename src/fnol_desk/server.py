"""HTTP server for the Harborlight FNOL Desk.

Serves static files from ``desk/`` and JSON under ``/api/*``. Accept and reject
update the same mock reviews table as ``tools/runtime.py``.
"""

from __future__ import annotations

import json
import os
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fnol_desk.actions import (  # noqa: E402
    DeskActionError,
    accept_review,
    default_mock_state,
    default_mock_url,
    reject_review,
    send_to_handlers,
)
from fnol_desk.auth import (  # noqa: E402
    COOKIE_NAME,
    AuthError,
    ensure_seeded,
    login,
    logout,
    user_from_session,
    user_public,
)
from fnol_desk.view import case_view, list_audit, list_queue  # noqa: E402
from fnol_foundation.stores import Stores  # noqa: E402

DESK_STATIC = ROOT / "desk"


def _json_bytes(body: object) -> bytes:
    return json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")


def create_server(
    host: str = "127.0.0.1",
    port: int = 8780,
    *,
    state_dir: Path | None = None,
    mock_state: Path | None = None,
    mock_url: str | None = None,
) -> ThreadingHTTPServer:
    auth_path = ensure_seeded(
        (Path(state_dir) / "desk.sqlite") if state_dir is not None else None
    )
    stores = Stores(state_dir) if state_dir is not None else Stores()
    mock_state = Path(mock_state) if mock_state is not None else default_mock_state()
    mock_url = mock_url or default_mock_url()

    class Handler(BaseHTTPRequestHandler):
        server_version = "fnol-desk/1.0"

        def log_message(self, fmt, *args):
            return

        def _set_cors(self):
            # Same-origin only; cookie auth. No broad CORS.
            pass

        def _send(self, status: int, body: object, *, content_type: str = "application/json; charset=utf-8", headers: dict | None = None):
            raw = body if isinstance(body, (bytes, bytearray)) else _json_bytes(body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if headers:
                for key, value in headers.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict:
            size = int(self.headers.get("Content-Length") or "0")
            if size < 0 or size > 65536:
                raise DeskActionError("body_size", "request body too large", 413)
            if size == 0:
                return {}
            raw = self.rfile.read(size)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeskActionError("invalid_json", "body must be a JSON object", 400) from exc
            if not isinstance(body, dict):
                raise DeskActionError("invalid_json", "body must be a JSON object", 400)
            return body

        def _session_token(self) -> str | None:
            raw = self.headers.get("Cookie") or ""
            cookie = SimpleCookie()
            try:
                cookie.load(raw)
            except Exception:
                return None
            morsel = cookie.get(COOKIE_NAME)
            if morsel is None:
                return None
            return morsel.value

        def _current_user(self):
            return user_from_session(self._session_token(), path=auth_path)

        def _require_user(self):
            user = self._current_user()
            if user is None:
                raise AuthError("unauthenticated", "sign in required")
            return user

        def _session_cookie(self, token: str | None, *, clear: bool = False) -> str:
            if clear or not token:
                return (
                    f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
                )
            # 12 hours
            return (
                f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={12 * 3600}"
            )

        def _static(self, rel: str):
            # Prevent path escape
            target = (DESK_STATIC / rel).resolve()
            if not str(target).startswith(str(DESK_STATIC.resolve())):
                self._send(404, {"error": "not_found"})
                return
            if not target.is_file():
                self._send(404, {"error": "not_found"})
                return
            data = target.read_bytes()
            ctype = "application/octet-stream"
            if target.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            elif target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif target.suffix == ".woff2":
                ctype = "font/woff2"
            elif target.suffix == ".svg":
                ctype = "image/svg+xml"
            self._send(200, data, content_type=ctype)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                if path == "/health":
                    self._send(200, {"status": "ok", "service": "fnol-desk"})
                    return
                if path in {"/", "/index.html"}:
                    self._static("index.html")
                    return
                if path.startswith("/fonts/"):
                    self._static(path.lstrip("/"))
                    return
                if path in {"/desk.css", "/desk.js"}:
                    self._static(path.lstrip("/"))
                    return
                if path == "/api/me":
                    user = self._current_user()
                    if user is None:
                        self._send(401, {"error": "unauthenticated"})
                        return
                    self._send(200, {"user": user_public(user)})
                    return
                if path == "/api/queue":
                    user = self._require_user()
                    rows = list_queue(team=user.team, stores=stores, mock_state=mock_state)
                    self._send(200, {"team": user.team, "cases": rows})
                    return
                if path.startswith("/api/cases/"):
                    user = self._require_user()
                    case_id = path[len("/api/cases/") :].strip("/")
                    if not case_id or "/" in case_id:
                        self._send(404, {"error": "not_found"})
                        return
                    view = case_view(
                        case_id, team=user.team, stores=stores, mock_state=mock_state
                    )
                    if view is None:
                        self._send(404, {"error": "not_found", "case_id": case_id})
                        return
                    self._send(200, view)
                    return
                if path == "/api/audit":
                    user = self._require_user()
                    if user.team not in {"security", "handlers", "analysts"}:
                        raise AuthError("forbidden", "cannot read audit")
                    # Security primary; others may read for demo transparency
                    self._send(200, {"events": list_audit(mock_state=mock_state)})
                    return
                self._send(404, {"error": "not_found"})
            except AuthError as exc:
                code = 401 if exc.code == "unauthenticated" else 403
                self._send(code, {"error": exc.code, "message": str(exc)})
            except DeskActionError as exc:
                self._send(exc.http_status, {"error": exc.code, "message": str(exc)})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            try:
                body = self._read_json()
                if path == "/api/login":
                    username = body.get("username")
                    password = body.get("password")
                    user, token = login(
                        str(username or ""),
                        str(password or ""),
                        path=auth_path,
                    )
                    self._send(
                        200,
                        {"user": user_public(user)},
                        headers={"Set-Cookie": self._session_cookie(token)},
                    )
                    return
                if path == "/api/logout":
                    logout(self._session_token(), path=auth_path)
                    self._send(
                        200,
                        {"ok": True},
                        headers={"Set-Cookie": self._session_cookie(None, clear=True)},
                    )
                    return
                if path.startswith("/api/cases/") and path.endswith("/send"):
                    user = self._require_user()
                    case_id = path[len("/api/cases/") : -len("/send")].strip("/")
                    result = send_to_handlers(
                        user,
                        case_id,
                        stores=stores,
                        mock_url=mock_url,
                        mock_state=mock_state,
                    )
                    self._send(200, result)
                    return
                if path.startswith("/api/cases/") and path.endswith("/accept"):
                    user = self._require_user()
                    case_id = path[len("/api/cases/") : -len("/accept")].strip("/")
                    result = accept_review(
                        user, case_id, stores=stores, mock_state=mock_state
                    )
                    self._send(200, result)
                    return
                if path.startswith("/api/cases/") and path.endswith("/reject"):
                    user = self._require_user()
                    case_id = path[len("/api/cases/") : -len("/reject")].strip("/")
                    reason = body.get("reason")
                    result = reject_review(
                        user,
                        case_id,
                        str(reason or ""),
                        stores=stores,
                        mock_state=mock_state,
                    )
                    self._send(200, result)
                    return
                self._send(404, {"error": "not_found"})
            except AuthError as exc:
                code = 401 if exc.code in {"unauthenticated", "invalid_credentials"} else 403
                if exc.code == "invalid_credentials":
                    code = 401
                self._send(code, {"error": exc.code, "message": str(exc)})
            except DeskActionError as exc:
                self._send(exc.http_status, {"error": exc.code, "message": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Harborlight FNOL Desk")
    parser.add_argument("--host", default=os.environ.get("FNOL_DESK_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("FNOL_DESK_PORT", "8780"))
    )
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--mock-state", type=Path, default=None)
    parser.add_argument("--mock-url", default=None)
    args = parser.parse_args(argv)
    ensure_seeded(
        (args.state_dir / "desk.sqlite") if args.state_dir is not None else None
    )
    server = create_server(
        host=args.host,
        port=args.port,
        state_dir=args.state_dir,
        mock_state=args.mock_state,
        mock_url=args.mock_url,
    )
    host, port = server.server_address[:2]
    print(
        f"Harborlight FNOL Desk at http://{host}:{port}/ "
        f"(seeded accounts: achen / jellis / rokonkwo)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
