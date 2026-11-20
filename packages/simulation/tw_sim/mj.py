from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

import mujoco
import numpy as np

from tw_action import Trajectory, check_limits
from tw_scene import convert_scene, find_joint, find_object, pose_for_value, scene_hash


@dataclass(frozen=True)
class SimConfig:
    timestep: float = 0.002
    settle: float = 0.5           # seconds held at the final target
    goal_tolerance_prismatic: float = 0.005  # m
    goal_tolerance_revolute: float = math.radians(1.0)
    penetration_tolerance: float = 0.002     # m; deeper contacts count as collisions
    speed_tolerance: float = 1.10            # x max_speed allowed transiently
    trace_stride: int = 10


def _fmt(v):
    return " ".join(f"{float(x):.9g}" for x in v)


def build_mjcf(snapshot: dict, moving_id: str, joint_name: str) -> str:
    """One moving body with one joint; everything else is static world geometry. Metres, Z-up."""
    if snapshot["coordinate_system"]["up"] != "z":
        raise ValueError("simulation expects a Z-up scene; convert with tw_scene.convert_axes first")
    geoms, body = [], ""
    for o in snapshot["objects"]:
        if not o["collision"]:
            continue
        if any(s <= 0 for s in o["size"]):
            continue  # missing geometry is reported by simulate()
        half = [s / 2 for s in o["size"]]
        if o["id"] == moving_id:
            j = find_joint(o, joint_name)
            jtype = "slide" if j["kind"] == "prismatic" else "hinge"
            body = (f'<body name={quoteattr(o["id"])} pos="{_fmt(o["pose"]["position"])}" quat="{_fmt(o["pose"]["rotation"])}">'
                    f'<joint name="j" type="{jtype}" axis="{_fmt(j["axis"])}" pos="{_fmt(j["anchor"])}" '
                    f'range="{j["lower"] - j["value"]:.9g} {j["upper"] - j["value"]:.9g}" limited="true" damping="5" armature="0.05"/>'
                    f'<geom name={quoteattr("g:" + o["id"])} type="box" size="{_fmt(half)}" density="300"/></body>')
        else:
            geoms.append(f'<geom name={quoteattr("g:" + o["id"])} type="box" pos="{_fmt(o["pose"]["position"])}" '
                         f'quat="{_fmt(o["pose"]["rotation"])}" size="{_fmt(half)}"/>')
    if not body:
        raise KeyError(f"moving object {moving_id!r} has no collision geometry")
    o = find_object(snapshot, moving_id)
    j = find_joint(o, joint_name)
    return (f'<mujoco model="tinker"><compiler angle="radian"/><option timestep="0.002" gravity="0 0 0" integrator="implicitfast"/>'
            f'<worldbody>{"".join(geoms)}{body}</worldbody>'
            f'<actuator><position name="a" joint="j" kp="4000" dampratio="1" forcelimited="true" '
            f'forcerange="{-j["max_force"]:.9g} {j["max_force"]:.9g}"/></actuator></mujoco>')


def _aabb_overlap(lo1, hi1, lo2, hi2):
    return all(lo1[i] < hi2[i] and lo2[i] < hi1[i] for i in range(3))


def simulate(snapshot: dict, traj: Trajectory, *, skill_id: str = "adhoc", config: SimConfig = SimConfig(),
             sun_dir: list[float] | None = None) -> dict:
    """Run the trajectory through MuJoCo and return a SimulationResult document."""
    sid = "sim-" + uuid.uuid5(uuid.NAMESPACE_URL, scene_hash(snapshot) + repr(traj.as_dict()) + skill_id).hex[:16]
    s_hash = scene_hash(snapshot)
    snap_m = convert_scene(snapshot, "m") if snapshot["units"] != "m" else snapshot
    f = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}[snapshot["units"]]
    result = {"schema_version": "1.0.0", "id": sid, "skill_id": skill_id, "scene_id": snapshot["scene_id"],
              "scene_hash": s_hash, "success": False, "violations": [], "trace_ref": None,
              "trajectory": {"object_id": traj.object_id, "joint": traj.joint, "t": [], "value": []}, "metrics": {}}
    try:
        obj = find_object(snap_m, traj.object_id)
        j = find_joint(obj, traj.joint)
    except KeyError as e:
        result["violations"].append({"code": "missing_geometry", "message": str(e.args[0]), "t": None, "object_ids": [traj.object_id]})
        return result
    bad = [o["id"] for o in snap_m["objects"] if o["collision"] and any(s <= 0 for s in o["size"])]
    if obj["id"] in bad:
        result["violations"].append({"code": "missing_geometry", "message": "moving object has no geometry", "t": None, "object_ids": [obj["id"]]})
        return result
    prismatic = j["kind"] == "prismatic"
    vt = Trajectory(traj.object_id, traj.joint, list(traj.t), [v * f if prismatic else v for v in traj.value])
    goal = vt.value[-1]
    if goal < j["lower"] - 1e-9 or goal > j["upper"] + 1e-9:
        result["violations"].append({"code": "unreachable_goal", "message": f"goal {traj.value[-1]:.4f} outside joint range",
                                     "t": None, "object_ids": [obj["id"]]})
    result["violations"] += check_limits(snap_m, vt)

    model = mujoco.MjModel.from_xml_string(build_mjcf(snap_m, obj["id"], j["name"]))
    model.opt.timestep = config.timestep
    data = mujoco.MjData(model)
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, obj["id"])
    mgeom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "g:" + obj["id"])
    base = j["value"]
    lo_q, hi_q = j["lower"] - base, j["upper"] - base
    data.qpos[0] = vt.value[0] - base
    mujoco.mj_forward(model, data)
    nogo = [c for c in snap_m.get("constraints", []) if c["kind"] == "no_go_volume"]
    total = vt.duration + config.settle
    steps = int(math.ceil(total / config.timestep))
    collided: dict[str, float] = {}
    nogo_hit: dict[str, float] = {}
    max_speed_seen, max_force_seen, max_track = 0.0, 0.0, 0.0
    saturated_steps = 0
    tol = config.goal_tolerance_prismatic if prismatic else config.goal_tolerance_revolute
    for k in range(steps + 1):
        t = vt.t[0] + k * config.timestep
        target = min(max(vt.value_at(t) - base, lo_q), hi_q)
        data.ctrl[0] = target
        if k:
            mujoco.mj_step(model, data)
        q = float(data.qpos[0])
        max_speed_seen = max(max_speed_seen, abs(float(data.qvel[0])))
        frc = abs(float(data.actuator_force[0]))
        max_force_seen = max(max_force_seen, frc)
        if frc >= j["max_force"] * 0.999:
            saturated_steps += 1
        if t <= vt.t[-1]:
            max_track = max(max_track, abs(q - target))
        for c in data.contact[: data.ncon]:
            if c.dist < -config.penetration_tolerance and mgeom in (c.geom1, c.geom2):
                other = c.geom2 if c.geom1 == mgeom else c.geom1
                name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, other)[2:]
                collided.setdefault(name, t)
        if nogo:
            # world AABB of the moving box from MuJoCo's current pose
            xm, xr = data.geom_xpos[mgeom], data.geom_xmat[mgeom].reshape(3, 3)
            half = model.geom_size[mgeom]
            ext = np.abs(xr) @ half
            lo, hi = xm - ext, xm + ext
            for c in nogo:
                if _aabb_overlap(lo, hi, c["min"], c["max"]):
                    nogo_hit.setdefault(c["id"], t)
        if k % config.trace_stride == 0 or k == steps:
            v = q + base
            result["trajectory"]["t"].append(round(t, 6))
            result["trajectory"]["value"].append(round(v / f if prismatic else v, 9))
    final = float(data.qpos[0]) + base
    for name, t in collided.items():
        result["violations"].append({"code": "collision", "message": f"{obj['id']} penetrates {name}", "t": round(t, 4),
                                     "object_ids": [obj["id"], name]})
    for cid, t in nogo_hit.items():
        result["violations"].append({"code": "no_go_volume", "message": f"{obj['id']} enters {cid}", "t": round(t, 4),
                                     "object_ids": [obj["id"]]})
    if max_speed_seen > j["max_speed"] * config.speed_tolerance and not any(v["code"] == "speed_limit" for v in result["violations"]):
        result["violations"].append({"code": "speed_limit", "message": f"simulated speed {max_speed_seen:.3f} > {j['max_speed']:.3f}",
                                     "t": None, "object_ids": [obj["id"]]})
    reached = abs(final - goal) <= tol
    if not reached and not any(v["code"] == "unreachable_goal" for v in result["violations"]):
        code = "force_limit" if saturated_steps > 0.2 / config.timestep else "unreachable_goal"
        result["violations"].append({"code": code, "message": f"final {final / f if prismatic else final:.4f} vs goal {traj.value[-1]:.4f}",
                                     "t": None, "object_ids": [obj["id"]]})
    m = result["metrics"]
    m.update({"engine": f"mujoco {mujoco.__version__}", "timestep_s": config.timestep, "steps": steps,
              "final_value": final / f if prismatic else final, "goal_value": traj.value[-1],
              "goal_error": abs(final - goal) / f if prismatic else abs(final - goal), "reached_goal": reached,
              "max_speed": max_speed_seen / f if prismatic else max_speed_seen, "max_force_n": max_force_seen,
              "max_tracking_error": max_track / f if prismatic else max_track, "duration_s": vt.duration,
              "units": snapshot["units"] if prismatic else "rad"})
    if sun_dir is not None and obj["type"] == "blind":
        a = sunlit_fraction(snapshot, sun_dir, {obj["id"]: traj.value[0]})
        b = sunlit_fraction(snapshot, sun_dir, {obj["id"]: traj.value[-1]})
        if a is not None and b is not None:
            m["sunlit_fraction_start"] = a
            m["sunlit_fraction_end"] = b
    result["success"] = reached and not result["violations"]
    return result


def sunlit_fraction(snapshot: dict, sun_dir: list[float], joint_values: dict[str, float] | None = None, n: int = 12) -> float | None:
    """Fraction of rays from a grid on the outer window face that reach the sun unobstructed (blind/obstacles block).
    A geometric daylight proxy, not a lighting simulation."""
    snap = convert_scene(snapshot, "m") if snapshot["units"] != "m" else snapshot
    snap = {**snap, "objects": [dict(o) for o in snap["objects"]]}
    for o in snap["objects"]:
        if joint_values and o["id"] in joint_values and o["joints"]:
            j = o["joints"][0]
            o["pose"] = pose_for_value(o, j, joint_values[o["id"]])
    win = next((o for o in snap["objects"] if o["type"] == "window"), None)
    if win is None:
        return None
    geoms = []
    for o in snap["objects"]:
        if o["collision"] and o["type"] not in ("window", "wall", "floor") and all(s > 0 for s in o["size"]):
            geoms.append(f'<geom name={quoteattr(o["id"])} type="box" pos="{_fmt(o["pose"]["position"])}" '
                         f'quat="{_fmt(o["pose"]["rotation"])}" size="{_fmt([s / 2 for s in o["size"]])}"/>')
    if not geoms:
        return 1.0
    model = mujoco.MjModel.from_xml_string(f'<mujoco><worldbody>{"".join(geoms)}</worldbody></mujoco>')
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    d = np.array(sun_dir, dtype=float)
    d /= np.linalg.norm(d)
    cx, cy, cz = win["pose"]["position"]
    w, _, h = win["size"]
    y_out = cy - 0.051 - 0.001  # outer wall face (wall thickness 0.1 centred on the glass)
    hits, geomid = 0, np.zeros(1, dtype=np.int32)
    for i in range(n):
        for k in range(n):
            p = np.array([cx - w / 2 + w * (i + 0.5) / n, y_out, cz - h / 2 + h * (k + 0.5) / n])
            if mujoco.mj_ray(model, data, p, d, None, 1, -1, geomid) < 0:
                hits += 1
    return hits / (n * n)
