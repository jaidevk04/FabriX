from fastapi.testclient import TestClient

from cognition.api import create_app


def test_cores_api_reports_alerts_and_events():
    with TestClient(create_app(":memory:")) as client:
        plant = "cement-demo"
        names = [c["name"] for c in client.get(f"/api/plants/{plant}/cores").json()]
        assert names == ["learning", "vision", "robot", "optimization"]
        client.post(
            f"/api/plants/{plant}/faults",
            json={"kind": "kiln_drive_bearing_wear", "severity": 1, "ramp_ticks": 0},
        )
        client.post(f"/api/plants/{plant}/world/start", json={"interval_seconds": 0.2})
        import time

        time.sleep(1.2)
        report = client.get(f"/api/plants/{plant}/cores/learning").json()
        assert report["status"] == "alert" and report["alerts"][0]["equipment"] == "drive"
        deep = client.get(f"/api/plants/{plant}/cores/learning?analyse=true").json()
        assert deep["source"] == "reference" and deep["assessment"]["candidates"]
        events = client.get(f"/api/plants/{plant}/cores/events").json()
        assert any(e["kind"] == "core_alert" for e in events)
        client.post(f"/api/plants/{plant}/world/stop")
        assert client.get(f"/api/plants/{plant}/cores/nope").status_code == 404
        assert client.get("/api/plants/missing/cores").status_code == 404


def test_agent_status_runs_and_stop_endpoints(monkeypatch):
    for name in ("GEMINI_MODEL", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COGNITION_CORE_AGENTS", "false")
    with TestClient(create_app(":memory:")) as client:
        status = client.get("/api/cores/agents").json()
        assert status["enabled"] is False and status["available"] is False
        assert status["ceiling_seconds"] == 600
        plant = "steel-demo"
        assert client.get(f"/api/plants/{plant}/cores/runs").json() == []
        assert client.post(f"/api/plants/{plant}/cores/stop").json() == {"stopped": []}
        assert client.post(f"/api/plants/{plant}/cores/robot/stop").json() == {"stopped": []}
        assert client.post(f"/api/plants/{plant}/cores/nope/stop").status_code == 404
        assert client.post("/api/plants/missing/cores/stop").status_code == 404
        kinds = [e["kind"] for e in client.get(f"/api/plants/{plant}/cores/events").json()]
        assert kinds == ["core_stop_all", "core_stop"]
        monkeypatch.setenv("COGNITION_CORE_AGENTS", "true")
        # create_app loads a local .env, so credentials may exist; only the invariant is asserted.
        on = client.get("/api/cores/agents").json()
        assert on["enabled"] and on["degraded"] == (not on["available"])


def test_panel_and_overview_endpoints_serve_the_ui():
    with TestClient(create_app(":memory:")) as client:
        plant = "cement-demo"
        client.post(
            f"/api/plants/{plant}/faults",
            json={"kind": "kiln_drive_bearing_wear", "severity": 1, "ramp_ticks": 0},
        )
        client.post(f"/api/plants/{plant}/world/start", json={"interval_seconds": 0.2})
        import time

        time.sleep(1.5)
        panel = client.get(f"/api/plants/{plant}/cores/panel").json()
        assert {"world", "agents", "cores", "runs", "faults", "signals", "cameras", "fleet"} <= set(
            panel
        )
        assert [c["name"] for c in panel["cores"]] == [
            "learning",
            "vision",
            "robot",
            "optimization",
        ]
        assert panel["world"]["running"] and panel["faults"][0]["kind"] == "kiln_drive_bearing_wear"
        assert panel["events"] and panel["last_seq"] == panel["events"][-1]["seq"]
        later = client.get(f"/api/plants/{plant}/cores/panel?after={panel['last_seq']}").json()
        assert all(e["seq"] > panel["last_seq"] for e in later["events"])
        overview = client.get("/api/cores/overview").json()
        assert overview["plants"][plant]["world"] and overview["plants"][plant]["cores"]["learning"]
        assert set(overview["plants"]) == {"cement-demo", "steel-demo", "chemical-demo"}
        client.post(f"/api/plants/{plant}/world/stop")
        assert client.get("/impact").status_code == 200
        assert client.get("/api/plants/missing/cores/panel").status_code == 404
