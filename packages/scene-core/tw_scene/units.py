from __future__ import annotations

import copy

UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}


def convert_length(value: float, src: str, dst: str) -> float:
    if src not in UNIT_TO_M or dst not in UNIT_TO_M:
        raise ValueError(f"unsupported units {src!r} -> {dst!r}")
    return value * UNIT_TO_M[src] / UNIT_TO_M[dst]


def convert_scene(snapshot: dict, dst: str) -> dict:
    """Return a copy of a SceneSnapshot expressed in `dst` units. Angles (revolute joints) are unchanged."""
    src = snapshot["units"]
    f = convert_length(1.0, src, dst)
    s = copy.deepcopy(snapshot)
    s["units"] = dst
    for o in s["objects"]:
        o["pose"]["position"] = [c * f for c in o["pose"]["position"]]
        o["size"] = [c * f for c in o["size"]]
        for j in o["joints"]:
            j["anchor"] = [c * f for c in j["anchor"]]
            if j["kind"] == "prismatic":
                for k in ("lower", "upper", "value", "max_speed"):
                    j[k] = j[k] * f
    for c in s["constraints"]:
        for k in ("min", "max"):
            if k in c:
                c[k] = [v * f for v in c[k]]
    return s
