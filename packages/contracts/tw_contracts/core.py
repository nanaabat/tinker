from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from importlib import resources
from typing import Any, Callable

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "1.0.0"
KINDS = ("SceneSnapshot", "Demonstration", "Skill", "GoalProposal", "SimulationResult",
         "ActionApproval", "ActionReceipt")
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32


class ContractError(ValueError):
    """A document failed strict validation."""


class VersionMismatch(ContractError):
    """A document's schema_version cannot be read or migrated by this build."""


@lru_cache(maxsize=None)
def load_schema(kind: str) -> dict:
    if kind not in KINDS:
        raise ContractError(f"unknown contract kind {kind!r}")
    text = resources.files("tw_contracts").joinpath("schemas", f"{kind}.schema.json").read_text("utf-8")
    return json.loads(text)


@lru_cache(maxsize=None)
def _validator(kind: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(kind), format_checker=FormatChecker())


def _parse_version(v: Any) -> tuple[int, int, int]:
    if not isinstance(v, str):
        raise VersionMismatch("schema_version is missing or not a string")
    try:
        a, b, c = (int(p) for p in v.split("."))
    except ValueError as e:
        raise VersionMismatch(f"schema_version {v!r} is not semver") from e
    return a, b, c


# Migrations are pure data transforms keyed by (kind, from_major). Never executable payloads.
def _scene_0_to_1(d: dict) -> dict:
    d = copy.deepcopy(d)
    if "unit" in d and "units" not in d:  # 0.x used "unit"
        d["units"] = d.pop("unit")
    d.setdefault("constraints", [])
    d.setdefault("host", {"name": "unknown", "version": "unknown"})
    d.setdefault("coordinate_system", {"up": "z", "handedness": "right"})
    d["schema_version"] = "1.0.0"
    return d


MIGRATIONS: dict[tuple[str, int], Callable[[dict], dict]] = {("SceneSnapshot", 0): _scene_0_to_1}


def migrate(kind: str, doc: dict) -> dict:
    major, _, _ = _parse_version(doc.get("schema_version"))
    cur_major = _parse_version(SCHEMA_VERSION)[0]
    if major > cur_major:
        raise VersionMismatch(f"{kind} schema_version {doc.get('schema_version')} is newer than supported {SCHEMA_VERSION}")
    while major < cur_major:
        fn = MIGRATIONS.get((kind, major))
        if fn is None:
            raise VersionMismatch(f"no migration for {kind} from major version {major}")
        doc = fn(doc)
        major = _parse_version(doc["schema_version"])[0]
    return doc


def _depth(x: Any, d: int = 0) -> int:
    if d > MAX_DEPTH:
        return d
    if isinstance(x, dict):
        return max([_depth(v, d + 1) for v in x.values()] + [d])
    if isinstance(x, list):
        return max([_depth(v, d + 1) for v in x] + [d])
    return d


def validate(kind: str, doc: Any, *, allow_migration: bool = True) -> dict:
    """Validate strictly and return the (possibly migrated) document. Raises ContractError."""
    if not isinstance(doc, dict):
        raise ContractError(f"{kind} must be a JSON object")
    if _depth(doc) > MAX_DEPTH:
        raise ContractError("document nesting is too deep")
    if allow_migration:
        doc = migrate(kind, doc)
    else:
        if _parse_version(doc.get("schema_version"))[0] != _parse_version(SCHEMA_VERSION)[0]:
            raise VersionMismatch(f"{kind} schema_version {doc.get('schema_version')} != {SCHEMA_VERSION}")
    errors = sorted(_validator(kind).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = "/".join(str(p) for p in e.path) or "<root>"
        raise ContractError(f"{kind} invalid at {where}: {e.message}")
    return doc


def parse_json(kind: str, raw: bytes | str) -> dict:
    """Parse untrusted bytes with a size cap, then validate."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ContractError("document too large")
    try:
        doc = json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(ContractError(f"bad constant {c}")))
    except json.JSONDecodeError as e:
        raise ContractError(f"malformed JSON: {e.msg}") from e
    return validate(kind, doc)


def canonical_json(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(x: Any) -> str:
    return hashlib.sha256(canonical_json(x).encode("utf-8")).hexdigest()
