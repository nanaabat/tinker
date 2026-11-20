"""Write Python reference kinematics vectors for the C# parity test."""
import json
import math
from pathlib import Path

from tw_fixtures import BLIND_ID, PANEL_ID, room_scene
from tw_scene import find_joint, find_object, pose_for_value

s = room_scene(blind_value=0.3, panel_value=0.4)
cases = []
for oid, jn, vals in [(BLIND_ID, "tilt", [0, 0.1, 0.5, 1.0, 1.4, math.radians(83)]), (PANEL_ID, "slide", [0, 0.25, 0.9, 1.5, 2.0])]:
    o = find_object(s, oid)
    j = find_joint(o, jn)
    for v in vals:
        cases.append({"object_id": oid, "joint": jn, "value": v, "pose": pose_for_value(o, j, v)})
out = Path(__file__).resolve().parents[1] / "apps/tinker-rhino/TinkerWink.Core.Tests/vectors/kinematics.json"
out.write_text(json.dumps({"scene": s, "cases": cases}, indent=1))
print(out, len(cases))
