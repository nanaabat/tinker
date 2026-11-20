from __future__ import annotations

import math
import uuid

from tw_scene import find_joint, find_object, value_from_pose


class InvalidDemonstration(ValueError):
    pass


class Recorder:
    """Turns host change events into a Demonstration document.

    - samples of the target object are rate limited to `min_interval` seconds (edits/undo/redo always kept)
    - events for other objects are ignored (the demo covers one selected object)
    - undo/redo during recording are recorded as events; the resulting pose is what counts
    """

    def __init__(self, snapshot: dict, object_id: str, joint: str, *, min_interval: float = 1 / 60, context: dict | None = None):
        self.snapshot = snapshot
        self.obj = find_object(snapshot, object_id)
        self.joint = find_joint(self.obj, joint)
        self.min_interval = min_interval
        self.context = dict(context or {})
        self.samples: list[dict] = []
        self.recording = False
        self._t0: float | None = None
        self._last_t = -math.inf

    def start(self, t0: float | None = None):
        if self.recording:
            raise RuntimeError("already recording")
        self.recording, self.samples, self._t0, self._last_t = True, [], t0, -math.inf

    def on_change(self, object_id: str, pose: dict, t: float, event: str = "sample"):
        if not self.recording or object_id != self.obj["id"]:
            return
        if self._t0 is None:
            self._t0 = t
        rel = t - self._t0
        if rel < 0:
            return  # out-of-order event from before recording started
        if event == "sample" and rel - self._last_t < self.min_interval:
            return
        if self.samples and rel < self.samples[-1]["t"]:
            rel = self.samples[-1]["t"]  # clamp host clock jitter; time stays monotonic
        self._last_t = rel
        self.samples.append({"t": round(rel, 6), "poses": {object_id: pose}, "action": None, "event": event})

    def stop(self, demo_id: str | None = None, corrections_of: list[str] | None = None) -> dict:
        if not self.recording:
            raise RuntimeError("not recording")
        self.recording = False
        if len(self.samples) < 2:
            raise InvalidDemonstration("demonstration is empty: move the selected object while recording")
        final = value_from_pose(self.obj, self.joint, self.samples[-1]["poses"][self.obj["id"]])
        return {"schema_version": "1.0.0", "id": demo_id or "demo-" + uuid.uuid4().hex[:12],
                "scene_id": self.snapshot["scene_id"], "object_ids": [self.obj["id"]], "samples": self.samples,
                "goal": {"object_id": self.obj["id"], "joint": self.joint["name"], "target_value": final},
                "context": self.context, "user_corrections": list(corrections_of or [])}


def demo_series(demo: dict, snapshot: dict) -> tuple[list[float], list[float]]:
    """(t, joint value) for the demo's target object. Validates content beyond schema."""
    oid = demo["goal"]["object_id"]
    obj = find_object(snapshot, oid)
    j = find_joint(obj, demo["goal"]["joint"])
    ts, vs = [], []
    for s in demo["samples"]:
        pose = s["poses"].get(oid)
        if pose is None:
            continue
        v = value_from_pose(obj, j, pose)
        if not all(math.isfinite(c) for c in pose["position"] + pose["rotation"]) or not math.isfinite(v):
            raise InvalidDemonstration("non-finite pose in demonstration")
        if ts and s["t"] < ts[-1]:
            raise InvalidDemonstration("demonstration time goes backwards")
        if ts and s["t"] == ts[-1]:
            vs[-1] = v
            continue
        ts.append(float(s["t"]))
        vs.append(v)
    if len(ts) < 2:
        raise InvalidDemonstration("demonstration has fewer than two samples of the target object")
    span = j["upper"] - j["lower"]
    if abs(vs[-1] - vs[0]) < 1e-3 * span:
        raise InvalidDemonstration("the object did not move during the demonstration")
    return ts, vs
