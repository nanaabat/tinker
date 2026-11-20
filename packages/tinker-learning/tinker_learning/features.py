"""Shared feature/rollout definitions for training (torch) and inference (onnxruntime / numpy)."""
from __future__ import annotations

import math

import numpy as np

STEPS = 50          # rollout steps over normalized phase
DUR_SCALE = 10.0    # seconds; duration target = log(T / DUR_SCALE)


def features(phase: float, progress: float, dist_norm: float) -> list[float]:
    return [phase, progress, dist_norm]


def rollout(predict, start: float, goal: float, span: float):
    """predict(np.ndarray[n,3]) -> np.ndarray[n,2] (dprogress*STEPS, log duration). Returns (ts, values, raw_end_progress)."""
    d = abs(goal - start) / span
    p = 0.0
    out_p = [0.0]
    dur = None
    for k in range(STEPS):
        y = predict(np.array([features(k / STEPS, p, d)], dtype=np.float32))[0]
        if dur is None:
            dur = DUR_SCALE * math.exp(float(y[1]))
        p = min(1.2, max(-0.2, p + float(y[0]) / STEPS))
        out_p.append(p)
    raw_end = out_p[-1]
    ts = [dur * k / STEPS for k in range(STEPS + 1)]
    vals = [start + (goal - start) * x for x in out_p]
    if abs(raw_end - 1.0) > 1e-4:  # terminal settle segment to the exact goal; error is reported, not hidden
        ts.append(ts[-1] + max(0.05, dur * abs(1.0 - raw_end)))
        vals.append(goal)
    return ts, vals, raw_end
