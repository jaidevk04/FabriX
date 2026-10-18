from datetime import timedelta

import pytest
from pydantic import ValidationError

from cognition.control.gateway import Rejected
from cognition.domain import Action, Proposal, now
from cognition.simulation.thermal import simulate


def proposal(platform, **changes):
    values = dict(
        plant_id="kiln",
        revision=platform.store.plant("kiln").revision,
        expires_at=now() + timedelta(minutes=1),
        summary="Tested adjustment",
        action=Action(value=36),
    )
    values.update(changes)
    return Proposal(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": Action(value=0)},
        {"action": Action(value=10)},
        {"action": Action(value=65)},
        {"revision": 99},
        {"plant_id": "other"},
        {"expires_at": now() - timedelta(minutes=1)},
    ],
)
def test_rejection_has_no_side_effects(platform, changes):
    state = platform.connector.disturb("kiln", "heat_load")
    with pytest.raises(Rejected):
        platform.gateway.execute(proposal(platform, **changes), "cmd", "kiln")
    assert platform.store.plant("kiln") == state


@pytest.mark.parametrize(
    "field,value",
    [
        ("quality", "bad"),
        ("mode", "manual"),
        ("sampled_at", now() - timedelta(hours=1)),
        ("sampled_at", now() + timedelta(hours=1)),
    ],
)
def test_preconditions(platform, field, value):
    state = platform.connector.disturb("kiln", "heat_load")
    setattr(state, field, value)
    platform.store.put("plants", "kiln", state)
    with pytest.raises(Rejected):
        platform.gateway.execute(proposal(platform), "cmd", "kiln")


def test_forecast_never_mutates_state(platform):
    state = platform.connector.disturb("kiln", "heat_load")
    copy = state.model_dump_json()
    assert simulate(state, Action(value=36)).recovered
    assert state.model_dump_json() == copy
    assert platform.store.plant("kiln") == state


def test_command_id_replay_and_conflicts(platform):
    platform.connector.disturb("kiln", "heat_load")
    request = proposal(platform)
    receipt = platform.gateway.execute(request, "cmd", "kiln")
    state = platform.store.plant("kiln")
    assert platform.gateway.execute(request, "cmd", "kiln") == receipt
    assert platform.store.plant("kiln") == state
    with pytest.raises(Rejected, match="conflicts"):
        platform.gateway.execute(proposal(platform, action=Action(value=35)), "cmd", "kiln")


def test_receipt_failure_rolls_back_state(platform):
    state = platform.connector.disturb("kiln", "heat_load")
    platform.store.db.execute(
        "CREATE TRIGGER reject BEFORE INSERT ON commands BEGIN "
        "SELECT RAISE(ABORT,'receipt failed'); END"
    )
    with pytest.raises(Exception, match="receipt failed"):
        platform.gateway.execute(proposal(platform), "cmd", "kiln")
    assert platform.store.plant("kiln") == state


@pytest.mark.parametrize(
    "changes",
    [{"escalation": "Ambiguous"}, {"action": None}, {"expires_at": now().replace(tzinfo=None)}],
)
def test_invalid_proposal_contract(platform, changes):
    with pytest.raises(ValidationError):
        proposal(platform, **changes)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_controls(value):
    with pytest.raises(ValidationError):
        Action(value=value)


def test_wrong_units_are_rejected_by_schema():
    with pytest.raises(ValidationError):
        Action(value=36, unit="bar")
