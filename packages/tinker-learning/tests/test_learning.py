import copy
import json
import math

import numpy as np
import pytest

from tw_connector import MockHost
from tw_contracts import validate
from tw_fixtures import BLIND_ID, PANEL_ID, room_scene
from tinker_learning import (BCPolicy, InvalidDemonstration, ModelRegistry, ParametricTemplate, Recorder, RegistryError,
                             SkillRuntime, demo_series, replay)
from tinker_learning.pipeline import learn_skill, retrain_with_corrections


# ---------------- recorder
def _record(host, scene, fn, **kw):
    rec = Recorder(scene, PANEL_ID, "slide", **kw)
    unsub = host.subscribe_changes(rec.on_change)
    rec.start()
    fn()
    unsub()
    return rec.stop()


def test_recorder_rate_limits_samples_but_keeps_edits():
    s = room_scene()
    h = MockHost(s)

    def move():
        for k in range(1000):  # 1 kHz host events
            h.user_set_joint(PANEL_ID, "slide", k / 1000, t=k / 1000, event="sample")
        h.user_set_joint(PANEL_ID, "slide", 1.0, t=1.0005, event="edit")
    d = _record(h, s, move, min_interval=0.02)
    validate("Demonstration", d)
    n = len(d["samples"])
    assert 45 <= n <= 55, n
    assert d["samples"][-1]["event"] == "edit"
    assert d["goal"]["target_value"] == pytest.approx(1.0)


def test_recorder_ignores_other_objects_and_records_undo_redo():
    s = room_scene()
    h = MockHost(s)

    def move():
        h.user_set_joint(PANEL_ID, "slide", 0.0, t=0, event="sample")
        h.user_set_joint(BLIND_ID, "tilt", 0.5, t=0.1)  # edit to another object during recording
        h.user_set_joint(PANEL_ID, "slide", 0.8, t=0.5)
        h.user_set_joint(PANEL_ID, "slide", 0.0, t=0.6, event="undo")
        h.user_set_joint(PANEL_ID, "slide", 0.8, t=0.7, event="redo")
    d = _record(h, s, move)
    assert [x["event"] for x in d["samples"]] == ["sample", "edit", "undo", "redo"]
    assert all(list(x["poses"]) == [PANEL_ID] for x in d["samples"])
    ts, vs = demo_series(d, s)
    assert vs[-1] == pytest.approx(0.8)


def test_empty_demonstration_rejected():
    s = room_scene()
    with pytest.raises(InvalidDemonstration):
        _record(MockHost(s), s, lambda: None)


def test_no_motion_and_bad_time_rejected(demos, scene):
    still = copy.deepcopy(demos[0])
    for x in still["samples"]:
        x["poses"] = still["samples"][0]["poses"]
    with pytest.raises(InvalidDemonstration):
        demo_series(still, scene)
    back = copy.deepcopy(demos[0])
    back["samples"][3]["t"] = -1 if False else back["samples"][1]["t"] - 0.5
    with pytest.raises(InvalidDemonstration):
        demo_series(back, scene)


def test_recorder_state_errors(scene):
    r = Recorder(scene, PANEL_ID, "slide")
    with pytest.raises(RuntimeError):
        r.stop()
    r.start()
    with pytest.raises(RuntimeError):
        r.start()


# ---------------- baseline
def test_replay_is_exact(demos, scene):
    ts, vs = demo_series(demos[0], scene)
    tr = replay(ts, vs, BLIND_ID, "tilt")
    assert tr.value == vs and tr.t == [t - ts[0] for t in ts]
    for t, v in zip(ts, vs):
        assert tr.value_at(t - ts[0]) == v


def test_template_hits_goal_and_roundtrips(demos, scene):
    tpl = ParametricTemplate().fit([demo_series(d, scene) for d in demos])
    tr = tpl.generate(BLIND_ID, "tilt", 1.2, 0.3)
    assert tr.value[0] == pytest.approx(1.2) and tr.value[-1] == pytest.approx(0.3)
    again = ParametricTemplate.from_fallback(json.loads(json.dumps(tpl.as_fallback())))
    assert again.generate(BLIND_ID, "tilt", 1.2, 0.3).value == pytest.approx(tr.value, abs=1e-5)


# ---------------- ML
@pytest.mark.slow
def test_bc_beats_baseline_on_holdout(trained):
    _, res = trained
    ev = res["skill"]["evaluation"]
    assert res["skill"]["model_ref"]["kind"] == "behavior_cloning_onnx"
    assert ev["model_holdout_rmse"] < ev["baseline_holdout_rmse"] * 0.5, ev
    assert ev["model_val_rmse"] < ev["baseline_val_rmse"], ev


@pytest.mark.slow
def test_training_is_reproducible(scene, demos):
    from tinker_learning import bc
    from tinker_learning.pipeline import split
    series = [demo_series(d, scene) for d in demos]
    tr, va = split(series, seed=0)
    a, _ = bc.train(tr, va, math.radians(83), seed=0, epochs=150)
    b, _ = bc.train(tr, va, math.radians(83), seed=0, epochs=150)
    c, _ = bc.train(tr, va, math.radians(83), seed=1, epochs=150)
    assert bc.state_hash(a) == bc.state_hash(b) != bc.state_hash(c)


@pytest.mark.slow
def test_checkpoint_restore_and_onnx_match(trained, tmp_path):
    from tinker_learning import bc
    reg, res = trained
    skill = res["skill"]
    v = skill["version"]
    model, meta = bc.load_checkpoint(reg.root / "blind-tilt" / f"v{v}" / "model.pt")
    x = np.random.default_rng(0).random((64, 3)).astype(np.float32)
    y_restored = bc.torch_predict(model)(x)
    y_orig = res["predict"](x)
    y_onnx = BCPolicy(reg.resolve(skill["model_ref"]["path"], expect_sha256=skill["model_ref"]["sha256"]))(x)
    assert np.allclose(y_restored, y_orig, atol=1e-7)
    assert np.allclose(y_onnx, y_orig, atol=1e-5)


@pytest.mark.slow
def test_runtime_uses_onnx_inside_range_and_template_outside(trained, scene):
    reg, res = trained
    rt = SkillRuntime(res["skill"], reg)
    j = next(o for o in scene["objects"] if o["id"] == BLIND_ID)["joints"][0]
    lo, hi = res["skill"]["preconditions"]["value_range"]
    tr, info = rt.generate(BLIND_ID, j, hi - 0.05, lo + 0.05)
    assert info["method"] == "behavior_cloning_onnx" and tr.value[-1] == pytest.approx(lo + 0.05)
    narrow = copy.deepcopy(res["skill"])
    narrow["preconditions"]["value_range"] = [0.5, 0.9]
    tr2, info2 = SkillRuntime(narrow, reg).generate(BLIND_ID, j, 0.1, 1.3)
    assert info2["method"] == "template" and info2["confidence"] < res["skill"]["evaluation"]["confidence"]
    ok, why = rt.applicable(j, 0.0, 2.0)
    assert not ok


def test_baseline_only_skill_without_torch_model(scene, demos, tmp_path):
    reg = ModelRegistry(tmp_path)
    res = learn_skill(scene, demos[:6], name="blind-baseline", registry=reg, use_ml=False)
    assert res["skill"]["model_ref"]["kind"] == "parametric_template" and res["skill"]["model_ref"]["path"] is None
    validate("Skill", res["skill"])


# ---------------- registry
def test_registry_versions_rollback_and_traversal(tmp_path, trained):
    _, res = trained
    reg = ModelRegistry(tmp_path)
    v1 = reg.register("blind-tilt", res["skill"], res["files"])
    v2 = reg.register("blind-tilt", res["skill"], res["files"])
    assert (v1, v2) == (1, 2) and reg.active_version("blind-tilt") == 2
    assert reg.rollback("blind-tilt") == 1 and reg.active_version("blind-tilt") == 1
    with pytest.raises(RegistryError):
        reg.rollback("blind-tilt")
    for bad in ["../x", "/etc/passwd", "blind-tilt/../../x", "a\\b"]:
        with pytest.raises(RegistryError):
            reg.resolve(bad)
    with pytest.raises(RegistryError):
        reg.register("../evil", res["skill"], {})
    # tampered model is refused
    p = reg.resolve("blind-tilt/v1/model.onnx")
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(RegistryError):
        reg.resolve("blind-tilt/v1/model.onnx", expect_sha256=reg.load_skill("blind-tilt", 1)["model_ref"]["sha256"])


@pytest.mark.slow
def test_corrections_need_approval_and_compare(tmp_path, scene, demos):
    reg = ModelRegistry(tmp_path)
    learn_skill(scene, demos[:20], name="blind-tilt", registry=reg, epochs=300)
    with pytest.raises(PermissionError):
        retrain_with_corrections(scene, demos[:20], demos[20:], name="blind-tilt", registry=reg, approval=None)
    with pytest.raises(PermissionError):
        retrain_with_corrections(scene, demos[:20], demos[20:], name="blind-tilt", registry=reg,
                                 approval={"user_id": "u", "approved": "yes"})
    out = retrain_with_corrections(scene, demos[:20], demos[20:], name="blind-tilt", registry=reg,
                                   approval={"user_id": "tester", "approved": True}, epochs=300)
    assert out["version"] == 2 and out["previous_version"] == 1
    assert reg.active_version("blind-tilt") == (2 if out["activated"] else 1)
    assert "new_val_rmse" in out and "previous_val_rmse" in out
    reg.activate("blind-tilt", 2)
    assert reg.rollback("blind-tilt") == 1
