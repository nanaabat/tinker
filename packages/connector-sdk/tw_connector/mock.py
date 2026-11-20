from __future__ import annotations

import copy
import itertools
import time
from typing import Callable

from tw_scene import find_joint, find_object, pose_for_value

from .base import Capabilities, ConnectorError, HostConnector


class MockHost(HostConnector):
    """In-memory host used by tests and the headless demo. Has a real undo stack and failure injection."""

    def __init__(self, snapshot: dict, *, clock: Callable[[], float] = time.monotonic, fail_apply_after: int | None = None):
        self._scene = copy.deepcopy(snapshot)
        self._subs: list[Callable] = []
        self._undo: dict[str, list[tuple[str, dict, dict]]] = {}
        self._redo: list[str] = []
        self._ids = itertools.count(1)
        self.previews: dict[str, list[dict]] = {}
        self.clock = clock
        self.fail_apply_after = fail_apply_after
        self.applied_count = 0

    def capabilities(self) -> Capabilities:
        return Capabilities(host="mock", host_version="0.1.0", units=self._scene["units"], up=self._scene["coordinate_system"]["up"])

    def get_scene(self) -> dict:
        return copy.deepcopy(self._scene)

    def subscribe_changes(self, callback):
        self._subs.append(callback)
        return lambda: self._subs.remove(callback) if callback in self._subs else None

    def begin_demonstration(self, object_id: str, joint: str):
        find_joint(find_object(self._scene, object_id), joint)  # raises KeyError if missing
        return {"object_id": object_id, "joint": joint, "t0": self.clock()}

    # ---- "user moves the object with host tools"
    def user_set_joint(self, object_id: str, joint: str, value: float, *, t: float | None = None, event: str = "edit"):
        o = find_object(self._scene, object_id)
        j = find_joint(o, joint)
        o["pose"] = pose_for_value(o, j, value)
        j["value"] = float(value)
        stamp = self.clock() if t is None else t
        for cb in list(self._subs):
            cb(object_id, copy.deepcopy(o["pose"]), stamp, event)

    def preview_transforms(self, frames: list[dict]) -> str:
        h = f"preview-{next(self._ids)}"
        self.previews[h] = copy.deepcopy(frames)
        return h

    def clear_preview(self, handle: str) -> None:
        self.previews.pop(handle, None)

    def apply_transforms(self, moves: list[dict]) -> str:
        ref = f"undo-{next(self._ids)}"
        record = []
        try:
            for m in moves:
                if self.fail_apply_after is not None and self.applied_count >= self.fail_apply_after:
                    raise ConnectorError("injected host failure during apply")
                o = find_object(self._scene, m["object_id"])
                j = find_joint(o, m["joint"])
                record.append((o["id"], copy.deepcopy(o["pose"]), {"joint": j["name"], "value": j["value"]}))
                o["pose"] = pose_for_value(o, j, m["value"])
                j["value"] = float(m["value"])
                self.applied_count += 1
        except Exception:
            self._undo[ref] = record
            self.undo(ref)  # host-level atomicity: roll back the partial step
            raise
        self._undo[ref] = record
        return ref

    def undo(self, undo_ref: str) -> None:
        record = self._undo.pop(undo_ref, None)
        if record is None:
            raise ConnectorError(f"unknown undo ref {undo_ref}")
        for oid, pose, jv in reversed(record):
            o = find_object(self._scene, oid)
            o["pose"] = pose
            find_joint(o, jv["joint"])["value"] = jv["value"]

    def map_object_ids(self) -> dict[str, str]:
        return {o["host_id"]: o["id"] for o in self._scene["objects"]}
