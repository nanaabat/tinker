"""Learn -> evaluate -> register. Compares behavior cloning against the deterministic baseline on held-out demos."""
from __future__ import annotations

import json
import math
import random
import tempfile
from pathlib import Path

from tw_scene import find_joint, find_object

from .baseline import ParametricTemplate, _interp
from .features import rollout
from .recorder import demo_series


def traj_rmse(gen_ts, gen_vs, ts, vs, span) -> float:
    """RMSE of generated vs demonstrated joint value on the demo's timestamps, normalized by joint range."""
    t0 = ts[0]
    err = [(_interp(gen_ts, gen_vs, t - t0) - v) / span for t, v in zip(ts, vs)]
    return math.sqrt(sum(e * e for e in err) / len(err))


def split(items, *, seed=0, val_frac=0.25):
    idx = list(range(len(items)))
    random.Random(seed).shuffle(idx)
    nv = max(1, int(round(len(items) * val_frac))) if len(items) > 1 else 0
    return [items[i] for i in idx[nv:]], [items[i] for i in idx[:nv]]


def evaluate(template, predict, series, span):
    b, m = [], []
    for ts, vs in series:
        g = template.generate("x", "j", vs[0], vs[-1])
        b.append(traj_rmse(g.t, g.value, ts, vs, span))
        if predict is not None:
            gts, gvs, _ = rollout(predict, vs[0], vs[-1], span)
            m.append(traj_rmse(gts, gvs, ts, vs, span))
    mean = lambda x: (sum(x) / len(x)) if x else None
    return mean(b), mean(m)


def learn_skill(snapshot, demos, *, name, registry=None, holdout=None, seed=0, epochs=800, use_ml=True,
                progress_cb=None) -> dict:
    """Returns {skill, metrics, files}. Registers a new version if a registry is given."""
    oid, jn = demos[0]["goal"]["object_id"], demos[0]["goal"]["joint"]
    obj = find_object(snapshot, oid)
    j = find_joint(obj, jn)
    span = j["upper"] - j["lower"]
    series = [demo_series(d, snapshot) for d in demos]
    tr, va = split(series, seed=seed)
    template = ParametricTemplate().fit(tr)
    hold = [demo_series(d, snapshot) for d in (holdout or [])]
    files, history, predict = {}, [], None
    tmp = Path(tempfile.mkdtemp(prefix="tinker-learn-"))
    if use_ml:
        from . import bc
        model, history = bc.train(tr, va, span, seed=seed, epochs=epochs, progress_cb=progress_cb)
        predict = bc.torch_predict(model)
        bc.save_checkpoint(model, tmp / "model.pt", {"hidden": 64, "seed": seed, "epochs": epochs, "span": span})
        bc.export_onnx(model, tmp / "model.onnx")
        files = {"model.pt": tmp / "model.pt", "model.onnx": tmp / "model.onnx"}
    b_val, m_val = evaluate(template, predict, va, span)
    b_hold, m_hold = evaluate(template, predict, hold, span) if hold else (None, None)
    best = min(x for x in (b_val, m_val) if x is not None)
    confidence = max(0.05, min(0.95, 1.0 - 8.0 * best))
    use_model = use_ml and m_val is not None and m_val <= b_val
    vals = [v for _, vs in series for v in (vs[0], vs[-1])]
    skill = {
        "schema_version": "1.0.0", "id": f"skill-{name}", "version": 1, "name": name,
        "target_types": [obj["type"] if obj["type"] in ("wall", "window", "blind", "sliding_panel") else "generic"],
        "preconditions": {"joint_kind": j["kind"], "value_range": [min(vals), max(vals)],
                          "required_capabilities": ["preview", "apply", "undo"]},
        "model_ref": {"kind": "behavior_cloning_onnx" if use_model else "parametric_template", "path": None, "sha256": None},
        "fallback_trajectory": template.as_fallback(),
        "limits": {"max_speed": j["max_speed"], "max_force": j["max_force"]},
        "evaluation": {"demonstrations": len(demos), "baseline_val_rmse": b_val, "model_val_rmse": m_val,
                       "baseline_holdout_rmse": b_hold, "model_holdout_rmse": m_hold, "confidence": round(confidence, 3),
                       "note": ("confidence is 1 - 8 x best validation RMSE (normalized by joint range), clipped; "
                                "a heuristic, not a calibrated probability. demonstrations: "
                                + ("scripted" if all(d["context"].get("source") == "scripted" for d in demos) else "recorded"))},
    }
    if not use_model:
        files = {}
    out = {"skill": skill, "history": history, "files": files, "predict": predict, "template": template}
    if registry is not None:
        v = registry.register(name, skill, files)
        out["skill"] = registry.load_skill(name, v)
    return out


def retrain_with_corrections(snapshot, demos, corrections, *, name, registry, approval: dict | None, seed=0, epochs=800,
                             holdout=None):
    """Append correction demos and retrain. Requires an explicit approval {user_id, approved: True}.
    The new version is activated only if it does not regress validation RMSE versus the previous version."""
    if not approval or approval.get("approved") is not True or not approval.get("user_id"):
        raise PermissionError("retraining with corrections requires explicit user approval")
    prev = registry.load_skill(name)
    res = learn_skill(snapshot, list(demos) + list(corrections), name=name, registry=None, seed=seed, epochs=epochs,
                      holdout=holdout)
    new = res["skill"]
    prev_score = min(x for x in (prev["evaluation"]["model_val_rmse"], prev["evaluation"]["baseline_val_rmse"]) if x is not None)
    new_score = min(x for x in (new["evaluation"]["model_val_rmse"], new["evaluation"]["baseline_val_rmse"]) if x is not None)
    improved = new_score <= prev_score * 1.05
    v = registry.register(name, new, res["files"], activate=improved)
    return {"version": v, "activated": improved, "previous_version": prev["version"], "previous_val_rmse": prev_score,
            "new_val_rmse": new_score}
