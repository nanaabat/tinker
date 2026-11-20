from __future__ import annotations

import re
import uuid

_NS = uuid.UUID("6f1d3c3e-7a0b-4c55-9a51-2b7d8f1e0c11")
_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def semantic_id(host: str, document_id: str, host_object_id: str, kind: str = "obj") -> str:
    """Stable id: same host object in same document always maps to the same id, across sessions."""
    u = uuid.uuid5(_NS, f"{host}\x1f{document_id}\x1f{host_object_id}")
    return f"{kind}-{u.hex[:20]}"


class IdMap:
    """Bidirectional host-id <-> semantic-id map for one document."""

    def __init__(self, host: str, document_id: str):
        self.host, self.document_id = host, document_id
        self._to_sem: dict[str, str] = {}
        self._to_host: dict[str, str] = {}

    def add(self, host_object_id: str, preferred: str | None = None) -> str:
        if host_object_id in self._to_sem:
            return self._to_sem[host_object_id]
        sid = preferred if preferred and _OK.match(preferred) and preferred not in self._to_host else \
            semantic_id(self.host, self.document_id, host_object_id)
        self._to_sem[host_object_id] = sid
        self._to_host[sid] = host_object_id
        return sid

    def semantic(self, host_object_id: str) -> str:
        return self._to_sem[host_object_id]

    def host_id(self, sid: str) -> str:
        return self._to_host[sid]

    def as_dict(self) -> dict[str, str]:
        return dict(self._to_sem)
