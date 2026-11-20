"""Blender implementation of the tinker connector interface (scene <-> SceneSnapshot, record, preview, apply, undo).
Must run on Blender's main thread."""
from __future__ import annotations

import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from ._vendor.tw_scene import IdMap, find_joint, find_object, pose_for_value

PROP = "tinker"  # custom property namespace on objects
UNIT_FROM_SCALE = {1.0: "m", 0.01: "cm", 0.001: "mm"}


def scene_units(scene) -> str:
    s = round(scene.unit_settings.scale_length, 6)
    return UNIT_FROM_SCALE.get(s, "m")


def _box_center_local(obj) -> Vector:
    bb = [Vector(c) for c in obj.bound_box]
    return sum(bb, Vector()) / 8.0


def object_pose(obj) -> dict:
    mw = obj.matrix_world
    loc, rot, scale = mw.decompose()
    c_local = _box_center_local(obj)
    center = mw @ c_local
    q = rot.normalized()
    return {"position": [center.x, center.y, center.z], "rotation": [q.w, q.x, q.y, q.z]}


def set_object_pose(obj, pose: dict):
    """Place obj so that its bounding-box centre and rotation match `pose`, keeping its scale."""
    _, _, scale = obj.matrix_world.decompose()
    q = Quaternion(pose["rotation"]).normalized()
    c_local = _box_center_local(obj)
    offset = q @ Vector((c_local.x * scale.x, c_local.y * scale.y, c_local.z * scale.z))
    loc = Vector(pose["position"]) - offset
    obj.matrix_world = Matrix.LocRotScale(loc, q, scale)


def _looks_like_window(obj) -> bool:
    name = (obj.name or "").lower()
    if obj.type != "MESH" or "frame" in name:
        return False
    return any(w in name for w in ("window", "glaz", "glass"))


def tinker_objects(scene):
    out = [o for o in scene.objects if PROP in o.keys() or o.get("tinker_type") or o.get("tinker_id") or o.get("tinker_joint")]
    seen = {o.name for o in out}
    # include untagged glazing so wink can resolve a sunlit-window target on real models
    for o in scene.objects:
        if o.name in seen:
            continue
        if _looks_like_window(o):
            out.append(o)
            seen.add(o.name)
    return out


def snapshot(context) -> dict:
    scene = context.scene
    doc_id = bpy.data.filepath or "untitled.blend"
    ids = IdMap("blender", doc_id)
    objs = []
    for o in tinker_objects(scene):
        if o.type not in {"MESH", "EMPTY", "LIGHT"}:
            continue
        sid = ids.add(o.name, preferred=o.get("tinker_id"))
        joints = []
        jd = o.get("tinker_joint")
        if jd:
            j = dict(jd)
            joints.append({"name": str(j["name"]), "kind": str(j["kind"]), "axis": [float(x) for x in j["axis"]],
                           "anchor": [float(x) for x in j["anchor"]], "lower": float(j["lower"]), "upper": float(j["upper"]),
                           "max_speed": float(j["max_speed"]), "max_force": float(j["max_force"]), "value": float(j["value"])})
        parent = o.parent.get("tinker_id") if o.parent is not None and o.parent.get("tinker_id") else None
        typ = str(o.get("tinker_type") or "generic")
        if typ == "generic" and _looks_like_window(o):
            typ = "window"
        objs.append({"id": sid, "host_id": o.name, "name": o.name, "type": typ,
                     "parent_id": o.get("tinker_parent") or parent, "pose": object_pose(o),
                     "size": [float(d) for d in o.dimensions], "geometry_ref": "blender:" + (o.data.name if o.data is not None else o.name),
                     "collision": bool(o.get("tinker_collision", typ != "window")), "joints": joints})
    cons = [dict(c) for c in scene.get("tinker_constraints", [])] if scene.get("tinker_constraints") else []
    for c in cons:
        for k in ("min", "max"):
            if k in c:
                c[k] = [float(x) for x in c[k]]
        c["object_ids"] = [str(x) for x in c.get("object_ids", [])]
    return {"schema_version": "1.0.0", "scene_id": "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in scene.name)[:100] or "scene",
            "units": scene_units(scene), "coordinate_system": {"up": "z", "handedness": "right"},
            "host": {"name": "blender", "version": bpy.app.version_string}, "objects": objs, "constraints": cons}


def build_from_snapshot(context, snap: dict, collection_name: str = "tinker fixture"):
    """Create cube meshes for a SceneSnapshot (used for fixtures and importing scenes)."""
    coll = bpy.data.collections.get(collection_name) or bpy.data.collections.new(collection_name)
    if coll.name not in context.scene.collection.children:
        context.scene.collection.children.link(coll)
    made = {}
    for od in snap["objects"]:
        mesh = bpy.data.meshes.new(od["id"] + "-mesh")
        sx, sy, sz = (s / 2 for s in od["size"])
        verts = [(x * sx, y * sy, z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        ob = bpy.data.objects.new(od["host_id"], mesh)
        coll.objects.link(ob)
        ob["tinker_id"] = od["id"]
        ob["tinker_type"] = od["type"]
        ob["tinker_collision"] = od["collision"]
        if od["parent_id"]:
            ob["tinker_parent"] = od["parent_id"]
        if od["joints"]:
            ob["tinker_joint"] = dict(od["joints"][0])
        if not od["collision"]:
            ob.display_type = "WIRE"
            ob.hide_render = True
        set_object_pose(ob, od["pose"])
        made[od["id"]] = ob
    if snap.get("constraints"):
        context.scene["tinker_constraints"] = snap["constraints"]
    context.view_layer.update()
    return made


def object_by_id(context, sid: str):
    for o in tinker_objects(context.scene):
        if o.get("tinker_id") == sid or o.name == sid:
            return o
    return None


class Recorder:
    """Samples the selected object's pose from depsgraph updates while recording."""
    active: "Recorder | None" = None

    def __init__(self, obj_name: str, min_interval: float = 1 / 60):
        self.obj_name = obj_name
        self.min_interval = min_interval
        self.samples: list[dict] = []
        self.t0 = time.monotonic()
        self._last_pose = None
        self._last_t = -1e9

    def sample(self, obj, t: float | None = None, event: str = "sample"):
        t = (time.monotonic() if t is None else t) - self.t0
        pose = object_pose(obj)
        if self._last_pose is not None and pose == self._last_pose and event == "sample":
            return
        if event == "sample" and t - self._last_t < self.min_interval:
            return
        if self.samples and t < self.samples[-1]["t"]:
            t = self.samples[-1]["t"]
        self._last_pose, self._last_t = pose, t
        self.samples.append({"t": round(t, 6), "poses": {obj.get("tinker_id", obj.name): pose}, "action": None, "event": event})


def on_depsgraph_update(scene, depsgraph):
    rec = Recorder.active
    if rec is None:
        return
    obj = scene.objects.get(rec.obj_name)
    if obj is None:
        return
    for upd in depsgraph.updates:
        if upd.is_updated_transform and getattr(upd.id, "name", None) == rec.obj_name:
            rec.sample(obj)
            break
