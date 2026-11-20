from __future__ import annotations

import math
import uuid

from tw_action import Trajectory, preview_transforms
from tw_connector import negotiate
from tw_contracts import validate
from tw_scene import find_joint, find_object
from tw_sim import simulate as mj_simulate, sunlit_fraction
from tinker_learning import ModelRegistry, SkillRuntime


class PlanError(RuntimeError):
    pass


class TinkerProvider:
    """wink's Tinker provider: list_skills / simulate / preview / apply. Never applies without an approved action."""

    def __init__(self, registry: ModelRegistry, connector=None):
        self.registry = registry
        self.connector = connector
        self._sims: dict[str, dict] = {}

    # ---- skills
    def list_skills(self, scene: dict, goal: dict | None) -> list[dict]:
        caps = self.connector.capabilities() if self.connector else None
        out = []
        for name in self.registry.skills():
            sk = self.registry.load_skill(name)
            if goal is not None:
                ts = goal["target_state"]
                if ts["object_type"] not in sk["target_types"]:
                    continue
            if caps is not None:
                ok, _ = negotiate(caps, sk)
                if not ok:
                    continue
            if not any(o["type"] in sk["target_types"] and any(j["kind"] == sk["preconditions"]["joint_kind"] for j in o["joints"])
                       for o in scene["objects"]):
                continue
            out.append(sk)
        out.sort(key=lambda s: -s["evaluation"]["confidence"])
        return out

    # ---- turn an intent into a concrete target value using geometry (not a feeling)
    def resolve_target(self, scene: dict, goal: dict, skill: dict, *, sun_dir=None, max_sunlit: float = 0.12) -> tuple[str, str, float, dict]:
        ts = goal["target_state"]
        cands = [o for o in scene["objects"] if o["type"] == ts["object_type"] and o["joints"]
                 and (ts.get("object_id") in (None, o["id"]))]
        if not cands:
            raise PlanError(f"no {ts['object_type']} with a joint in the scene")
        obj = cands[0]
        j = find_joint(obj, ts["joint"]) if ts.get("joint") else obj["joints"][0]
        if ts.get("target_value") is not None:
            return obj["id"], j["name"], float(ts["target_value"]), {"reason": "target value given by the goal"}
        if ts.get("intent") in ("reduce_direct_sun", "increase_daylight") and sun_dir is not None and obj["type"] == "blind":
            lo, hi = j["lower"], j["upper"]
            grid = [lo + (hi - lo) * i / 40 for i in range(41)]
            fr = []
            for v in grid:
                f = sunlit_fraction(scene, sun_dir, {obj["id"]: v})
                if f is None:
                    fr = []
                    break
                fr.append((v, f))
            if not fr:
                raise PlanError("no window in the scene to resolve a sunlit target")
            if ts["intent"] == "reduce_direct_sun":
                ok = [v for v, f in fr if f <= max_sunlit]
                # most open setting that still keeps direct sun under the cap (keeps view and daylight)
                v = max(ok) if ok else min(fr, key=lambda x: x[1])[0]
            else:
                v = max(fr, key=lambda x: x[1])[0]
            return obj["id"], j["name"], v, {"reason": f"most open {obj['type']} setting with direct sun on at most {max_sunlit:.0%} of the window",
                                             "sunlit_now": sunlit_fraction(scene, sun_dir), "sunlit_target": dict(fr)[v]}
        raise PlanError("goal has no target value and no geometric way to resolve its intent")

    def simulate(self, skill: dict, scene: dict, constraints: list[dict] | None = None, *, object_id: str, joint: str,
                 goal_value: float, sun_dir=None) -> dict:
        scene = dict(scene)
        if constraints:
            scene["constraints"] = list(scene.get("constraints", [])) + list(constraints)
        obj = find_object(scene, object_id)
        j = find_joint(obj, joint)
        rt = SkillRuntime(skill, self.registry)
        ok, why = rt.applicable(j, j["value"], goal_value)
        if not ok:
            res = {"schema_version": "1.0.0", "id": "sim-" + uuid.uuid4().hex[:16], "skill_id": skill["id"],
                   "scene_id": scene["scene_id"], "scene_hash": "0" * 64, "success": False,
                   "violations": [{"code": "not_applicable", "message": why, "t": None, "object_ids": [object_id]}],
                   "trace_ref": None, "trajectory": {"object_id": object_id, "joint": joint, "t": [], "value": []}, "metrics": {}}
            from tw_scene import scene_hash
            res["scene_hash"] = scene_hash(scene)
            return validate("SimulationResult", res)
        traj, info = rt.generate(object_id, j, j["value"], goal_value)
        res = mj_simulate(scene, traj, skill_id=skill["id"], sun_dir=sun_dir)
        res["metrics"].update({"method": info["method"], "applicability": info["applicability"],
                               "skill_confidence": info["confidence"], "skill_version": skill["version"]})
        validate("SimulationResult", res)
        self._sims[res["id"]] = {"result": res, "plan": traj.as_dict(), "scene": scene}
        return res

    def preview(self, simulation: dict, frames: int = 24) -> dict:
        rec = self._sims.get(simulation["id"])
        if rec is None:
            raise PlanError("unknown simulation")
        tr = Trajectory(**{k: rec["plan"][k] for k in ("object_id", "joint", "t", "value")})
        fr = preview_transforms(rec["scene"], tr, frames)
        handle = self.connector.preview_transforms(fr) if self.connector else None
        return {"frames": fr, "handle": handle}

    def apply(self, approved_action: dict) -> str:
        """approved_action = {simulation_id, approval: ActionApproval}. wink verifies policy before calling this."""
        if self.connector is None:
            raise PlanError("no host connected: tinker can only suggest")
        validate("ActionApproval", approved_action["approval"])
        rec = self._sims.get(approved_action["simulation_id"])
        if rec is None or approved_action["approval"]["simulation_id"] != approved_action["simulation_id"]:
            raise PlanError("approval does not match a known simulation")
        if not rec["result"]["success"]:
            raise PlanError("refusing to apply a failed simulation")
        tr = rec["plan"]
        return self.connector.apply_transforms([{"object_id": tr["object_id"], "joint": tr["joint"], "value": tr["value"][-1]}])
