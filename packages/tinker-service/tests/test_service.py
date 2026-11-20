import http.client
import json
import os
import stat
import threading

import pytest

from tw_connector import MockHost
from tw_fixtures import BLIND_ID, room_scene
from tinker_service import PlanError, TinkerProvider
from tinker_service.http import MAX_BODY, TinkerHTTPServer, load_or_create_token

SUN = [-0.55, -0.7, 0.45]
GOAL = {"target_state": {"object_type": "blind", "object_id": None, "joint": "tilt", "target_value": None,
                         "intent": "reduce_direct_sun"}}


def test_provider_lists_resolves_simulates_previews(trained):
    reg, _ = trained
    host = MockHost(room_scene(blind_value=1.4))
    tp = TinkerProvider(reg, host)
    scene = host.get_scene()
    skills = tp.list_skills(scene, GOAL)
    assert [s["name"] for s in skills] == ["blind-tilt"]
    oid, jn, val, why = tp.resolve_target(scene, GOAL, skills[0], sun_dir=SUN, max_sunlit=0.12)
    assert oid == BLIND_ID and why["sunlit_target"] <= 0.12 < why["sunlit_now"]
    sim = tp.simulate(skills[0], scene, object_id=oid, joint=jn, goal_value=val, sun_dir=SUN)
    assert sim["success"], sim["violations"]
    pv = tp.preview(sim)
    assert pv["handle"] in host.previews and len(pv["frames"]) == 24
    assert host.get_scene() == scene  # preview did not change the document


def test_no_skill_for_other_object_type(trained):
    reg, _ = trained
    tp = TinkerProvider(reg, MockHost(room_scene()))
    goal = {"target_state": dict(GOAL["target_state"], object_type="sliding_panel")}
    assert tp.list_skills(room_scene(), goal) == []


def test_apply_requires_known_successful_simulation(trained):
    reg, _ = trained
    tp = TinkerProvider(reg, MockHost(room_scene()))
    with pytest.raises(PlanError):
        tp.apply({"simulation_id": "sim-x", "approval": {"schema_version": "1.0.0", "proposal_id": "g", "simulation_id": "sim-x",
                                                          "user_id": "u", "approved_at": "2026-11-15T05:00:00+00:00", "scope": "host_document"}})
    with pytest.raises(PlanError):
        TinkerProvider(reg, None).apply({"simulation_id": "x", "approval": {}})


def test_not_applicable_goal_outside_joint_range(trained):
    reg, res = trained
    tp = TinkerProvider(reg, MockHost(room_scene()))
    sim = tp.simulate(res["skill"], room_scene(), object_id=BLIND_ID, joint="tilt", goal_value=3.0)
    assert not sim["success"] and sim["violations"][0]["code"] == "not_applicable"


# ---------------- HTTP security
@pytest.fixture()
def server(trained, tmp_path):
    reg, _ = trained
    tok = load_or_create_token(tmp_path / "token")
    srv = TinkerHTTPServer(reg.root, tok, 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, tok
    srv.shutdown()
    srv.server_close()


def call(srv, method, path, body=None, headers=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=60)
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    out = r.status, r.getheaders(), r.read()
    c.close()
    return out


def test_token_file_is_private(tmp_path):
    tok = load_or_create_token(tmp_path / "t")
    assert len(tok) >= 40 and load_or_create_token(tmp_path / "t") == tok
    assert stat.S_IMODE(os.stat(tmp_path / "t").st_mode) == 0o600


def test_binds_loopback_only(server):
    srv, _ = server
    assert srv.server_address[0] == "127.0.0.1"


def test_requires_token(server):
    srv, tok = server
    assert call(srv, "GET", "/v1/health")[0] == 401
    assert call(srv, "GET", "/v1/health", headers={"Authorization": "Bearer wrong"})[0] == 401
    st, hdrs, body = call(srv, "GET", "/v1/health", headers={"Authorization": f"Bearer {tok}"})
    assert st == 200 and json.loads(body)["ok"]
    assert not any(k.lower().startswith("access-control") for k, _ in hdrs)


def test_rejects_browser_origin_and_rebinding(server):
    srv, tok = server
    auth = {"Authorization": f"Bearer {tok}"}
    assert call(srv, "GET", "/v1/health", headers={**auth, "Origin": "https://evil.example"})[0] == 403
    assert call(srv, "GET", "/v1/health", headers={**auth, "Host": "evil.example"})[0] == 403
    assert call(srv, "OPTIONS", "/v1/health", headers=auth)[0] in (401, 403, 405)


def test_size_type_and_malformed(server):
    srv, tok = server
    auth = {"Authorization": f"Bearer {tok}"}
    assert call(srv, "POST", "/v1/plan", headers={**auth, "Content-Length": str(MAX_BODY + 1)}, raw=b"")[0] == 413
    assert call(srv, "POST", "/v1/plan", headers={**auth, "Content-Type": "text/plain"}, raw=b"{}")[0] == 415
    assert call(srv, "POST", "/v1/plan", headers=auth, raw=b"{not json")[0] == 400
    assert call(srv, "POST", "/v1/plan", headers=auth, body=[1, 2])[0] == 400
    st, _, body = call(srv, "POST", "/v1/plan", headers=auth, body={"skill": "blind-tilt", "scene": {"schema_version": "1.0.0"}})
    assert st == 400 and b"Traceback" not in body


def test_path_traversal_in_skill_name(server):
    srv, tok = server
    auth = {"Authorization": f"Bearer {tok}"}
    for name in ["../../etc/passwd", "/abs", "blind-tilt/../x", "A"]:
        st, _, _ = call(srv, "POST", "/v1/plan", headers=auth, body={"skill": name, "scene": room_scene(),
                                                                     "object_id": BLIND_ID, "joint": "tilt", "goal_value": 0.4})
        assert st == 400, name


def test_untrusted_scene_file_rejected(server):
    srv, tok = server
    auth = {"Authorization": f"Bearer {tok}"}
    evil = room_scene()
    evil["objects"][0]["geometry_ref"] = "x" * 10000
    st, _, _ = call(srv, "POST", "/v1/plan", headers=auth, body={"skill": "blind-tilt", "scene": evil,
                                                                 "object_id": BLIND_ID, "joint": "tilt", "goal_value": 0.4})
    assert st == 400


def test_plan_over_http(server):
    srv, tok = server
    st, _, body = call(srv, "POST", "/v1/plan", headers={"Authorization": f"Bearer {tok}"},
                       body={"skill": "blind-tilt", "scene": room_scene(blind_value=1.4), "object_id": BLIND_ID,
                             "joint": "tilt", "goal_value": 0.4, "sun_dir": SUN})
    out = json.loads(body)
    assert st == 200 and out["simulation"]["success"] and len(out["preview"]) == 24


def test_no_external_network_calls(monkeypatch, trained):
    """The service and learner must not open non-loopback sockets (no silent telemetry)."""
    import socket
    real = socket.socket.connect

    def guard(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        assert host in ("127.0.0.1", "localhost", "::1"), f"external connection attempted to {host}"
        return real(self, addr)
    monkeypatch.setattr(socket.socket, "connect", guard)
    reg, res = trained
    tp = TinkerProvider(reg, MockHost(room_scene(blind_value=1.4)))
    sim = tp.simulate(res["skill"], room_scene(blind_value=1.4), object_id=BLIND_ID, joint="tilt", goal_value=0.4, sun_dir=SUN)
    assert sim["success"]
