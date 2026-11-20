from __future__ import annotations

import hashlib
import json


def scene_hash(snapshot: dict) -> str:
    """Hash of geometry/joint state used to detect stale scenes between simulate and apply."""
    s = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
