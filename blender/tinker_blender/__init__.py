"""tinker for Blender: Select -> Record -> Stop -> Learn -> Simulate -> Preview -> Apply (+ Undo).
Learning and simulation run in the local tinker service (loopback, token-authenticated). Never auto-applies."""

import json
import math
import os
import queue
import subprocess
import sys
import threading

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import connector as C
try:  # hunch + tingle sections ship with the tingle build; tinker/wink also run without them
    from . import hunch_panel as HP
    from . import tingle_panel as TP
except ImportError:
    HP = TP = None
from .client import ServiceError, TinkerClient

_results: "queue.Queue" = queue.Queue()
_DEMOS_TEXT = "tinker_demos.json"
_PLAN_TEXT = "tinker_last_plan.json"
_UNDO_TEXT = "tinker_undo.json"
GHOST = "tinker preview"


def _text_json(name, default):
    t = bpy.data.texts.get(name)
    if t is None:
        return default
    try:
        return json.loads(t.as_string())
    except ValueError:
        return default


def _set_text_json(name, value):
    t = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    t.clear()
    t.write(json.dumps(value))


def _prefs(context):
    a = context.preferences.addons.get(__package__)
    return a.preferences if a else None


def _client(context) -> TinkerClient:
    p = _prefs(context)
    port = p.port if p else 47615
    tok = p.token_file if p and p.token_file else None
    return TinkerClient(port=port, token_file=tok)


class TinkerPrefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    port: IntProperty(name="Service port", default=47615, min=1024, max=65535)
    token_file: StringProperty(name="Token file", subtype="FILE_PATH", default="")
    service_python: StringProperty(name="Service Python", subtype="FILE_PATH", default="",
                                   description="Python with tinker-service installed (set once by the installer)")

    def draw(self, context):
        for k in ("port", "token_file", "service_python"):
            self.layout.prop(self, k)


class TinkerState(bpy.types.PropertyGroup):
    target: StringProperty(name="Target", default="")
    status: StringProperty(name="Status", default="select an object with a tinker joint")
    skill_name: StringProperty(name="Skill", default="")
    goal: FloatProperty(name="Goal", default=0.0, description="target joint value (degrees for hinges, scene units for slides)")
    confidence: FloatProperty(name="Confidence", default=0.0)
    sim_ok: BoolProperty(default=False)
    sim_summary: StringProperty(default="")
    preview_frame: IntProperty(name="Preview frame", default=23, min=0, max=239, update=lambda s, c: _update_ghost(c))
    busy: BoolProperty(default=False)
    progress: FloatProperty(default=0.0, min=0.0, max=1.0, subtype="FACTOR")
    recording: BoolProperty(default=False)
    use_ml: BoolProperty(name="Behavior cloning (ML)", default=True)


def _state(context) -> TinkerState:
    return context.scene.tinker


def _target(context):
    st = _state(context)
    obj = context.scene.objects.get(st.target) if st.target else None
    return obj


def _plain(x):
    """IDProperty groups/arrays -> plain JSON-able Python values."""
    if hasattr(x, "to_dict"):
        x = x.to_dict()
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if hasattr(x, "to_list"):
        x = x.to_list()
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _joint(obj):
    return _plain(obj["tinker_joint"]) if obj is not None and obj.get("tinker_joint") else None


def _goal_value(context, joint):
    g = _state(context).goal
    return math.radians(g) if joint["kind"] == "revolute" else g


def _run(context, fn, on_done, blocking):
    st = _state(context)
    if blocking:
        try:
            on_done(context, fn(), None)
        except ServiceError as e:
            on_done(context, None, e)
        return
    st.busy, st.progress = True, 0.1

    def work():
        try:
            _results.put((on_done, fn(), None))
        except ServiceError as e:
            _results.put((on_done, None, e))
    threading.Thread(target=work, daemon=True).start()
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=0.2)


def _poll():
    ctx = bpy.context
    try:
        on_done, res, err = _results.get_nowait()
    except queue.Empty:
        if ctx.scene is not None:
            st = _state(ctx)
            st.progress = min(0.95, st.progress + 0.03)
        return 0.2
    st = _state(ctx)
    st.busy, st.progress = False, 1.0
    on_done(ctx, res, err)
    for w in ctx.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()
    return None


# ---------------------------------------------------------------- operators
class TINKER_OT_select(bpy.types.Operator):
    bl_idname = "tinker.select"
    bl_label = "Select"
    bl_description = "Use the active object as the tinker target"

    def execute(self, context):
        obj = context.active_object
        st = _state(context)
        if obj is None or not obj.get("tinker_joint"):
            self.report({"ERROR"}, "the active object has no tinker joint (add one in the object's tinker settings)")
            return {"CANCELLED"}
        st.target = obj.name
        j = _joint(obj)
        st.goal = math.degrees(j["value"]) if j["kind"] == "revolute" else j["value"]
        st.status = f"selected {obj.name} ({j['kind']} joint '{j['name']}')"
        return {"FINISHED"}


class TINKER_OT_record(bpy.types.Operator):
    bl_idname = "tinker.record"
    bl_label = "Record"
    bl_description = "Start recording; move the object with Blender's own tools"

    def execute(self, context):
        obj = _target(context)
        if obj is None:
            self.report({"ERROR"}, "select a target first")
            return {"CANCELLED"}
        C.Recorder.active = C.Recorder(obj.name)
        C.Recorder.active.sample(obj, event="sample")
        _state(context).recording = True
        _state(context).status = "recording: move the object, then press Stop"
        return {"FINISHED"}


class TINKER_OT_stop(bpy.types.Operator):
    bl_idname = "tinker.stop"
    bl_label = "Stop"

    def execute(self, context):
        rec = C.Recorder.active
        st = _state(context)
        C.Recorder.active = None
        st.recording = False
        obj = _target(context)
        if rec is None or obj is None:
            return {"CANCELLED"}
        rec.sample(obj, event="edit")
        if len(rec.samples) < 2:
            st.status = "nothing recorded: move the object while recording"
            self.report({"WARNING"}, st.status)
            return {"CANCELLED"}
        snap = C.snapshot(context)
        sid = obj.get("tinker_id", obj.name)
        from ._vendor.tw_scene import find_joint, find_object, value_from_pose
        # goal = final joint value, computed against the scene state at the START of the demo
        start_obj = json.loads(json.dumps(find_object(snap, sid)))
        j0 = find_joint(start_obj, _joint(obj)["name"])
        start_val = j0["value"]
        start_obj["pose"] = rec.samples[0]["poses"][sid]
        final = value_from_pose(start_obj, dict(j0, value=start_val), rec.samples[-1]["poses"][sid])
        demos = _text_json(_DEMOS_TEXT, [])
        demo = {"schema_version": "1.0.0", "id": f"demo-blender-{len(demos):03d}", "scene_id": snap["scene_id"],
                "object_ids": [sid], "samples": rec.samples,
                "goal": {"object_id": sid, "joint": j0["name"], "target_value": final},
                "context": {"source": "blender", "start_value": start_val}, "user_corrections": []}
        demos.append({"demo": demo, "scene": _scene_at(snap, sid, start_val, rec.samples[0]["poses"][sid])})
        _set_text_json(_DEMOS_TEXT, demos)
        # keep the stored joint value in sync with where the user left the object
        jd = _joint(obj)
        jd["value"] = float(final)
        obj["tinker_joint"] = jd
        st.status = f"recorded demonstration {len(demos)} ({len(rec.samples)} samples)"
        return {"FINISHED"}


def _scene_at(snap, sid, value, pose):
    s = json.loads(json.dumps(snap))
    for o in s["objects"]:
        if o["id"] == sid:
            o["pose"] = pose
            o["joints"][0]["value"] = value
    return s


class TINKER_OT_learn(bpy.types.Operator):
    bl_idname = "tinker.learn"
    bl_label = "Learn"
    blocking: BoolProperty(default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        st = _state(context)
        obj = _target(context)
        items = _text_json(_DEMOS_TEXT, [])
        if obj is None or not items:
            self.report({"ERROR"}, "record at least one demonstration first")
            return {"CANCELLED"}
        name = "".join(ch if ch.isalnum() else "-" for ch in obj.name.lower()).strip("-")[:40] or "skill"
        name = (name + "-" + _joint(obj)["name"].lower())[:60]
        scene = items[0]["scene"]
        demos = [it["demo"] for it in items]
        client = _client(context)
        st.status = f"learning from {len(demos)} demonstrations..."

        def done(ctx, res, err):
            s = _state(ctx)
            if err:
                s.status = f"learn failed: {err}"
                return
            sk = res["skill"]
            s.skill_name = sk["name"]
            s.confidence = sk["evaluation"]["confidence"]
            kind = sk["model_ref"]["kind"].replace("_", " ")
            s.status = f"learned {sk['name']} v{sk['version']} ({kind}); confidence {s.confidence:.2f} is a heuristic"
        _run(context, lambda: client.learn(scene, demos, name, use_ml=st.use_ml), done, self.blocking)
        return {"FINISHED"}


class TINKER_OT_simulate(bpy.types.Operator):
    bl_idname = "tinker.simulate"
    bl_label = "Simulate"
    blocking: BoolProperty(default=False, options={"SKIP_SAVE"})

    def execute(self, context):
        st = _state(context)
        obj = _target(context)
        if obj is None or not st.skill_name:
            self.report({"ERROR"}, "learn a skill first")
            return {"CANCELLED"}
        snap = C.snapshot(context)
        j = _joint(obj)
        sid = obj.get("tinker_id", obj.name)
        goal = _goal_value(context, j)
        client = _client(context)

        def done(ctx, res, err):
            s = _state(ctx)
            if err:
                s.status, s.sim_ok = f"simulation failed to run: {err}", False
                return
            sim = res["simulation"]
            _set_text_json(_PLAN_TEXT, {"simulation": sim, "preview": res["preview"], "target": obj.name})
            s.sim_ok = bool(sim["success"])
            m = sim["metrics"]
            if s.sim_ok:
                s.sim_summary = f"passed ({m.get('method', '?')}); goal error {m.get('goal_error', 0):.4f}"
            else:
                s.sim_summary = "failed: " + "; ".join(v["code"] for v in sim["violations"])
            s.status = "simulation " + s.sim_summary
        _run(context, lambda: client.plan(snap, st.skill_name, sid, j["name"], goal), done, self.blocking)
        return {"FINISHED"}


def _ghost(context, create=True):
    g = context.scene.objects.get(GHOST)
    if g is None and create:
        obj = _target(context)
        g = bpy.data.objects.new(GHOST, obj.data)  # linked duplicate: no geometry copied, never rendered
        g.display_type = "WIRE"
        g.hide_render = True
        g.hide_select = True
        context.scene.collection.objects.link(g)
        g.matrix_world = obj.matrix_world.copy()
    return g


def _update_ghost(context):
    plan = _text_json(_PLAN_TEXT, None)
    g = _ghost(context, create=False)
    if not plan or g is None or not plan["preview"]:
        return
    i = min(_state(context).preview_frame, len(plan["preview"]) - 1)
    C.set_object_pose(g, plan["preview"][i]["pose"])


class TINKER_OT_preview(bpy.types.Operator):
    bl_idname = "tinker.preview"
    bl_label = "Preview"
    bl_description = "Show the simulated motion as a wireframe ghost; the object itself does not move"

    def execute(self, context):
        st = _state(context)
        plan = _text_json(_PLAN_TEXT, None)
        if not plan or not st.sim_ok:
            self.report({"ERROR"}, "run a successful simulation first")
            return {"CANCELLED"}
        _ghost(context)
        st.preview_frame = len(plan["preview"]) - 1
        _update_ghost(context)
        st.status = "previewing: scrub the frame slider, then Apply or Clear"
        return {"FINISHED"}


class TINKER_OT_clear_preview(bpy.types.Operator):
    bl_idname = "tinker.clear_preview"
    bl_label = "Clear preview"

    def execute(self, context):
        g = _ghost(context, create=False)
        if g is not None:
            bpy.data.objects.remove(g, do_unlink=True)
        return {"FINISHED"}


class TINKER_OT_apply(bpy.types.Operator):
    bl_idname = "tinker.apply"
    bl_label = "Apply"
    bl_description = "Apply the simulated end state to the object as one undoable step"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)  # explicit confirmation in the UI

    def execute(self, context):
        st = _state(context)
        plan = _text_json(_PLAN_TEXT, None)
        obj = _target(context)
        if not plan or not st.sim_ok or obj is None or plan.get("target") != obj.name:
            self.report({"ERROR"}, "nothing approved to apply: simulate and preview first")
            return {"CANCELLED"}
        before = {"name": obj.name, "matrix": [list(r) for r in obj.matrix_world], "joint": _joint(obj)}
        _set_text_json(_UNDO_TEXT, before)
        final = plan["preview"][-1]
        C.set_object_pose(obj, final["pose"])
        jd = _joint(obj)
        jd["value"] = float(final["value"])
        obj["tinker_joint"] = jd
        bpy.ops.tinker.clear_preview()
        try:
            bpy.ops.ed.undo_push(message="tinker apply")
        except RuntimeError:
            pass  # no undo stack in background mode; tinker's own Undo below still works
        st.sim_ok = False
        st.status = f"applied: {obj.name} {jd['name']} = {jd['value']:.4f}"
        return {"FINISHED"}


class TINKER_OT_undo(bpy.types.Operator):
    bl_idname = "tinker.undo"
    bl_label = "Undo"

    def execute(self, context):
        from mathutils import Matrix
        before = _text_json(_UNDO_TEXT, None)
        obj = context.scene.objects.get(before["name"]) if before else None
        if obj is None:
            self.report({"WARNING"}, "nothing to undo")
            return {"CANCELLED"}
        obj.matrix_world = Matrix(before["matrix"])
        obj["tinker_joint"] = before["joint"]
        _set_text_json(_UNDO_TEXT, None)
        try:
            bpy.ops.ed.undo_push(message="tinker undo")
        except RuntimeError:
            pass
        _state(context).status = f"undid the last tinker apply on {obj.name}"
        return {"FINISHED"}


class TINKER_OT_start_service(bpy.types.Operator):
    bl_idname = "tinker.start_service"
    bl_label = "Start local service"

    def execute(self, context):
        p = _prefs(context)
        py = p.service_python if p else ""
        if not py or not os.path.isfile(py):
            self.report({"ERROR"}, "set 'Service Python' in the add-on preferences (the installer does this)")
            return {"CANCELLED"}
        subprocess.Popen([py, "-m", "tinker_service.http", "--port", str(p.port)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        _state(context).status = "starting tinker service..."
        return {"FINISHED"}


class TINKER_PT_panel(bpy.types.Panel):
    bl_label = "tinker"
    bl_idname = "TINKER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "tinker"

    def draw(self, context):
        st = _state(context)
        L = self.layout
        L.label(text="the learning + doing machine")
        box = L.box()
        box.label(text=st.status, icon="INFO")
        if st.busy:
            box.progress(factor=st.progress, text="working...")
        col = L.column(align=True)
        col.enabled = not st.busy
        col.operator("tinker.select", icon="RESTRICT_SELECT_OFF")
        row = col.row(align=True)
        row.operator("tinker.record", icon="REC", depress=st.recording)
        row.operator("tinker.stop", icon="SNAP_FACE")
        col.prop(st, "use_ml")
        col.operator("tinker.learn", icon="OUTLINER_OB_FORCE_FIELD")
        if st.skill_name:
            col.label(text=f"skill {st.skill_name}  confidence {st.confidence:.2f} (heuristic)")
        col.prop(st, "goal")
        col.operator("tinker.simulate", icon="PHYSICS")
        if st.sim_summary:
            col.label(text=st.sim_summary, icon="CHECKMARK" if st.sim_ok else "ERROR")
        row = col.row(align=True)
        row.operator("tinker.preview", icon="HIDE_OFF")
        row.operator("tinker.clear_preview", icon="X", text="")
        col.prop(st, "preview_frame", slider=True)
        col.operator("tinker.apply", icon="CHECKMARK")
        col.operator("tinker.undo", icon="LOOP_BACK")
        L.operator("tinker.start_service", icon="PLAY")
        if HP is not None:
            HP.draw_hunch_section(L, context)


CLASSES = (TinkerPrefs, TinkerState, TINKER_OT_select, TINKER_OT_record, TINKER_OT_stop, TINKER_OT_learn, TINKER_OT_simulate,
           TINKER_OT_preview, TINKER_OT_clear_preview, TINKER_OT_apply, TINKER_OT_undo, TINKER_OT_start_service)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.tinker = PointerProperty(type=TinkerState)
    if C.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(C.on_depsgraph_update)
    if HP is not None:
        HP.register()
    if TP is not None:
        TP.register()


def unregister():
    if TP is not None:
        TP.unregister()
    if HP is not None:
        HP.unregister()
    if C.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(C.on_depsgraph_update)
    del bpy.types.Scene.tinker
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
