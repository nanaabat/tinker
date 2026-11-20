import pytest

from tw_connector import Capabilities, ConnectorError, MockHost, negotiate
from tw_fixtures import BLIND_ID, PANEL_ID, room_scene


def test_apply_is_one_undo_step():
    h = MockHost(room_scene())
    ref = h.apply_transforms([{"object_id": PANEL_ID, "joint": "slide", "value": 1.0},
                              {"object_id": BLIND_ID, "joint": "tilt", "value": 0.5}])
    vals = {o["id"]: o["joints"][0]["value"] for o in h.get_scene()["objects"] if o["joints"]}
    assert vals == {PANEL_ID: 1.0, BLIND_ID: 0.5}
    h.undo(ref)
    assert h.get_scene() == room_scene()
    with pytest.raises(ConnectorError):
        h.undo(ref)


def test_partial_apply_failure_rolls_back():
    h = MockHost(room_scene(), fail_apply_after=1)
    with pytest.raises(ConnectorError):
        h.apply_transforms([{"object_id": PANEL_ID, "joint": "slide", "value": 1.0},
                            {"object_id": BLIND_ID, "joint": "tilt", "value": 0.5}])
    assert h.get_scene() == room_scene()


def test_subscribe_and_unsubscribe():
    h = MockHost(room_scene())
    seen = []
    unsub = h.subscribe_changes(lambda *a: seen.append(a))
    h.user_set_joint(PANEL_ID, "slide", 0.3, t=1.0)
    unsub()
    h.user_set_joint(PANEL_ID, "slide", 0.4, t=2.0)
    assert len(seen) == 1 and seen[0][0] == PANEL_ID and seen[0][3] == "edit"


def test_preview_is_non_destructive():
    h = MockHost(room_scene())
    hd = h.preview_transforms([{"object_id": PANEL_ID, "value": 1.0}])
    assert h.get_scene() == room_scene()
    h.clear_preview(hd)
    assert hd not in h.previews


def test_begin_demonstration_missing_object():
    with pytest.raises(KeyError):
        MockHost(room_scene()).begin_demonstration("ghost", "slide")


def test_negotiation():
    skill = {"target_types": ["blind"], "preconditions": {"joint_kind": "revolute", "value_range": [0, 1],
                                                          "required_capabilities": ["preview", "apply", "undo"]}}
    assert negotiate(Capabilities("x", "1"), skill) == (True, [])
    ok, why = negotiate(Capabilities("x", "1", joint_kinds=frozenset({"prismatic"}),
                                     features=frozenset({"get_scene"})), skill)
    assert not ok and len(why) == 2


def test_id_map():
    assert MockHost(room_scene()).map_object_ids()[PANEL_ID] == PANEL_ID
