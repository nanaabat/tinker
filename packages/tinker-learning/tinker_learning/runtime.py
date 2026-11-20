"""Inference without PyTorch: ONNX Runtime policy + template fallback, producing trajectories for a Skill."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from tw_action import Trajectory

from .baseline import ParametricTemplate
from .features import rollout


class BCPolicy:
    def __init__(self, onnx_path: Path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self.sess = ort.InferenceSession(str(onnx_path), sess_options=so, providers=["CPUExecutionProvider"])

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return self.sess.run(["y"], {"x": x.astype(np.float32)})[0]


class SkillRuntime:
    """Generate a trajectory for a Skill document. Uses the ONNX model when present and the goal is inside the
    demonstrated range; otherwise falls back to the deterministic template and says so."""

    def __init__(self, skill: dict, registry=None):
        self.skill = skill
        self.template = ParametricTemplate.from_fallback(skill["fallback_trajectory"])
        self.policy = None
        ref = skill["model_ref"]
        if ref["kind"] == "behavior_cloning_onnx" and registry is not None and ref["path"]:
            self.policy = BCPolicy(registry.resolve(ref["path"], expect_sha256=ref["sha256"]))

    def applicable(self, joint: dict, start: float, goal: float) -> tuple[bool, str]:
        lo, hi = self.skill["preconditions"]["value_range"]
        if joint["kind"] != self.skill["preconditions"]["joint_kind"]:
            return False, "joint kind differs from the demonstrated skill"
        if not (joint["lower"] - 1e-9 <= goal <= joint["upper"] + 1e-9):
            return False, "goal is outside the joint's limits"
        if not (lo - 1e-9 <= goal <= hi + 1e-9 and lo - 1e-9 <= start <= hi + 1e-9):
            return True, "outside the demonstrated range: using the deterministic template, confidence reduced"
        return True, "inside the demonstrated range"

    def generate(self, object_id: str, joint: dict, start: float, goal: float) -> tuple[Trajectory, dict]:
        tr, info = self._generate(object_id, joint, start, goal)
        return self._respect_speed(tr, joint, info)

    @staticmethod
    def _respect_speed(tr: Trajectory, joint: dict, info: dict, margin: float = 0.9) -> tuple[Trajectory, dict]:
        """Demonstrations can be faster than the actuator allows. Slow the motion down uniformly (same path,
        longer time) so the peak speed stays under margin x max_speed. Reported, never silent."""
        peak = 0.0
        for (t0, v0), (t1, v1) in zip(zip(tr.t, tr.value), zip(tr.t[1:], tr.value[1:])):
            if t1 > t0:
                peak = max(peak, abs(v1 - v0) / (t1 - t0))
        limit = joint["max_speed"] * margin
        if peak > limit:
            k = peak / limit
            tr = Trajectory(tr.object_id, tr.joint, [t * k for t in tr.t], list(tr.value))
            info = {**info, "time_scaled": round(k, 4), "note": f"slowed {k:.2f}x to stay under {margin:.0%} of max speed"}
        return tr, info

    def _generate(self, object_id: str, joint: dict, start: float, goal: float) -> tuple[Trajectory, dict]:
        ok, why = self.applicable(joint, start, goal)
        span = joint["upper"] - joint["lower"]
        conf = float(self.skill["evaluation"]["confidence"])
        info = {"method": "template", "applicability": why, "confidence": conf}
        if abs(goal - start) < 1e-9:
            return Trajectory(object_id, joint["name"], [0.0, 0.05], [start, goal]), {**info, "method": "noop"}
        if self.policy is not None and ok and why == "inside the demonstrated range":
            ts, vs, raw_end = rollout(self.policy, start, goal, span)
            info.update({"method": "behavior_cloning_onnx", "raw_end_progress": raw_end})
            return Trajectory(object_id, joint["name"], ts, vs), info
        if why.startswith("outside the demonstrated"):
            info["confidence"] = round(conf * 0.5, 3)
        return self.template.generate(object_id, joint["name"], start, goal), info
