from cognition.domain import Incident, Industry, PlantSpec, Request
from cognition.harnesses.reference import ReferenceHarness
from cognition.layers.cognitive.tools import Tools
from cognition.persistence.store import Store
from cognition.runtime.platform import Platform


async def test_restart_reconciles_committed_command_without_reexecution(tmp_path):
    path = str(tmp_path / "platform.db")
    store = Store(path)
    platform = Platform(store)
    platform.onboard(PlantSpec(id="unit", name="Unit", industry=Industry.STEEL))
    state = platform.connector.disturb("unit", "heat_load")
    incident = Incident(plant_id="unit", harness="reference", status="investigating")
    store.put("incidents", incident.id, incident)
    request = Request(incident_id=incident.id, snapshot=state)
    proposal = await ReferenceHarness().propose(request, Tools(request, store))
    receipt = platform.gateway.execute(proposal, incident.id, "unit")
    final_state = store.plant("unit")
    # Simulate the crash window after command commit and before incident completion.
    store.close()
    reopened = Store(path)
    restarted = Platform(reopened)
    restarted.reconcile()
    assert reopened.incidents()[0].status == "resolved"
    assert reopened.incidents()[0].trajectory == receipt.trajectory
    assert restarted.gateway.execute(proposal, incident.id, "unit") == receipt
    assert reopened.plant("unit") == final_state
    reopened.close()


def test_interrupted_investigation_requires_new_snapshot(platform):
    incident = Incident(plant_id="kiln", harness="reference", status="investigating")
    platform.store.put("incidents", incident.id, incident)
    platform.reconcile()
    assert platform.store.incidents()[0].status == "interrupted"
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
