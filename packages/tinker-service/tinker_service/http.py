"""Authenticated loopback HTTP for hosts (e.g. the Blender add-on) that cannot import PyTorch/MuJoCo.

Security: binds 127.0.0.1 only; per-install bearer token (file mode 0600) compared in constant time;
Host header must be loopback (DNS-rebinding guard); any browser Origin is rejected unless allow-listed; no CORS
headers; JSON only; request size cap; strict contract validation; skill names validated against traversal.
Nothing is sent off the machine."""
from __future__ import annotations

import os
import re
from pathlib import Path

from tw_connector.ipc import MAX_BODY, SecureServer, load_or_create_token

from tw_contracts import ContractError, validate
from tw_scene import find_joint, find_object
from tinker_learning import ModelRegistry
from tinker_learning.pipeline import learn_skill

from .provider import PlanError, TinkerProvider

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class TinkerHTTPServer(SecureServer):
    client_errors = (ContractError, ValueError, KeyError, PlanError)

    def __init__(self, registry_root: Path, token: str, port: int = 0, allowed_origins=()):
        super().__init__(token, port, allowed_origins)
        self.registry = ModelRegistry(registry_root)
        self.provider = TinkerProvider(self.registry)

    def get_routes(self, path: str):
        if path == "/v1/health":
            return {"ok": True, "service": "tinker", "version": "0.1.0"}
        if path == "/v1/skills":
            return {"skills": [self.registry.load_skill(n) for n in self.registry.skills()]}
        return None

    def routes(self, path: str, body: dict):
        if path == "/v1/learn":
            name = body.get("name", "")
            if not isinstance(name, str) or not _NAME.match(name):
                raise ValueError("invalid skill name")
            scene = validate("SceneSnapshot", body["scene"])
            demos = [validate("Demonstration", d) for d in body["demonstrations"]]
            if not demos:
                raise ValueError("no demonstrations")
            use_ml = bool(body.get("use_ml", True))
            res = learn_skill(scene, demos, name=name, registry=self.registry, use_ml=use_ml,
                              epochs=int(min(max(body.get("epochs", 600), 50), 3000)))
            return {"skill": res["skill"], "history": res["history"]}
        if path == "/v1/plan":
            name = body.get("skill", "")
            if not isinstance(name, str) or not _NAME.match(name):
                raise ValueError("invalid skill name")
            scene = validate("SceneSnapshot", body["scene"])
            skill = self.registry.load_skill(name)
            obj = find_object(scene, body["object_id"])
            find_joint(obj, body["joint"])
            sim = self.provider.simulate(skill, scene, object_id=obj["id"], joint=body["joint"],
                                         goal_value=float(body["goal_value"]), sun_dir=body.get("sun_dir"))
            prev = self.provider.preview(sim, frames=int(min(max(body.get("frames", 24), 2), 240))) if sim["id"] in self.provider._sims else {"frames": []}
            return {"simulation": sim, "preview": prev["frames"]}
        return None


def serve(registry_root: Path, token_path: Path, port: int = 0):
    srv = TinkerHTTPServer(Path(registry_root), load_or_create_token(Path(token_path)), port)
    return srv


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="tinker local service (loopback only)")
    home = Path(os.environ.get("TINKER_HOME", Path.home() / ".tinker"))
    ap.add_argument("--registry", default=str(home / "registry"))
    ap.add_argument("--token-file", default=str(home / "token"))
    ap.add_argument("--port", type=int, default=47615)
    a = ap.parse_args(argv)
    srv = serve(Path(a.registry), Path(a.token_file), a.port)
    print(f"tinker-service on http://127.0.0.1:{srv.server_address[1]} (token in {a.token_file})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
