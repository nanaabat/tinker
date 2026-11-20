"""Right-handed Y-up (e.g. glTF, some OBJ exports) <-> right-handed Z-up (Rhino, Blender)."""
from __future__ import annotations

import copy
import math

from .quat import qaxis, qconj, qmul

# Rotating the frame +90 deg about X maps Y-up to Z-up: (x, y, z) -> (x, -z, y)
_R = qaxis([1.0, 0.0, 0.0], math.pi / 2)


def y_up_to_z_up_vec(v):
    return [v[0], -v[2], v[1]]


def z_up_to_y_up_vec(v):
    return [v[0], v[2], -v[1]]


def _q(q, inverse=False):
    # change of world frame only: local geometry (sizes, joint axes, anchors) keeps its meaning
    r = qconj(_R) if inverse else _R
    return qmul(r, q)


def convert_axes(snapshot: dict, up: str) -> dict:
    s = copy.deepcopy(snapshot)
    cur = s["coordinate_system"]["up"]
    if cur == up:
        return s
    to_z = up == "z"
    vec = y_up_to_z_up_vec if to_z else z_up_to_y_up_vec
    for o in s["objects"]:
        o["pose"]["position"] = vec(o["pose"]["position"])
        o["pose"]["rotation"] = _q(o["pose"]["rotation"], inverse=not to_z)
        # sizes are local extents and joint axes/anchors are in the object's local frame: unchanged
    for c in s["constraints"]:
        if "min" in c and "max" in c:
            a, b = vec(c["min"]), vec(c["max"])
            c["min"] = [min(a[i], b[i]) for i in range(3)]
            c["max"] = [max(a[i], b[i]) for i in range(3)]
    s["coordinate_system"]["up"] = up
    return s
