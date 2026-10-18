"""Read model for the operations UI; forecasts, proposals and receipts stay distinct."""

from cognition.domain import SECONDS_PER_TICK, Action, Receipt, sim_clock
from cognition.industries import PACKS, get_industry
from cognition.layers.reflexive import assess
from cognition.runtime.platform import Platform


def operations(platform: Platform, plant_id: str, automation) -> dict:
    state = platform.connector.snapshot(plant_id)
    perception = platform.perception.assess(state)
    latest = next((item for item in platform.store.incidents() if item.plant_id == plant_id), None)
    receipt = None
    if latest:
        try:
            receipt = Receipt.model_validate_json(platform.store.get("commands", latest.id))
        except KeyError:
            pass
    run = automation.state(plant_id)
    events = platform.store.events(latest.id) if latest else []
    allowed_events = {
        "started",
        "proposed",
        "approval_requested",
        "approval_decided",
        "command_dispatch",
        "command_committed",
        "action_applied",
        "measurement",
        "verified",
        "verification_failed",
        "cancelled",
        "completed",
    }
    evidence = [
        event
        for event in events
        if event["kind"] in allowed_events and event["kind"] != "measurement"
    ]
    evidence.extend([event for event in events if event["kind"] == "measurement"][-5:])
    evidence.sort(key=lambda event: event["seq"])
    return {
        "snapshot": state.model_dump(mode="json"),
        "time": {
            "simulated_seconds": state.sim_seconds,
            "simulated_clock": sim_clock(state.sim_seconds),
            "tick": state.tick,
            "seconds_per_tick": SECONDS_PER_TICK,
            "advancing": bool(run.enabled or platform.world.running(plant_id)),
            "world_running": platform.world.running(plant_id),
            "kill": platform.world.kill_state(plant_id),
        },
        "industry": get_industry(state.spec.industry).PROFILE.id,
        "skill": get_industry(state.spec.industry).PROFILE.skill,
        "limits": {
            "band": PACKS[state.spec.industry].band,
            "envelope": PACKS[state.spec.industry].envelope,
            "gain": PACKS[state.spec.industry].gain,
            "asset": PACKS[state.spec.industry].asset,
        },
        "reflexive": assess(state),
        "perceptual": perception,
        "cognitive": {
            "phase": run.phase if run.enabled or run.phase == "attention" else "idle",
            "harness": run.config.harness if run.enabled else latest.harness if latest else None,
            "reason": run.reason
            if run.enabled
            else latest.reason
            if latest
            else "No investigation yet.",
            "authority": "Scoped proposal; official MCP dispatch through independent gateway.",
        },
        "incident": latest.model_dump(mode="json") if latest else None,
        "receipt": receipt.model_dump(mode="json") if receipt else None,
        "events": evidence,
        "response": {
            "proposed_duty": latest.proposal.action.value
            if latest and latest.proposal and isinstance(latest.proposal.action, Action)
            else None,
            "applied": receipt is not None,
            "measured_duty": state.duty,
            "measured_actuator": state.actuator,
            "measured_temperature": state.temperature,
            "verified": bool(
                receipt
                and receipt.recovered
                and receipt.verification == "completed"
                and state.quality == "good"
                and not state.stuck
                and not state.interlock
                and state.mode == "automatic"
                and abs(state.temperature - state.target) <= PACKS[state.spec.industry].band
            ),
            "source": "Fresh simulator samples" if run.enabled else "Current simulator snapshot",
        },
    }
