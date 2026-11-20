# tinker

the learning + doing machine. watch. practice. learn.

tinker watches you move a part in your 3D tool, practices the move in a physics sandbox, and learns a skill it can repeat. every step is previewed first and can be undone.

## what is here

blender/tinker_blender  the blender extension: select, record, stop, learn, simulate, preview, apply, undo
rhino/  the rhino plug in and a small c# core with tests (compiles against rhinocommon 8)
packages/contracts  json schemas shared by tinker and wink, with python, c# and typescript bindings
packages/connector-sdk  the host connector interface and the authenticated loopback transport
packages/scene-core  scene snapshots, joints and poses
packages/action-core  validated, reversible actions
packages/simulation  the mujoco sandbox check
packages/tinker-learning  demonstrations in, a small behaviour cloning skill out (onnx)
packages/tinker-service  the local service the extension talks to
packages/test-fixtures  a synthetic room with a tilting blind, for tests

no trained weights ship with this repo. skills are learned on your machine from your own demonstrations.

## try it

```
python -m venv .venv
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install onnx onnxruntime onnxscript mujoco jsonschema pytest
for p in packages/*; do .venv/bin/pip install -e "$p"; done
.venv/bin/python -m pytest
.venv/bin/tinker-service
python build_blender.py
```

then in blender: edit, preferences, get extensions, install from disk, and pick the zip in dist. point the extension at the service port and token file it prints.

## status

experimental and early. expect rough edges and changes, and check every result yourself. no trained skills or weights ship with it; tinker learns from your own demonstrations. the blender extension and service run end to end on a test scene. the rhino plug in compiles but has not been run inside rhino. tinker learns one joint at a time.

## family

tinker is one of three. wink brings hunch and tinker together. tingle puts all three in one panel inside the 3D tools you already use.

## licence

mit, copyright aprewaturkson inc. see LICENSE.
