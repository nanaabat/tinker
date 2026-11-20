"""Z-up, right-handed, metres by default. Room spans x in [0, W], y in [0, D], z in [0, H].
The south wall sits at y in [-T, 0] and has a window; the blind hangs outside it (y < -T), hinged at its top edge.
Blind joint 'tilt': 0 rad = closed (hanging flat over the window), up to ~83 deg swung outward.
Sliding panel joint 'slide': prismatic along +x inside the room."""
from __future__ import annotations

import math

from tw_scene import convert_scene

IDENT = [1.0, 0.0, 0.0, 0.0]
BLIND_ID = "blind-south"
PANEL_ID = "panel-sliding"
WINDOW_ID = "window-south"


def _box(id_, type_, center, size, *, parent=None, collision=True, joints=None, rot=None):
    return {"id": id_, "host_id": id_, "name": id_.replace("-", " "), "type": type_, "parent_id": parent,
            "pose": {"position": [float(c) for c in center], "rotation": list(rot or IDENT)},
            "size": [float(s) for s in size], "geometry_ref": "box", "collision": collision, "joints": joints or []}


def room_scene(width=4.0, depth=5.0, height=2.7, *, wall=0.1, window_w=1.6, window_h=1.4, sill=0.9,
               blind_value=0.0, panel_value=0.0, panel_travel=2.0, obstacle=None, no_go=None,
               units="m", scene_id="fixture-room") -> dict:
    W, D, H, T = width, depth, height, wall
    x0, x1 = W / 2 - window_w / 2, W / 2 + window_w / 2
    z0, z1 = sill, sill + window_h
    objs = [
        _box("room", "room", [W / 2, D / 2, H / 2], [W, D, H], collision=False),
        _box("floor", "floor", [W / 2, D / 2, -0.05], [W + 2 * T, D + 2 * T, 0.1], parent="room"),
        _box("wall-north", "wall", [W / 2, D + T / 2, H / 2], [W + 2 * T, T, H], parent="room"),
        _box("wall-east", "wall", [W + T / 2, D / 2, H / 2], [T, D, H], parent="room"),
        _box("wall-west", "wall", [-T / 2, D / 2, H / 2], [T, D, H], parent="room"),
        _box("wall-south-left", "wall", [(x0 - T) / 2, -T / 2, H / 2], [x0 + T, T, H], parent="room"),
        _box("wall-south-right", "wall", [(x1 + W + T) / 2, -T / 2, H / 2], [W + T - x1, T, H], parent="room"),
        _box("wall-south-below", "wall", [W / 2, -T / 2, z0 / 2], [window_w, T, z0], parent="room"),
        _box("wall-south-above", "wall", [W / 2, -T / 2, (z1 + H) / 2], [window_w, T, H - z1], parent="room"),
        _box(WINDOW_ID, "window", [W / 2, -T / 2, (z0 + z1) / 2], [window_w, 0.01, window_h], parent="room"),
    ]
    bh, bw = window_h + 0.1, window_w + 0.1
    blind = _box(BLIND_ID, "blind", [W / 2, -T - 0.06, (z0 + z1) / 2], [bw, 0.02, bh], parent=WINDOW_ID, joints=[{
        "name": "tilt", "kind": "revolute", "axis": [-1.0, 0.0, 0.0], "anchor": [0.0, 0.0, bh / 2],
        "lower": 0.0, "upper": math.radians(83), "max_speed": 0.6, "max_force": 40.0, "value": 0.0}])
    objs.append(blind)
    pw, ph = 1.2, 2.2
    panel = _box(PANEL_ID, "sliding_panel", [0.15 + pw / 2, D / 2, 0.02 + ph / 2], [pw, 0.05, ph], parent="room", joints=[{
        "name": "slide", "kind": "prismatic", "axis": [1.0, 0.0, 0.0], "anchor": [0.0, 0.0, 0.0],
        "lower": 0.0, "upper": float(panel_travel), "max_speed": 0.5, "max_force": 200.0, "value": 0.0}])
    objs.append(panel)
    if obstacle is not None:  # (center, size)
        objs.append(_box("obstacle", "obstacle", obstacle[0], obstacle[1], parent="room"))
    constraints = []
    if no_go is not None:  # (min, max)
        constraints.append({"id": "nogo-1", "kind": "no_go_volume", "object_ids": [], "min": list(no_go[0]), "max": list(no_go[1])})
    snap = {"schema_version": "1.0.0", "scene_id": scene_id, "units": "m",
            "coordinate_system": {"up": "z", "handedness": "right"},
            "host": {"name": "fixture", "version": "0.1.0"}, "objects": objs, "constraints": constraints}
    # apply initial joint values by re-posing (the snapshot pose always corresponds to joint.value)
    from tw_scene import pose_for_value
    for oid, val in ((BLIND_ID, blind_value), (PANEL_ID, panel_value)):
        o = next(x for x in objs if x["id"] == oid)
        j = o["joints"][0]
        o["pose"] = pose_for_value(o, j, val)
        j["value"] = float(val)
    return snap if units == "m" else convert_scene(snap, units)
