"""Shared local-IPC security for tinker and wink services: loopback-only HTTP, per-install bearer token (0600),
DNS-rebinding Host check, Origin rejection, no CORS, JSON only, body size cap, no tracebacks to clients."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 4 * 1024 * 1024


def load_or_create_token(path: Path) -> str:
    path = Path(path)
    if path.exists():
        return path.read_text("utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


class ClientError(ValueError):
    """Raised by route handlers for 400 responses."""


class SecureHandler(BaseHTTPRequestHandler):
    server_version = "tw-local/0.1"
    sys_version = ""
    client_errors: tuple = (ClientError, ValueError, KeyError)

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: dict):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _guard(self) -> bool:
        srv = self.server
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self._send(403, {"error": "bad host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in srv.allowed_origins:
            self._send(403, {"error": "origin not allowed"})
            return False
        auth = self.headers.get("Authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        if not hmac.compare_digest(tok.encode(), srv.token.encode()):
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_OPTIONS(self):
        self._send(405, {"error": "method not allowed"})

    def do_GET(self):
        if not self._guard():
            return
        try:
            with self.server.lock:
                out = self.server.get_routes(self.path)
        except Exception as e:
            return self._send(500, {"error": "internal", "message": type(e).__name__})
        self._send(200, out) if out is not None else self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._guard():
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._send(415, {"error": "json only"})
        try:
            n = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            n = -1
        if n < 0:
            return self._send(411, {"error": "length required"})
        if n > MAX_BODY:
            return self._send(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ClientError("body must be an object")
            with self.server.lock:
                out = self.server.routes(self.path, body)
        except self.server.client_errors as e:
            return self._send(400, {"error": type(e).__name__, "message": str(e)[:500]})
        except Exception as e:
            return self._send(500, {"error": "internal", "message": type(e).__name__})
        self._send(200, out) if out is not None else self._send(404, {"error": "not found"})


class SecureServer(ThreadingHTTPServer):
    daemon_threads = True
    client_errors: tuple = (ClientError, ValueError, KeyError)

    def __init__(self, token: str, port: int = 0, allowed_origins=()):
        super().__init__(("127.0.0.1", port), SecureHandler)
        self.token = token
        self.allowed_origins = set(allowed_origins)
        self.lock = threading.Lock()

    def get_routes(self, path: str):
        return None

    def routes(self, path: str, body: dict):
        return None
