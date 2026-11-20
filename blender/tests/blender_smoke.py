"""Runs INSIDE a real Blender process (background mode). Installs the built extension, builds the fixture room,
records demonstrations by moving the blind (depsgraph handler, real time), then Learn -> Simulate -> Preview ->
Apply -> Undo through the add-on's operators, talking to a real tinker-service over loopback.
usage: blender -b --factory-startup --python blender_smoke.py -- ZIP FIXTURE_JSON PORT TOKEN_FILE OUT_JSON"""
import json
import math
import sys
import time
import traceback

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
ZIP, FIXTURE, PORT, TOKEN, OUT = argv[0], argv[1], int(argv[2]), argv[3], argv[4]
res = {"blender": bpy.app.version_string, "checks": {}, "errors": []}


def check(name, cond, detail=""):
    res["checks"][name] = {"ok": bool(cond), "detail": str(detail)[:400]}


try:
    bpy.ops.extensions.package_install_files(filepath=ZIP, repo="user_default", enable_on_install=True)
    import importlib
    mod_name = next(m for m in bpy.context.preferences.addons.keys() if m.endswith("tinker_blender"))
    check("extension_installed_and_enabled", True, mod_name)
    prefs = bpy.context.preferences.addons[mod_name].preferences
    prefs.port, prefs.token_file = PORT, TOKEN
    check("panel_registered", hasattr(bpy.types, "TINGLE_PT_panel"), "tingle panel")
    tb = importlib.import_module(mod_name)
    C = tb.C

    snap = json.load(open(FIXTURE))
    # start with an empty scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    ctx = bpy.context
    made = C.build_from_snapshot(ctx, snap)
    check("fixture_built", len(made) == len(snap["objects"]), len(made))

    # cross-host contract: Blender's snapshot of the fixture equals the source snapshot
    bsnap = C.snapshot(ctx)
    src = {o["id"]: o for o in snap["objects"]}
    worst = 0.0
    for o in bsnap["objects"]:
        s = src[o["id"]]
        worst = max(worst, max(abs(a - b) for a, b in zip(o["pose"]["position"] + o["size"], s["pose"]["position"] + s["size"])))
        qa, qb = o["pose"]["rotation"], s["pose"]["rotation"]
        dotq = abs(sum(a * b for a, b in zip(qa, qb)))
        worst = max(worst, 1 - dotq)
    check("cross_host_snapshot_matches", worst < 1e-5 and len(bsnap["objects"]) == len(snap["objects"]), f"max error {worst:.2e}")
    res["blender_snapshot"] = bsnap

    blind = next(ob for ob in made.values() if ob.get("tinker_type") == "blind")
    bpy.context.view_layer.objects.active = blind
    blind.select_set(True)
    bpy.ops.tinker.select()
    st = ctx.scene.tinker
    check("select", st.target == blind.name, st.status)

    from importlib import import_module
    ts = import_module(mod_name + "._vendor.tw_scene")
    obj_d = next(o for o in snap["objects"] if o["id"] == blind["tinker_id"])
    jd = obj_d["joints"][0]
    hi = jd["upper"]
    pairs = [(0.2, 1.3), (1.3, 0.4), (0.4, 1.0), (1.0, 0.1), (0.1, 0.8), (0.8, 1.4), (1.4, 0.6), (0.6, 1.2)]
    handler_samples = []
    for k, (a, b) in enumerate(pairs):
        cur = dict(blind["tinker_joint"])["value"]
        # the "user" puts the blind at the start value (outside recording), then demonstrates a move
        C.set_object_pose(blind, ts.pose_for_value(obj_d, jd, a))
        j2 = dict(blind["tinker_joint"]); j2["value"] = a; blind["tinker_joint"] = j2
        ctx.view_layer.update()
        bpy.ops.tinker.record()
        d = abs(b - a) / hi
        T = 0.6 + 1.2 * d
        n = int(T * 30)
        for i in range(1, n + 1):
            ph = i / n
            aa = 1.3 + 2.4 * d
            p = ph ** aa / (ph ** aa + (1 - ph) ** aa) if ph < 1 else 1.0
            C.set_object_pose(blind, ts.pose_for_value(obj_d, jd, a + (b - a) * p))
            ctx.view_layer.update()  # fires depsgraph_update_post -> tinker handler samples the pose
            time.sleep(T / n)
        handler_samples.append(len(C.Recorder.active.samples))
        bpy.ops.tinker.stop()
    demos = json.loads(bpy.data.texts["tinker_demos.json"].as_string())
    check("recorded_via_depsgraph_handler", len(demos) == len(pairs) and min(handler_samples) >= 10, handler_samples)
    goals = [round(it["demo"]["goal"]["target_value"], 4) for it in demos]
    check("demo_goals_match_moves", all(abs(g - b) < 1e-3 for g, (_, b) in zip(goals, pairs)), goals)

    t0 = time.time()
    bpy.ops.tinker.learn(blocking=True)
    check("learn", bool(st.skill_name), f"{st.status} ({time.time() - t0:.1f}s)")
    res["learn_status"] = st.status

    st.goal = 30.0  # degrees
    bpy.ops.tinker.simulate(blocking=True)
    check("simulate", st.sim_ok, st.status)
    before = [list(r) for r in blind.matrix_world]
    bpy.ops.tinker.preview()
    ghost = ctx.scene.objects.get(tb.GHOST)
    check("preview_ghost_and_target_unmoved", ghost is not None and [list(r) for r in blind.matrix_world] == before,
          ghost.display_type if ghost else None)
    st.preview_frame = 0
    p0 = ghost.matrix_world.translation.copy()
    st.preview_frame = 23
    p1 = ghost.matrix_world.translation.copy()
    pv = json.loads(bpy.data.texts["tinker_last_plan.json"].as_string())["preview"]
    check("preview_scrub_moves_ghost", (p1 - p0).length > 0.05,
          f"{(p1 - p0).length:.3f} m; frame values {pv[0]['value']:.3f} -> {pv[-1]['value']:.3f}")

    bpy.ops.tinker.apply()  # execute() path; in the UI, invoke() asks for confirmation first
    val = dict(blind["tinker_joint"])["value"]
    after_snap = C.snapshot(ctx)
    ob_after = next(o for o in after_snap["objects"] if o["id"] == blind["tinker_id"])
    v_pose = ts.value_from_pose(obj_d, jd, ob_after["pose"])
    check("apply", abs(val - math.radians(30)) < 1e-6 and abs(v_pose - math.radians(30)) < 1e-4 and ctx.scene.objects.get(tb.GHOST) is None,
          f"joint {val:.5f} pose->value {v_pose:.5f}")
    bpy.ops.tinker.undo()
    check("undo", [list(r) for r in blind.matrix_world] == before and abs(dict(blind["tinker_joint"])["value"] - goals[-1]) < 1e-6,
          dict(blind["tinker_joint"])["value"])

    # impossible goal is refused by simulation, apply is blocked
    st.goal = 120.0
    bpy.ops.tinker.simulate(blocking=True)
    try:
        blocked = bpy.ops.tinker.apply() == {"CANCELLED"}
    except RuntimeError as e:  # operators that report ERROR raise in background mode
        blocked = "nothing approved" in str(e)
    check("impossible_goal_refused", (not st.sim_ok) and blocked, st.status)

    # persistence: demos and plan are stored in the .blend
    path = OUT.replace(".json", ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    check("session_saved_in_blend", "tinker_demos.json" in bpy.data.texts, path)
except Exception:
    res["errors"].append(traceback.format_exc())

json.dump(res, open(OUT, "w"), indent=2)
print("TINKER_SMOKE_DONE", OUT)
