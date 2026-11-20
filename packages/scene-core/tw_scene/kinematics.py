"""Map between an object's world pose and a joint value. Joint axis/anchor are in the object's local frame
at the snapshot pose, which corresponds to joint['value']. Revolute values are radians."""
from __future__ import annotations

from .quat import add, dot, qangle_about, qaxis, qconj, qmul, qrot, sub


def find_object(snapshot: dict, object_id: str) -> dict:
    for o in snapshot["objects"]:
        if o["id"] == object_id:
            return o
    raise KeyError(f"object {object_id!r} not in scene")


def find_joint(obj: dict, joint: str) -> dict:
    for j in obj["joints"]:
        if j["name"] == joint:
            return j
    raise KeyError(f"joint {joint!r} not on {obj['id']!r}")


def pose_for_value(obj: dict, joint: dict, value: float) -> dict:
    pos, rot = obj["pose"]["position"], obj["pose"]["rotation"]
    delta = value - joint["value"]
    if joint["kind"] == "prismatic":
        return {"position": add(pos, qrot(rot, [c * delta for c in joint["axis"]])), "rotation": list(rot)}
    anchor_w = add(pos, qrot(rot, joint["anchor"]))
    new_rot = qmul(rot, qaxis(joint["axis"], delta))
    new_pos = sub(anchor_w, qrot(new_rot, joint["anchor"]))
    return {"position": new_pos, "rotation": new_rot}


def value_from_pose(obj: dict, joint: dict, pose: dict) -> float:
    pos, rot = obj["pose"]["position"], obj["pose"]["rotation"]
    if joint["kind"] == "prismatic":
        local = qrot(qconj(rot), sub(pose["position"], pos))
        n = dot(joint["axis"], joint["axis"]) ** 0.5 or 1.0
        return joint["value"] + dot(local, joint["axis"]) / n
    rel = qmul(qconj(rot), pose["rotation"])
    return joint["value"] + qangle_about(rel, joint["axis"])
