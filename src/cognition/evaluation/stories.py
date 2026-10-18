"""Demo stories: one scripted sequence per plant. Data first, so tests, the evaluator and the
live runner all play exactly the same thing."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from cognition.domain import Industry


@dataclass(frozen=True)
class Step:
    at: int  # ticks in the evaluator, about seconds against a live server at 1 s per tick
    action: Literal["inject", "clear", "automation"]
    kind: str = ""
    severity: float = 0.7
    ramp_ticks: int | None = None
    note: str = ""


@dataclass(frozen=True)
class Expect:
    detect: tuple[str, ...] = ()  # equipment that must raise a notify or escalate alert
    false_alarms: int | None = 0
    resolved_min: int = 0
    escalated_text: str = ""  # text one escalated incident must contain
    all_faults_cleared: bool = False


@dataclass(frozen=True)
class Story:
    id: str
    industry: Industry
    title: str
    summary: str
    steps: tuple[Step, ...]
    watch: tuple[str, ...]
    expect: Expect = field(default_factory=Expect)
    max_ticks: int = 500


STORIES: dict[str, Story] = {
    story.id: story
    for story in (
        Story(
            "cement-quiet",
            Industry.CEMENT,
            "Cement plant, nothing wrong",
            "A control run. The cores must stay quiet and no investigation should start.",
            (),
            ("All four core lamps stay green.", "No alerts appear in the core bus timeline."),
            Expect(false_alarms=0),
            max_ticks=200,
        ),
        Story(
            "cement-bearing-wear",
            Industry.CEMENT,
            "Kiln drive bearing wear",
            "One mechanical fault: vibration and current rise, the drive camera sees a hotspot.",
            (Step(0, "inject", "kiln_drive_bearing_wear", 0.9, 4, "Bearing starts to wear"),),
            (
                "Learning core raises the drive alert; vision and robot follow.",
                "The inspector verifies the drive in person (T0).",
                "A repair order runs: lock-out, Gateway repair, unlock. A work order completes.",
            ),
            Expect(detect=("drive",), resolved_min=1, all_faults_cleared=True),
        ),
        Story(
            "cement-flame-tariff",
            Industry.CEMENT,
            "Cement flame instability with a tariff peak",
            "Unsteady flame heats the kiln while the electricity price spikes. The plant must "
            "recover and the energy trade-off shows in Optimization and Impact.",
            (
                Step(0, "inject", "flame_instability", 0.7, 20, "Flame becomes unstable"),
                Step(8, "inject", "tariff_peak", 1.0, 5, "Tariff peak starts"),
            ),
            (
                "Draft and oxygen swings alert on the kiln; temperature drifts out of band.",
                "Switch the Optimization goal to Energy and compare fuel and CO2e.",
                "Impact shows the tariff multiplier and the energy cost per hour rising.",
            ),
            Expect(detect=("kiln",), resolved_min=1),
        ),
        Story(
            "steel-roller-spare",
            Industry.STEEL,
            "Steel roller wear, surface defects and a spare shortage",
            "A repair is needed but the roller bearing spare is out of stock. The harness must "
            "escalate with the lead time. Once the shortage ends, the repair goes ahead.",
            (
                Step(0, "inject", "spare_shortage", 1.0, 0, "Spares unavailable"),
                Step(0, "inject", "roller_bearing_wear", 0.8, 6, "Roller bearing wears"),
                Step(3, "inject", "billet_surface_defect", 0.8, 10, "Surface defects appear"),
                Step(70, "clear", "spare_shortage", note="Shortage ends"),
                Step(71, "automation", note="Operator re-enables autopilot"),
            ),
            (
                "Learning and vision cores agree: signals and surface camera.",
                "The first investigation escalates: spare part not in inventory.",
                "Impact lists a spare reorder recommendation.",
                "After the shortage ends and autopilot is re-enabled, the repair runs.",
            ),
            Expect(detect=("rollers", "billets"), resolved_min=1, escalated_text="inventory"),
            max_ticks=600,
        ),
        Story(
            "chemical-jacket-leak",
            Industry.CHEMICAL,
            "Chemical jacket fouling with a pipe leak",
            "Two faults on different equipment: slow heat transfer in the jacket and a leak on "
            "the piping. Repairs cost more output than they return inside the planning horizon, "
            "so the Optimization core advises against an automatic repair and the harness "
            "escalates with the numbers.",
            (
                Step(0, "inject", "jacket_fouling", 0.8, 40, "Jacket fouls"),
                Step(15, "inject", "pipe_leak", 0.7, 15, "Piping starts to leak"),
            ),
            (
                "Gas and leak-camera evidence appears for the pipes, flow evidence for the jacket.",
                "The first investigation escalates and cites the Optimization repair-window plan.",
                "Work orders are drafted for the operator to decide on in the Cores tab.",
            ),
            Expect(detect=("jacket", "pipes"), escalated_text="optimization"),
            max_ticks=700,
        ),
    )
}


def apply_step(client: Any, base: str, step: Step) -> str:
    """Play one step against a running server through the public API."""
    if step.action == "inject":
        payload: dict[str, Any] = {"kind": step.kind, "severity": step.severity}
        if step.ramp_ticks is not None:
            payload["ramp_ticks"] = step.ramp_ticks
        client.post(f"{base}/faults", json=payload).raise_for_status()
        return f"injected {step.kind}"
    if step.action == "clear":
        active = client.get(f"{base}/faults").json()
        match = next((e for e in active if e["kind"] == step.kind), None)
        if match:
            client.delete(f"{base}/faults/{match['id']}").raise_for_status()
        return f"cleared {step.kind}"
    client.post(
        f"{base}/automation",
        json={
            "mode": "autopilot",
            "harness": "reference",
            "interval_seconds": 0.5,
            "cooldown_seconds": 0,
            "max_investigations": 6,
        },
    )
    return "autopilot on"


def run_story(
    client: Any,
    story: Story,
    plant_id: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
    reset: bool = True,
) -> list[str]:
    """Play a story against a running server. Automation starts in autopilot unless stopped."""
    base = f"/api/plants/{plant_id}"
    log: list[str] = []

    def note(text: str) -> None:
        log.append(text)
        say(text)

    note(f"Story: {story.title}")
    note(story.summary)
    if reset:
        client.delete(f"{base}/automation")
        client.post(f"{base}/world/stop")
        client.post(f"{base}/reset").raise_for_status()
    client.post(f"{base}/world/start", json={"interval_seconds": 1.0})
    client.post(
        f"{base}/automation",
        json={
            "mode": "autopilot",
            "harness": "reference",
            "interval_seconds": 0.5,
            "cooldown_seconds": 0,
            "max_investigations": 6,
        },
    )
    clock = 0
    for step in sorted(story.steps, key=lambda s: s.at):
        if step.at > clock:
            sleep(step.at - clock)
            clock = step.at
        done = apply_step(client, base, step)
        note(f"t+{step.at:>3}s  {done}" + (f" ({step.note})" if step.note else ""))
    note("Watch for:")
    for line in story.watch:
        note(f"  - {line}")
    return log
