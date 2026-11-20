import pytest

from tw_action import Trajectory, check_limits, preview_transforms, resample
from tw_fixtures import BLIND_ID, PANEL_ID, room_scene


def test_trajectory_validation():
    with pytest.raises(ValueError):
        Trajectory("a", "j", [0, 1], [0])
    with pytest.raises(ValueError):
        Trajectory("a", "j", [0, 2, 1], [0, 1, 2])


def test_interpolation_and_resample():
    t = Trajectory("a", "j", [0, 1, 2], [0, 1, 0])
    assert t.value_at(0.5) == pytest.approx(0.5) and t.value_at(5) == 0
    r = resample(t, 0.1)
    assert len(r.t) == 21 and r.value[10] == pytest.approx(1)


def test_limits_ok_and_violations():
    s = room_scene()
    assert check_limits(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.5])) == []
    codes = lambda tr: [v["code"] for v in check_limits(s, tr)]
    assert "joint_limit" in codes(Trajectory(PANEL_ID, "slide", [0, 10], [0, 2.5]))
    assert "speed_limit" in codes(Trajectory(PANEL_ID, "slide", [0, 0.5], [0, 1.5]))
    assert "speed_limit" in codes(Trajectory(PANEL_ID, "slide", [0, 0, 1], [0, 1, 1]))
    assert "missing_geometry" in codes(Trajectory("ghost", "slide", [0, 1], [0, 1]))


def test_constraints_tighten_limits():
    s = room_scene()
    s["constraints"] += [{"id": "tb", "kind": "travel_bounds", "object_ids": [PANEL_ID], "min": [0, 0, 0], "max": [1.0, 0, 0]},
                         {"id": "ms", "kind": "max_speed", "object_ids": [PANEL_ID], "value": 0.1}]
    codes = [v["code"] for v in check_limits(s, Trajectory(PANEL_ID, "slide", [0, 5], [0, 1.2]))]
    assert "joint_limit" in codes and "speed_limit" in codes


def test_preview_does_not_mutate_scene():
    s = room_scene()
    before = repr(s)
    fr = preview_transforms(s, Trajectory(BLIND_ID, "tilt", [0, 2], [0, 1.0]), frames=5)
    assert repr(s) == before and len(fr) == 5 and fr[-1]["value"] == pytest.approx(1.0)
