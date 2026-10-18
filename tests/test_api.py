from fastapi.testclient import TestClient

from cognition.api import create_app


def test_api_workflow():
    with TestClient(create_app(":memory:")) as client:
        assert client.get("/").status_code == 200
        assert client.get("/").headers["cache-control"] == "no-store"
        assert client.get("/static/style.css").headers["cache-control"] == "no-cache"
        for page in ("fleet", "studio", "investigations", "assets", "system"):
            assert client.get(f"/{page}").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/scene.js").status_code == 200
        assert client.get("/health").json()["mode"] == "simulation"
        assert len(client.get("/api/plants").json()) == 3
        assert client.get("/api/harnesses").json()[0]["configured"]
        spec = {"id": "new-unit", "name": "New unit", "industry": "steel"}
        assert client.post("/api/plants", json=spec).status_code == 201
        assert client.post("/api/plants", json=spec).status_code == 409
        assert (
            client.post(
                "/api/plants/new-unit/scenarios", json={"scenario": "heat_load"}
            ).status_code
            == 200
        )
        incident = client.post("/api/plants/new-unit/resolve", json={"harness": "reference"}).json()
        assert incident["status"] == "resolved"
        assert client.get(f"/api/incidents/{incident['id']}/events").json()
        assert client.get("/api/plants/new-unit/capabilities?query=control").json()
        reset = client.post("/api/plants/new-unit/reset", json={}).json()
        assert reset["temperature"] == reset["target"]
        assert client.post("/api/plants/missing/resolve", json={}).status_code == 404
        assert (
            client.post("/api/plants/new-unit/resolve", json={"harness": "unknown"}).status_code
            == 422
        )
        assert (
            client.post("/api/plants/new-unit/scenarios", json={"scenario": "unknown"}).status_code
            == 422
        )
        assert client.get("/api/incidents/missing/events").status_code == 404


def test_prediction_is_read_only_and_validated():
    with TestClient(create_app(":memory:")) as client:
        client.post("/api/plants/cement-demo/scenarios", json={"scenario": "heat_load"})
        before = client.get("/api/plants").json()
        result = client.post("/api/plants/cement-demo/predict", json={"value": 36})
        assert result.status_code == 200
        assert result.json()["prediction"]["recovered"]
        assert result.json()["revision"] == before[0]["revision"]
        assert client.get("/api/plants").json() == before
        assert client.get("/api/incidents").json() == []
        assert client.post("/api/plants/cement-demo/predict", json={"value": 91}).status_code == 422
        assert client.post("/api/plants/cement-demo/predict", json={"value": 20}).status_code == 422
        assert client.post("/api/plants/missing/predict", json={"value": 36}).status_code == 404
