from fastapi.testclient import TestClient

from cognition.api import create_app


def test_new_pages_and_assets_are_served_and_wired():
    with TestClient(create_app(":memory:")) as client:
        page = client.get("/impact")
        assert page.status_code == 200 and 'id="impact-host"' in page.text
        harness = client.get("/faculties")
        assert harness.status_code == 200 and 'id="faculties-host"' in harness.text
        studio = client.get("/studio").text
        # The cores moved out of the studio into the Specialist Faculties page, one tab per view.
        assert 'id="view-tab-cores"' not in studio and 'id="cores-panel"' not in studio
        for view in ("overview", "learning", "vision", "robot", "optimization"):
            assert f'id="faculties-tab-{view}"' in studio
        assert 'data-nav="faculties"' in studio and 'data-nav="impact"' in studio
        assert "/static/cores.css" in studio
        for asset in ("cores.js", "cores-parts.js", "faculties.js", "impact.js", "cores.css"):
            response = client.get(f"/static/{asset}")
            assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
        boot = client.get("/static/boot.js").text
        assert '"impact"' in boot and '"faculties"' in boot
        assert 'TABS = ["twin", "flow", "hmi"]' in client.get("/static/plant-views.js").text
        assert "fl-cores" in client.get("/static/fleet.js").text
