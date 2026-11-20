"""Loopback client for tinker-service. Only talks to 127.0.0.1; reads the per-install token file."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def default_home() -> Path:
    return Path(os.environ.get("TINKER_HOME", Path.home() / ".tinker"))


class ServiceError(RuntimeError):
    pass


class TinkerClient:
    def __init__(self, port: int = 47615, token_file: str | None = None, timeout: float = 120.0):
        self.base = f"http://127.0.0.1:{int(port)}"
        self.token_file = Path(token_file) if token_file else default_home() / "token"
        self.timeout = timeout

    def _token(self) -> str:
        try:
            return self.token_file.read_text("utf-8").strip()
        except OSError as e:
            raise ServiceError(f"tinker service token not found at {self.token_file}; start the service first") from e

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": "Bearer " + self._token(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("message") or e.reason
            except Exception:
                msg = e.reason
            raise ServiceError(f"tinker service: {e.code} {msg}") from e
        except urllib.error.URLError as e:
            raise ServiceError("tinker service is not running") from e

    def health(self):
        return self._req("GET", "/v1/health")

    def learn(self, scene, demos, name, epochs=600, use_ml=True):
        return self._req("POST", "/v1/learn", {"scene": scene, "demonstrations": demos, "name": name, "epochs": epochs, "use_ml": use_ml})

    def plan(self, scene, skill, object_id, joint, goal_value, sun_dir=None, frames=24):
        body = {"scene": scene, "skill": skill, "object_id": object_id, "joint": joint, "goal_value": goal_value, "frames": frames}
        if sun_dir is not None:
            body["sun_dir"] = sun_dir
        return self._req("POST", "/v1/plan", body)
