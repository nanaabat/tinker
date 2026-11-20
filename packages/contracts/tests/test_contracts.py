import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tw_contracts import ContractError, KINDS, VersionMismatch, parse_json, validate, MAX_DOCUMENT_BYTES

ROOT = Path(__file__).resolve().parents[3]


def test_generated_types_are_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "codegen.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_kind_has_schema():
    from tw_contracts import load_schema
    for k in KINDS:
        s = load_schema(k)
        assert s["additionalProperties"] is False and "schema_version" in s["required"]


def test_scene_roundtrip(scene):
    raw = json.dumps(scene)
    assert parse_json("SceneSnapshot", raw) == scene


def test_unknown_field_rejected(scene):
    bad = copy.deepcopy(scene)
    bad["objects"][0]["evil"] = "x"
    with pytest.raises(ContractError):
        validate("SceneSnapshot", bad)


def test_missing_required_rejected(scene):
    bad = copy.deepcopy(scene)
    del bad["units"]
    with pytest.raises(ContractError):
        validate("SceneSnapshot", bad)


def test_newer_major_version_rejected(scene):
    bad = dict(scene, schema_version="2.0.0")
    with pytest.raises(VersionMismatch):
        validate("SceneSnapshot", bad)


def test_non_semver_rejected(scene):
    with pytest.raises(VersionMismatch):
        validate("SceneSnapshot", dict(scene, schema_version="one"))


def test_migration_from_0x(scene):
    old = copy.deepcopy(scene)
    old["schema_version"] = "0.9.0"
    old["unit"] = old.pop("units")
    del old["constraints"]
    new = validate("SceneSnapshot", old)
    assert new["units"] == "m" and new["constraints"] == [] and new["schema_version"] == "1.0.0"


def test_no_migration_path(demos):
    old = dict(demos[0], schema_version="0.1.0")
    with pytest.raises(VersionMismatch):
        validate("Demonstration", old)


def test_strict_mode_refuses_migration(scene):
    with pytest.raises(VersionMismatch):
        validate("SceneSnapshot", dict(scene, schema_version="0.9.0"), allow_migration=False)


def test_malformed_json():
    for raw in [b"{", b"[1,2]", b'{"schema_version": NaN}', b"\xff\xfe"]:
        with pytest.raises(ContractError):
            parse_json("SceneSnapshot", raw)


def test_oversized_document():
    with pytest.raises(ContractError):
        parse_json("SceneSnapshot", b" " * (MAX_DOCUMENT_BYTES + 1))


def test_deep_nesting_rejected():
    deep = {"a": 1}
    for _ in range(60):
        deep = {"x": deep}
    with pytest.raises(ContractError):
        validate("SceneSnapshot", {"schema_version": "1.0.0", **deep})


def test_ids_reject_path_like_values(scene):
    bad = copy.deepcopy(scene)
    bad["objects"][0]["id"] = "../../etc/passwd"
    with pytest.raises(ContractError):
        validate("SceneSnapshot", bad)


def test_skill_model_path_has_no_executable_payload(trained):
    _, res = trained
    s = res["skill"]
    validate("Skill", s)
    text = json.dumps(s)
    assert "__reduce__" not in text and "lambda" not in text


def test_typescript_and_csharp_emitted():
    ts = (ROOT / "packages/contracts/ts/index.ts").read_text()
    cs = (ROOT / "packages/contracts/csharp/TinkerWink.Contracts.cs").read_text()
    for k in KINDS:
        assert f"export interface {k} " in ts
        assert f"public sealed class {k}" in cs
