"""Versioned on-disk model registry with an active pointer and rollback. Path traversal safe."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class RegistryError(ValueError):
    pass


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _skill_dir(self, name: str) -> Path:
        if not _NAME.match(name):
            raise RegistryError(f"invalid skill name {name!r}")
        return self.root / name

    def resolve(self, rel: str, expect_sha256: str | None = None) -> Path:
        if not isinstance(rel, str) or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/") or "\\" in rel:
            raise RegistryError(f"unsafe registry path {rel!r}")
        p = (self.root / rel).resolve()
        if os.path.commonpath([str(p), str(self.root)]) != str(self.root):
            raise RegistryError(f"path escapes registry: {rel!r}")
        if not p.is_file():
            raise RegistryError(f"missing model file {rel!r}")
        if expect_sha256 and sha256_file(p) != expect_sha256:
            raise RegistryError(f"checksum mismatch for {rel!r}")
        return p

    def versions(self, name: str) -> list[int]:
        d = self._skill_dir(name)
        if not d.exists():
            return []
        return sorted(int(x.name[1:]) for x in d.iterdir() if x.is_dir() and re.fullmatch(r"v\d+", x.name))

    def register(self, name: str, skill: dict, files: dict[str, Path], *, activate: bool = True) -> int:
        d = self._skill_dir(name)
        v = (self.versions(name) or [0])[-1] + 1
        vd = d / f"v{v}"
        vd.mkdir(parents=True, exist_ok=False)
        for fname, src in files.items():
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", fname) or fname.startswith("."):
                raise RegistryError(f"invalid file name {fname!r}")
            shutil.copyfile(src, vd / fname)
        skill = json.loads(json.dumps(skill))
        skill["version"] = v
        if "model.onnx" in files:
            skill["model_ref"]["path"] = f"{name}/v{v}/model.onnx"
            skill["model_ref"]["sha256"] = sha256_file(vd / "model.onnx")
        (vd / "skill.json").write_text(json.dumps(skill, indent=2), "utf-8")
        if activate:
            self.activate(name, v)
        return v

    def activate(self, name: str, version: int):
        d = self._skill_dir(name)
        if version not in self.versions(name):
            raise RegistryError(f"{name} has no version {version}")
        tmp = d / "ACTIVE.tmp"
        tmp.write_text(str(version), "utf-8")
        os.replace(tmp, d / "ACTIVE")  # atomic: crash-safe pointer swap

    def active_version(self, name: str) -> int | None:
        p = self._skill_dir(name) / "ACTIVE"
        return int(p.read_text("utf-8")) if p.exists() else None

    def rollback(self, name: str) -> int:
        cur = self.active_version(name)
        older = [v for v in self.versions(name) if cur is None or v < cur]
        if not older:
            raise RegistryError(f"{name} has no earlier version to roll back to")
        self.activate(name, older[-1])
        return older[-1]

    def load_skill(self, name: str, version: int | None = None) -> dict:
        v = version or self.active_version(name)
        if v is None:
            raise RegistryError(f"{name} has no active version")
        return json.loads((self._skill_dir(name) / f"v{v}" / "skill.json").read_text("utf-8"))

    def skills(self) -> list[str]:
        return sorted(x.name for x in self.root.iterdir() if x.is_dir() and _NAME.match(x.name) and (x / "ACTIVE").exists())
