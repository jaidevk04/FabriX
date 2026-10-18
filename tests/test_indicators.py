import pytest
from fastapi.testclient import TestClient

from cognition.api import create_app
from cognition.domain import Industry, PlantSpec, Request
from cognition.layers.cognitive.tools import Tools
from cognition.layers.perceptual.indicators import process_indicators
from cognition.simulation.thermal import inject, onboard


@pytest.mark.parametrize("industry", list(Industry))
def test_estimates_are_repeatable_bounded_and_respond_to_disturbance(industry):
    state = onboard(PlantSpec(id="indicator-test", name="Instrument test", industry=industry))
    before = state.model_dump_json()
    normal = process_indicators(state)
    assert len(normal) == 5
    assert normal == process_indicators(state)
    assert state.model_dump_json() == before
    assert all(metric.condition == "within_band" for metric in normal)
    disturbed = process_indicators(inject(state, "heat_load"))
    assert [metric.value for metric in normal] != [metric.value for metric in disturbed]
    assert all(metric.minimum <= metric.value <= metric.maximum for metric in disturbed)
    assert all(
        metric.value is None and metric.condition == "unavailable"
        for metric in process_indicators(inject(state, "sensor_fault"))
    )


def test_api_instruments_are_read_only_and_match_snapshot():
    with TestClient(create_app(":memory:")) as client:
        before = client.get("/api/plants").json()
        for state in before:
            response = client.get(f"/api/plants/{state['spec']['id']}/instruments")
            assert response.status_code == 200
            data = response.json()
            assert data["revision"] == state["revision"]
            assert data["sampled_at"] == state["sampled_at"]
            assert len(data["indicators"]) == 5
            assert "estimates" in data["basis"]
        assert before == client.get("/api/plants").json()
        assert client.get("/api/plants/missing/instruments").status_code == 404


def test_harness_estimates_use_frozen_incident_scope(platform):
    request = Request(incident_id="frozen-indicators", snapshot=platform.store.plant("kiln"))
    tools = Tools(request, platform.store)
    baseline = tools.read_snapshot()["process_indicators"]
    platform.connector.disturb("kiln", "heat_load")
    assert tools.read_snapshot()["process_indicators"] == baseline
    assert "not independent sensors" in baseline["basis"]
