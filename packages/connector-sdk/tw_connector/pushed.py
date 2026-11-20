from __future__ import annotations

import copy

from .base import Capabilities, ConnectorError, HostConnector


class PushedSceneConnector(HostConnector):
    """For hosts that talk to a service over IPC: the host pushes its current SceneSnapshot with each request
    and applies approved edits itself. Direct apply/undo here is refused by design."""

    def __init__(self):
        self.scene: dict | None = None
        self.previews: dict[str, list] = {}
        self._n = 0

    def push(self, scene: dict):
        self.scene = copy.deepcopy(scene)

    def capabilities(self) -> Capabilities:
        h = (self.scene or {}).get("host", {"name": "remote", "version": "?"})
        return Capabilities(host=h["name"], host_version=h["version"])

    def get_scene(self) -> dict:
        if self.scene is None:
            raise ConnectorError("no scene pushed by the host yet")
        return copy.deepcopy(self.scene)

    def subscribe_changes(self, callback):
        return lambda: None

    def begin_demonstration(self, object_id, joint):
        raise ConnectorError("record in the host")

    def preview_transforms(self, frames):
        self._n += 1
        h = f"remote-preview-{self._n}"
        self.previews[h] = frames
        return h

    def clear_preview(self, handle):
        self.previews.pop(handle, None)

    def apply_transforms(self, moves):
        raise ConnectorError("the host applies approved moves itself, then confirms")

    def undo(self, undo_ref):
        raise ConnectorError("undo happens in the host")

    def map_object_ids(self):
        return {o["host_id"]: o["id"] for o in (self.scene or {}).get("objects", [])}
