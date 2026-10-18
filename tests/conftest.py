import pytest

from cognition.domain import Industry, PlantSpec
from cognition.persistence.store import Store
from cognition.runtime.platform import Platform


@pytest.fixture
def platform():
    store = Store()
    platform = Platform(store)
    platform.onboard(PlantSpec(id="kiln", name="Kiln", industry=Industry.CEMENT))
    yield platform
    store.close()


@pytest.fixture(autouse=True)
def no_live_core_agents(monkeypatch):
    """Tests never make live model calls, even if a local .env turns core agents on."""
    monkeypatch.setenv("COGNITION_CORE_AGENTS", "false")
