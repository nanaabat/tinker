from __future__ import annotations

from dataclasses import dataclass, field

from tw_scene import find_joint, find_object, pose_for_value

EPS = 1e-6


@dataclass(frozen=True)
class JointMove:
    """Move one joint of one object to a target value (m for prismatic, rad for revolute)."""
    object_id: str
    joint: str
    target_value: float
    duration: float | None = None


@dataclass
class Trajectory:
    object_id: str
    joint: str
    t: list[float] = field(default_factory=list)
    value: list[float] = field(default_factory=list)

    def __post_init__(self):
        if len(self.t) != len(self.value):
            raise ValueError("t and value must be the same length")
        if any(b < a for a, b in zip(self.t, self.t[1:])):
            raise ValueError("trajectory time must be non-decreasing")

    @property
    def duration(self) -> float:
        return self.t[-1] - self.t[0] if self.t else 0.0

    def as_dict(self) -> dict:
        return {"object_id": self.object_id, "joint": self.joint, "t": list(self.t), "value": list(self.value)}

    def value_at(self, t: float) -> float:
        if not self.t:
            raise ValueError("empty trajectory")
        if t <= self.t[0]:
            return self.value[0]
        if t >= self.t[-1]:
            return self.value[-1]
        lo, hi = 0, len(self.t) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.t[mid] <= t:
                lo = mid
            else:
                hi = mid
        span = self.t[hi] - self.t[lo]
        a = 0.0 if span <= 0 else (t - self.t[lo]) / span
        return self.value[lo] + a * (self.value[hi] - self.value[lo])


def resample(traj: Trajectory, dt: float) -> Trajectory:
    if dt <= 0:
        raise ValueError("dt must be positive")
    n = max(1, int(round(traj.duration / dt)))
    ts = [traj.t[0] + i * traj.duration / n for i in range(n + 1)]
    return Trajectory(traj.object_id, traj.joint, ts, [traj.value_at(x) for x in ts])


def check_limits(snapshot: dict, traj: Trajectory) -> list[dict]:
    """Static checks before simulation: joint range, speed, travel_bounds/max_speed constraints."""
    out: list[dict] = []
    try:
        obj = find_object(snapshot, traj.object_id)
        j = find_joint(obj, traj.joint)
    except KeyError as e:
        return [{"code": "missing_geometry", "message": str(e.args[0]), "t": None, "object_ids": [traj.object_id]}]
    lo, hi = j["lower"], j["upper"]
    max_speed = j["max_speed"]
    for c in snapshot.get("constraints", []):
        if traj.object_id in c["object_ids"] or not c["object_ids"]:
            if c["kind"] == "travel_bounds" and "min" in c and "max" in c:
                lo, hi = max(lo, c["min"][0]), min(hi, c["max"][0])
            if c["kind"] == "max_speed" and "value" in c:
                max_speed = min(max_speed, c["value"])
    for t, v in zip(traj.t, traj.value):
        if v < lo - EPS or v > hi + EPS:
            out.append({"code": "joint_limit", "message": f"value {v:.4f} outside [{lo:.4f}, {hi:.4f}]", "t": t,
                        "object_ids": [traj.object_id]})
            break
    for (t0, v0), (t1, v1) in zip(zip(traj.t, traj.value), zip(traj.t[1:], traj.value[1:])):
        dt = t1 - t0
        if dt <= 0:
            if abs(v1 - v0) > EPS:
                out.append({"code": "speed_limit", "message": "instantaneous jump", "t": t1, "object_ids": [traj.object_id]})
                break
            continue
        sp = abs(v1 - v0) / dt
        if sp > max_speed * 1.02:
            out.append({"code": "speed_limit", "message": f"speed {sp:.4f} > max {max_speed:.4f}", "t": t1,
                        "object_ids": [traj.object_id]})
            break
    return out


def preview_transforms(snapshot: dict, traj: Trajectory, frames: int = 24) -> list[dict]:
    """Host-agnostic preview: object poses at evenly spaced times (does not modify the scene)."""
    obj = find_object(snapshot, traj.object_id)
    j = find_joint(obj, traj.joint)
    frames = max(2, frames)
    out = []
    for i in range(frames):
        t = traj.t[0] + traj.duration * i / (frames - 1)
        v = traj.value_at(t)
        out.append({"t": t, "object_id": obj["id"], "joint": j["name"], "value": v, "pose": pose_for_value(obj, j, v)})
    return out
