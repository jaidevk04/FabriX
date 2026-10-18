import asyncio

import pytest

from cognition.domain import Capabilities, Industry, PlantSpec
from cognition.harnesses.reference import ReferenceHarness
from cognition.persistence.store import Store
from cognition.runtime.platform import Platform


@pytest.mark.parametrize("industry", list(Industry))
@pytest.mark.parametrize(
    "scenario,expected",
    [("heat_load", "resolved"), ("actuator_stuck", "escalated"), ("sensor_fault", "escalated")],
)
async def test_matrix(industry, scenario, expected):
    store = Store()
    platform = Platform(store)
    platform.onboard(PlantSpec(id="unit", name="Unit", industry=industry))
    initial = platform.connector.disturb("unit", scenario)
    incident = await platform.resolve("unit", ReferenceHarness())
    assert incident.status == expected
    if expected == "resolved":
        assert incident.trajectory[-1] < incident.trajectory[0]
        assert store.plant("unit").revision > initial.revision
    else:
        assert store.plant("unit") == initial
        assert not incident.trajectory
    store.close()


async def test_concurrent_investigations_apply_only_one_command(platform):
    platform.connector.disturb("kiln", "heat_load")
    ready = asyncio.Event()
    release = asyncio.Event()
    arrivals = 0

    class Barrier(ReferenceHarness):
        async def propose(self, request, tools):
            nonlocal arrivals
            proposal = await super().propose(request, tools)
            arrivals += 1
            ready.set()
            await release.wait()
            return proposal

    first = asyncio.create_task(platform.resolve("kiln", Barrier()))
    await asyncio.wait_for(ready.wait(), 1)
    with pytest.raises(ValueError, match="already active"):
        await platform.resolve("kiln", Barrier())
    release.set()
    assert (await first).status == "resolved"
    assert arrivals == 1
    assert platform.store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1


async def test_timeout(platform):
    class Slow:
        def capabilities(self):
            return Capabilities(name="slow", live_model=False)

        async def propose(self, request, tools):
            await asyncio.sleep(10)

    platform.timeout = 0.01
    state = platform.store.plant("kiln")
    result = await platform.resolve("kiln", Slow())
    assert result.status == "failed"
    assert "TimeoutError" in result.reason
    assert platform.store.plant("kiln") == state


async def test_cancellation_is_persisted(platform):
    started = asyncio.Event()

    class Waiting(ReferenceHarness):
        async def propose(self, request, tools):
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(platform.resolve("kiln", Waiting()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert platform.store.incidents()[0].status == "interrupted"


async def test_sdk_errors_do_not_persist_credentials(platform):
    class Failing(ReferenceHarness):
        async def propose(self, request, tools):
            raise RuntimeError("secret-api-key")

    result = await platform.resolve("kiln", Failing())
    assert result.status == "failed"
    assert "secret-api-key" not in result.model_dump_json()
    assert "secret-api-key" not in str(platform.store.events(result.id))


def test_reset_preserves_monotonic_revision(platform):
    fault = platform.connector.disturb("kiln", "actuator_stuck")
    reset = platform.connector.reset("kiln")
    assert not reset.stuck
    assert reset.revision > fault.revision
