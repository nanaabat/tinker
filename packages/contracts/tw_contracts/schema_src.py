"""Source of truth for the tinker + wink contracts (JSON Schema draft 2020-12).

`python tools/codegen.py` writes the JSON files plus Python, TypeScript and C# types.
Never serialize executable code into these documents: every field is plain data.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0.0"
ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
QUAT = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
VERSION = {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"}
TIME = {"type": "string", "format": "date-time", "maxLength": 64}
TEXT = {"type": "string", "maxLength": 4000}
NAME = {"type": "string", "maxLength": 256}
# relative path inside a registry: no absolute paths, no "..", no backslashes
RELPATH = {"type": "string", "pattern": r"^(?!/)(?!.*\.\.)(?!.*\\)[A-Za-z0-9._/-]{1,256}$"}


def obj(props: dict, required: list[str] | None = None, title: str | None = None) -> dict:
    o = {"type": "object", "properties": props, "required": list(props) if required is None else required,
         "additionalProperties": False}
    if title:
        o["title"] = title
    return o


DEFS = {
    "Pose": obj({"position": VEC3, "rotation": QUAT}, title="Pose"),
    "Joint": obj({
        "name": ID,
        "kind": {"enum": ["prismatic", "revolute"]},
        "axis": VEC3,
        "anchor": VEC3,
        "lower": {"type": "number"},
        "upper": {"type": "number"},
        "max_speed": {"type": "number", "exclusiveMinimum": 0},
        "max_force": {"type": "number", "exclusiveMinimum": 0},
        "value": {"type": "number"},
    }, title="Joint"),
    "SceneObject": obj({
        "id": ID,
        "host_id": NAME,
        "name": NAME,
        "type": {"enum": ["room", "floor", "wall", "window", "blind", "sliding_panel", "obstacle", "generic"]},
        "parent_id": {"type": ["string", "null"], "maxLength": 128},
        "pose": {"$ref": "#/$defs/Pose"},
        "size": VEC3,
        "geometry_ref": NAME,
        "collision": {"type": "boolean"},
        "joints": {"type": "array", "items": {"$ref": "#/$defs/Joint"}, "maxItems": 16},
    }, required=["id", "host_id", "name", "type", "parent_id", "pose", "size", "collision", "joints"], title="SceneObject"),
    "Constraint": obj({
        "id": ID,
        "kind": {"enum": ["no_go_volume", "travel_bounds", "max_speed", "dependency"]},
        "object_ids": {"type": "array", "items": ID, "maxItems": 64},
        "min": VEC3,
        "max": VEC3,
        "value": {"type": "number"},
    }, required=["id", "kind", "object_ids"], title="Constraint"),
    "Violation": obj({
        "code": {"enum": ["collision", "joint_limit", "speed_limit", "force_limit", "no_go_volume",
                          "unreachable_goal", "missing_geometry", "stale_scene", "not_applicable"]},
        "message": TEXT,
        "t": {"type": ["number", "null"]},
        "object_ids": {"type": "array", "items": ID, "maxItems": 64},
    }, title="Violation"),
    "Sample": obj({
        "t": {"type": "number", "minimum": 0},
        "poses": {"type": "object", "additionalProperties": {"$ref": "#/$defs/Pose"}, "maxProperties": 64},
        "action": {"type": ["string", "null"], "maxLength": 128},
        "event": {"enum": ["sample", "edit", "undo", "redo"]},
    }, title="Sample"),
}


def doc(title: str, props: dict, required: list[str] | None = None) -> dict:
    base = {"schema_version": VERSION}
    base.update(props)
    req = ["schema_version"] + (list(props) if required is None else required)
    s = obj(base, req)
    s.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$id": f"urn:tinker:schema:{title}", "title": title})
    return s


DOCS = {
    "SceneSnapshot": doc("SceneSnapshot", {
        "scene_id": ID,
        "units": {"enum": ["m", "cm", "mm", "in", "ft"]},
        "coordinate_system": obj({"up": {"enum": ["z", "y"]}, "handedness": {"enum": ["right", "left"]}}),
        "host": obj({"name": NAME, "version": NAME}),
        "objects": {"type": "array", "items": {"$ref": "#/$defs/SceneObject"}, "maxItems": 2000},
        "constraints": {"type": "array", "items": {"$ref": "#/$defs/Constraint"}, "maxItems": 500},
    }),
    "Demonstration": doc("Demonstration", {
        "id": ID,
        "scene_id": ID,
        "object_ids": {"type": "array", "items": ID, "minItems": 1, "maxItems": 64},
        "samples": {"type": "array", "items": {"$ref": "#/$defs/Sample"}, "maxItems": 100000},
        "goal": obj({"object_id": ID, "joint": ID, "target_value": {"type": "number"}}),
        "context": {"type": "object", "additionalProperties": {"type": ["string", "number", "boolean"]}, "maxProperties": 64},
        "user_corrections": {"type": "array", "items": ID, "maxItems": 1000},
    }),
    "Skill": doc("Skill", {
        "id": ID,
        "version": {"type": "integer", "minimum": 1},
        "name": NAME,
        "target_types": {"type": "array", "items": {"enum": ["wall", "window", "blind", "sliding_panel", "generic"]}, "minItems": 1},
        "preconditions": obj({"joint_kind": {"enum": ["prismatic", "revolute"]},
                              "value_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                              "required_capabilities": {"type": "array", "items": NAME}}),
        "model_ref": obj({"kind": {"enum": ["parametric_template", "behavior_cloning_onnx"]},
                          "path": {"type": ["string", "null"], "maxLength": 256}, "sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}}),
        "fallback_trajectory": obj({"phase": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 1024},
                                    "progress": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 1024},
                                    "mean_speed": {"type": "number", "exclusiveMinimum": 0}}),
        "limits": obj({"max_speed": {"type": "number", "exclusiveMinimum": 0}, "max_force": {"type": "number", "exclusiveMinimum": 0}}),
        "evaluation": obj({"demonstrations": {"type": "integer", "minimum": 0},
                           "baseline_val_rmse": {"type": ["number", "null"]},
                           "model_val_rmse": {"type": ["number", "null"]},
                           "baseline_holdout_rmse": {"type": ["number", "null"]},
                           "model_holdout_rmse": {"type": ["number", "null"]},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                           "note": TEXT}),
    }),
    "GoalProposal": doc("GoalProposal", {
        "id": ID,
        "source": {"enum": ["user_rule", "inferred_preference", "model_guess", "manual"]},
        "provider": obj({"name": NAME, "mock": {"type": "boolean"}}),
        "target_state": obj({"object_type": {"enum": ["wall", "window", "blind", "sliding_panel", "generic"]},
                             "object_id": {"type": ["string", "null"], "maxLength": 128},
                             "joint": {"type": ["string", "null"], "maxLength": 128},
                             "target_value": {"type": ["number", "null"]},
                             "intent": NAME}),
        "rationale": TEXT,
        "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
        "user_preferences_used": {"type": "array", "items": NAME, "maxItems": 64},
        "created_at": TIME,
    }),
    "SimulationResult": doc("SimulationResult", {
        "id": ID,
        "skill_id": ID,
        "scene_id": ID,
        "scene_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "success": {"type": "boolean"},
        "violations": {"type": "array", "items": {"$ref": "#/$defs/Violation"}, "maxItems": 1000},
        "trace_ref": {"type": ["string", "null"], "maxLength": 256},
        "trajectory": obj({"t": {"type": "array", "items": {"type": "number"}, "maxItems": 20000},
                           "value": {"type": "array", "items": {"type": "number"}, "maxItems": 20000},
                           "object_id": ID, "joint": ID}),
        "metrics": {"type": "object", "additionalProperties": {"type": ["number", "string", "boolean", "null"]}, "maxProperties": 64},
    }),
    "ActionApproval": doc("ActionApproval", {
        "proposal_id": ID,
        "simulation_id": ID,
        "user_id": ID,
        "approved_at": TIME,
        "scope": {"enum": ["sandbox_preview", "host_document", "hardware"]},
    }),
    "ActionReceipt": doc("ActionReceipt", {
        "action_id": ID,
        "before_state": {"type": "object", "additionalProperties": {"type": "number"}, "maxProperties": 256},
        "after_state": {"type": "object", "additionalProperties": {"type": "number"}, "maxProperties": 256},
        "host_undo_ref": {"type": ["string", "null"], "maxLength": 256},
        "result": {"enum": ["applied", "rolled_back", "failed", "partial_rolled_back"]},
        "audit_id": ID,
    }),
}


def full_schema(name: str) -> dict:
    s = dict(DOCS[name])
    s["$defs"] = DEFS
    return s
