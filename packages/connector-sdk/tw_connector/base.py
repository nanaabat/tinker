from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


class ConnectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Capabilities:
    host: str
    host_version: str
    joint_kinds: frozenset[str] = frozenset({"prismatic", "revolute"})
    object_types: frozenset[str] = frozenset({"wall", "window", "blind", "sliding_panel", "generic"})
    features: frozenset[str] = field(default_factory=lambda: frozenset(
        {"get_scene", "subscribe_changes", "record", "preview", "apply", "undo"}))
    units: str = "m"
    up: str = "z"

    def as_dict(self) -> dict:
        return {"host": self.host, "host_version": self.host_version, "joint_kinds": sorted(self.joint_kinds),
                "object_types": sorted(self.object_types), "features": sorted(self.features), "units": self.units, "up": self.up}


def negotiate(caps: Capabilities, skill: dict) -> tuple[bool, list[str]]:
    """Can this host run this skill? Returns (ok, reasons). No promise of cross-host transfer beyond these checks."""
    reasons = []
    pre = skill["preconditions"]
    if pre["joint_kind"] not in caps.joint_kinds:
        reasons.append(f"host does not support {pre['joint_kind']} joints")
    if not set(skill["target_types"]) & set(caps.object_types):
        reasons.append("host exposes none of the skill's target object types")
    missing = set(pre.get("required_capabilities", [])) - set(caps.features)
    if missing:
        reasons.append("host lacks capabilities: " + ", ".join(sorted(missing)))
    return (not reasons, reasons)


class HostConnector(ABC):
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def get_scene(self) -> dict:
        """Return a SceneSnapshot document."""

    @abstractmethod
    def subscribe_changes(self, callback: Callable[[str, dict, float, str], None]) -> Callable[[], None]:
        """callback(object_id, pose, t, event). Returns an unsubscribe function."""

    @abstractmethod
    def begin_demonstration(self, object_id: str, joint: str): ...

    @abstractmethod
    def preview_transforms(self, frames: list[dict]) -> str:
        """Show a non-destructive preview. Returns a preview handle."""

    @abstractmethod
    def clear_preview(self, handle: str) -> None: ...

    @abstractmethod
    def apply_transforms(self, moves: list[dict]) -> str:
        """Apply final joint values [{object_id, joint, value}] as ONE undoable step. Returns an undo ref."""

    @abstractmethod
    def undo(self, undo_ref: str) -> None: ...

    @abstractmethod
    def map_object_ids(self) -> dict[str, str]:
        """host id -> semantic id"""
