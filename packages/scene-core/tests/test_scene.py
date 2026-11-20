import math

import pytest

from tw_scene import (IdMap, convert_axes, convert_length, convert_scene, find_joint, find_object, pose_for_value,
                      qaxis, qrot, scene_hash, semantic_id, value_from_pose, y_up_to_z_up_vec, z_up_to_y_up_vec)
from tw_fixtures import BLIND_ID, PANEL_ID, room_scene


def test_length_units():
    assert convert_length(1500, "mm", "m") == pytest.approx(1.5)
    assert convert_length(1, "ft", "in") == pytest.approx(12)
    with pytest.raises(ValueError):
        convert_length(1, "furlong", "m")


def test_scene_mm_roundtrip_preserves_angles():
    s = room_scene()
    mm = convert_scene(s, "mm")
    assert mm["units"] == "mm"
    p = find_joint(find_object(mm, PANEL_ID), "slide")
    b = find_joint(find_object(mm, BLIND_ID), "tilt")
    assert p["upper"] == pytest.approx(2000) and p["max_speed"] == pytest.approx(500)
    assert b["upper"] == pytest.approx(math.radians(83))  # radians are not lengths
    back = convert_scene(mm, "m")
    for a, c in zip(s["objects"], back["objects"]):
        assert a["pose"]["position"] == pytest.approx(c["pose"]["position"])


def test_axes_roundtrip():
    v = [1.0, 2.0, 3.0]
    assert z_up_to_y_up_vec(y_up_to_z_up_vec(v)) == v
    assert y_up_to_z_up_vec([0, 1, 0]) == [0, 0, 1]  # Y-up "up" becomes Z-up "up"
    s = room_scene()
    y = convert_axes(s, "y")
    z = convert_axes(y, "z")
    for a, c in zip(s["objects"], z["objects"]):
        assert a["pose"]["position"] == pytest.approx(c["pose"]["position"], abs=1e-9)
        assert a["pose"]["rotation"] == pytest.approx(c["pose"]["rotation"], abs=1e-9)


def test_axes_rotation_consistent_with_positions():
    # a point carried by an object's rotation must land in the same place in both frames
    s = room_scene(blind_value=0.7)
    o = find_object(s, BLIND_ID)
    local = [0.1, 0.2, 0.3]
    world_z = [a + b for a, b in zip(o["pose"]["position"], qrot(o["pose"]["rotation"], local))]
    oy = find_object(convert_axes(s, "y"), BLIND_ID)
    world_y = [a + b for a, b in zip(oy["pose"]["position"], qrot(oy["pose"]["rotation"], local))]
    assert z_up_to_y_up_vec(world_z) == pytest.approx(world_y, abs=1e-9)


@pytest.mark.parametrize("oid,joint,vals", [(PANEL_ID, "slide", [0, 0.5, 1.9]), (BLIND_ID, "tilt", [0, 0.3, 1.4])])
def test_joint_value_pose_roundtrip(oid, joint, vals):
    s = room_scene()
    o = find_object(s, oid)
    j = find_joint(o, joint)
    for v in vals:
        assert value_from_pose(o, j, pose_for_value(o, j, v)) == pytest.approx(v, abs=1e-9)


def test_blind_hinge_keeps_top_edge_fixed():
    s = room_scene()
    o = find_object(s, BLIND_ID)
    j = find_joint(o, "tilt")
    top = lambda pose: [a + b for a, b in zip(pose["position"], qrot(pose["rotation"], j["anchor"]))]
    p0, p1 = pose_for_value(o, j, 0.0), pose_for_value(o, j, 1.2)
    assert top(p0) == pytest.approx(top(p1), abs=1e-9)
    bottom = lambda pose: [a + b for a, b in zip(pose["position"], qrot(pose["rotation"], [0, 0, -o["size"][2] / 2]))]
    assert bottom(p1)[1] < bottom(p0)[1] - 0.5  # swings outward (-y), away from the wall


def test_semantic_ids_stable_and_distinct():
    a = semantic_id("rhino", "doc1", "guid-1")
    assert a == semantic_id("rhino", "doc1", "guid-1")
    assert a != semantic_id("rhino", "doc2", "guid-1") != semantic_id("blender", "doc1", "guid-1")
    m = IdMap("blender", "file.blend")
    sid = m.add("Cube")
    assert m.add("Cube") == sid and m.host_id(sid) == "Cube"
    assert m.add("Other", preferred=sid) != sid  # preferred id collision falls back to a derived id


def test_scene_hash_changes_with_state():
    assert scene_hash(room_scene()) == scene_hash(room_scene())
    assert scene_hash(room_scene()) != scene_hash(room_scene(blind_value=0.2))
