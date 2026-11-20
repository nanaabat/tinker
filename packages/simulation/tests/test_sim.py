import math

import pytest

from tw_action import Trajectory
from tw_contracts import validate
from tw_fixtures import BLIND_ID, PANEL_ID, room_scene
from tw_sim import simulate, sunlit_fraction

SUN = [-0.55, -0.7, 0.45]
codes = lambda r: sorted({v["code"] for v in r["violations"]})


def test_clean_slide_succeeds_and_validates():
    r = simulate(room_scene(), Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8]))
    validate("SimulationResult", r)
    assert r["success"], r["violations"]
    assert r["metrics"]["goal_error"] < 0.005


def test_deterministic():
    tr = Trajectory(BLIND_ID, "tilt", [0, 3], [0, 1.0])
    a, b = simulate(room_scene(), tr), simulate(room_scene(), tr)
    assert a["trajectory"] == b["trajectory"] and a["metrics"] == b["metrics"] and a["id"] == b["id"]


def test_collision_with_obstacle():
    s = room_scene(obstacle=([2.5, 2.5, 0.5], [0.4, 0.4, 1.0]))
    r = simulate(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8]))
    assert not r["success"] and "collision" in codes(r)
    assert any("obstacle" in v["object_ids"] for v in r["violations"])


@pytest.mark.parametrize("x", [1.2, 2.0, 2.8, 3.25])
def test_adversarial_obstacle_positions(x):
    # obstacles placed along the panel's path always block; one placed out of the path does not
    s = room_scene(obstacle=([x, 2.5, 1.0], [0.1, 0.3, 0.3]))
    r = simulate(s, Trajectory(PANEL_ID, "slide", [0, 4.2], [0, 2.0]))
    assert "collision" in codes(r)


def test_obstacle_out_of_path_is_fine():
    s = room_scene(obstacle=([2.0, 1.0, 0.5], [0.4, 0.4, 1.0]))
    assert simulate(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8]))["success"]


def test_blind_hits_exterior_obstacle():
    s = room_scene(obstacle=([2.0, -0.9, 1.0], [2.0, 0.3, 0.4]))
    r = simulate(s, Trajectory(BLIND_ID, "tilt", [0, 3], [0, 1.2]))
    assert "collision" in codes(r)


def test_impossible_goal():
    r = simulate(room_scene(), Trajectory(PANEL_ID, "slide", [0, 10], [0, 3.0]))
    assert not r["success"] and "unreachable_goal" in codes(r)


def test_speed_violation():
    r = simulate(room_scene(), Trajectory(PANEL_ID, "slide", [0, 0.5], [0, 1.5]))
    assert "speed_limit" in codes(r)


def test_force_limit_when_too_weak():
    s = room_scene()
    for o in s["objects"]:
        if o["id"] == PANEL_ID:
            o["joints"][0]["max_force"] = 0.5
    r = simulate(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8]))
    assert not r["success"] and "force_limit" in codes(r)


def test_no_go_volume():
    s = room_scene(no_go=([1.9, 2.3, 0.0], [2.6, 2.7, 1.0]))
    r = simulate(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8]))
    assert "no_go_volume" in codes(r)


def test_missing_geometry():
    s = room_scene()
    for o in s["objects"]:
        if o["id"] == PANEL_ID:
            o["size"] = [0, 0, 0]
    assert "missing_geometry" in codes(simulate(s, Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.0])))
    assert "missing_geometry" in codes(simulate(room_scene(), Trajectory("nope", "slide", [0, 4], [0, 1.0])))


def test_varying_geometry_room_sizes():
    for w, d in [(3.0, 4.0), (6.0, 8.0)]:
        r = simulate(room_scene(width=w, depth=d), Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.5]))
        assert r["success"], (w, d, r["violations"])


def test_millimetre_scene_matches_metre_scene():
    tr_m = Trajectory(PANEL_ID, "slide", [0, 4], [0, 1.8])
    tr_mm = Trajectory(PANEL_ID, "slide", [0, 4], [0, 1800])
    a, b = simulate(room_scene(), tr_m), simulate(room_scene(units="mm"), tr_mm)
    assert a["success"] and b["success"]
    assert b["metrics"]["final_value"] == pytest.approx(a["metrics"]["final_value"] * 1000, rel=1e-6)


def test_sunlit_fraction_monotone_with_closing():
    s = room_scene()
    vals = [sunlit_fraction(s, SUN, {BLIND_ID: math.radians(a)}) for a in (0, 20, 40, 60, 83)]
    assert vals[0] == 0.0 and vals == sorted(vals) and vals[-1] > 0.3
