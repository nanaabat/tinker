"""build the tinker blender extension zip.
usage: python build_blender.py [--blender PATH] [--out dist]"""
from __future__ import annotations

import argparse, os, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_blender(explicit=None):
    for c in [explicit, os.environ.get("BLENDER"), shutil.which("blender")]:
        if c and Path(c).is_file():
            return c
    raise SystemExit("blender not found: set BLENDER or pass --blender")


def stage_tinker(stage: Path, extra: list[Path] = ()) -> Path:
    if stage.exists():
        shutil.rmtree(stage)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "blender/tinker_blender", stage, ignore=ign)
    (stage / "_vendor").mkdir()
    (stage / "_vendor/__init__.py").write_text("")
    shutil.copytree(ROOT / "packages/scene-core/tw_scene", stage / "_vendor/tw_scene", ignore=ign)
    for f in extra:
        shutil.copyfile(f, stage / f.name)
    return stage


def pack(blender, stage: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([blender, "--factory-startup", "--command", "extension", "build",
                        "--source-dir", str(stage), "--output-dir", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    return sorted(out.glob(stage.name + "-*.zip"), key=lambda p: p.stat().st_mtime)[-1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()
    out = Path(a.out)
    print(pack(find_blender(a.blender), stage_tinker(out / "stage/tinker_blender"), out))
