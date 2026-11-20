"""Deterministic baseline. Not machine learning: exact replay plus a time-normalized, goal-scaled template."""
from __future__ import annotations

from tw_action import Trajectory

GRID = 65


def _interp(xs, ys, x):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if xs[m] <= x:
            lo = m
        else:
            hi = m
    a = (x - xs[lo]) / ((xs[hi] - xs[lo]) or 1.0)
    return ys[lo] + a * (ys[hi] - ys[lo])


def normalize(ts, vs):
    """Return (phase, progress) on a fixed grid, plus duration and signed distance."""
    t0, T = ts[0], ts[-1] - ts[0]
    v0, dist = vs[0], vs[-1] - vs[0]
    ph = [(t - t0) / T for t in ts]
    pr = [(v - v0) / dist for v in vs]
    grid = [i / (GRID - 1) for i in range(GRID)]
    return grid, [_interp(ph, pr, g) for g in grid], T, dist


def replay(ts, vs, object_id, joint) -> Trajectory:
    """Exact deterministic replay of a recorded series."""
    t0 = ts[0]
    return Trajectory(object_id, joint, [t - t0 for t in ts], list(vs))


class ParametricTemplate:
    """Goal-conditioned template: mean normalized progress curve, duration = distance / mean speed."""

    def __init__(self, phase=None, progress=None, mean_speed=None):
        self.phase, self.progress, self.mean_speed = phase, progress, mean_speed

    def fit(self, series: list[tuple[list[float], list[float]]]) -> "ParametricTemplate":
        if not series:
            raise ValueError("need at least one demonstration")
        curves, speeds = [], []
        for ts, vs in series:
            grid, pr, T, dist = normalize(ts, vs)
            curves.append(pr)
            speeds.append(abs(dist) / T)
        self.phase = grid
        self.progress = [sum(c[i] for c in curves) / len(curves) for i in range(len(grid))]
        self.progress[0], self.progress[-1] = 0.0, 1.0
        self.mean_speed = sum(speeds) / len(speeds)
        return self

    def generate(self, object_id, joint, start, goal, steps: int = 64) -> Trajectory:
        T = max(abs(goal - start) / self.mean_speed, 1e-3)
        ts = [T * i / steps for i in range(steps + 1)]
        return Trajectory(object_id, joint, ts, [start + (goal - start) * _interp(self.phase, self.progress, t / T) for t in ts])

    def as_fallback(self) -> dict:
        return {"phase": [round(x, 6) for x in self.phase], "progress": [round(x, 6) for x in self.progress],
                "mean_speed": self.mean_speed}

    @classmethod
    def from_fallback(cls, d: dict) -> "ParametricTemplate":
        return cls(list(d["phase"]), list(d["progress"]), float(d["mean_speed"]))
