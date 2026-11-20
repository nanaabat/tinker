"""Behavior cloning over normalized (phase, progress, distance) -> (progress increment, duration). PyTorch, CPU.
Reproducible: fixed seeds, single thread, deterministic algorithms."""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
from pathlib import Path

import numpy as np

from .baseline import _interp
from .features import DUR_SCALE, STEPS, features


def _torch():
    import torch
    return torch


def make_dataset(series, span: float):
    X, Y = [], []
    for ts, vs in series:
        t0, T = ts[0], ts[-1] - ts[0]
        v0, dist = vs[0], vs[-1] - vs[0]
        ph = [(t - t0) / T for t in ts]
        pr = [(v - v0) / dist for v in vs]
        p = [_interp(ph, pr, k / STEPS) for k in range(STEPS + 1)]
        d = abs(dist) / span
        for k in range(STEPS):
            X.append(features(k / STEPS, p[k], d))
            Y.append([(p[k + 1] - p[k]) * STEPS, math.log(T / DUR_SCALE)])
    return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)


def build_model(hidden: int = 64):
    torch = _torch()
    return torch.nn.Sequential(torch.nn.Linear(3, hidden), torch.nn.Tanh(), torch.nn.Linear(hidden, hidden),
                               torch.nn.Tanh(), torch.nn.Linear(hidden, 2))


def train(train_series, val_series, span: float, *, seed: int = 0, epochs: int = 800, lr: float = 3e-3,
          hidden: int = 64, progress_cb=None):
    torch = _torch()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    Xtr, Ytr = make_dataset(train_series, span)
    Xva, Yva = make_dataset(val_series, span) if val_series else (Xtr, Ytr)
    model = build_model(hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    xt, yt = torch.from_numpy(Xtr), torch.from_numpy(Ytr)
    xv, yv = torch.from_numpy(Xva), torch.from_numpy(Yva)
    hist = []
    for ep in range(epochs):
        opt.zero_grad()
        loss = torch.nn.functional.mse_loss(model(xt), yt)
        loss.backward()
        opt.step()
        if ep % 50 == 0 or ep == epochs - 1:
            with torch.no_grad():
                vl = float(torch.nn.functional.mse_loss(model(xv), yv))
            hist.append({"epoch": ep, "train_loss": loss.item(), "val_loss": vl})
            if progress_cb:
                progress_cb(ep + 1, epochs, loss.item(), vl)
    return model, hist


def state_hash(model) -> str:
    h = hashlib.sha256()
    for k, v in model.state_dict().items():
        h.update(k.encode())
        h.update(v.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def save_checkpoint(model, path: Path, meta: dict):
    torch = _torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "meta": meta}, path)


def load_checkpoint(path: Path):
    torch = _torch()
    ck = torch.load(path, map_location="cpu", weights_only=True)  # weights only: no pickled code is executed
    model = build_model(int(ck["meta"].get("hidden", 64)))
    model.load_state_dict(ck["state_dict"])
    model.eval()
    return model, ck["meta"]


def export_onnx(model, path: Path):
    torch = _torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    torch.onnx.export(model, (torch.zeros(1, 3),), str(path), input_names=["x"], output_names=["y"],
                      dynamic_axes={"x": {0: "n"}, "y": {0: "n"}}, opset_version=17, dynamo=False)
    return path


def torch_predict(model):
    torch = _torch()

    def f(x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return model(torch.from_numpy(x)).numpy()
    return f
