# Optimization core

Searches the twin for thermal-duty candidates and reports trade-offs.

## Authority

Never issues commands. Owns execution of an approved `thermal_duty` order, which still passes through the Gateway.

## Escalation

No always-on monitor. It runs when the main harness asks, or when an order needs execution.

## Files

| File | Role |
|---|---|
| `instruction.md` | identity, boundaries, output contract |
| `agent.py` | assembles the ADK agent only |
| `schemas.py` | structured outputs |
| `monitor.py` | always-on deterministic simulated model, no LLM |
| `reference.py` | offline analyser with the same output as the agent |
| `tools/` | one tool per file |
| `skills/` | procedures (Agent Skills spec) |

## Tools

| Tool | Kind | What it does |
|---|---|---|
| `optimization_evaluate_candidate` | read | Forecast one thermal-duty percentage on a twin copy and compare with doing nothing. |
| `optimization_execute_order` | action | Apply the thermal-duty change the platform approved, through the Gateway. |
| `optimization_read_followup_status` | read | Read how many follow-up corrections an order has had and whether one is pending. |
| `optimization_read_problem_context` | read | Read temperature, target, band, duty limits and the business numbers that matter. |
| `optimization_request_evidence` | read | Ask the learning, vision or robot core for evidence relevant to an objective. |
| `optimization_search_duty` | read | Rank safe thermal-duty values on a twin copy for a goal, with trade-offs. |
| `optimization_solve_assignment` | read | Solve a small exact problem: when to repair, who gets the spares, or which robot goes. |

## Skills

| Skill | Use |
|---|---|
| `maintenance-windows` | Decide when to repair, who gets scarce spares and which robot goes first. |
| `problem-formulation` | Turn a request into an objective, constraints and a starting point. |
| `tradeoff-reporting` | Report candidates and what each gives up. |
| `twin-search-methods` | Search the twin for duty candidates and verify any answer with math tools. |
| `core-report-writing`, `bus-requests` | shared by every core |

## Testing

- `pytest tests/cores` runs the monitor, reference analyser, tools and agent wiring offline.
- `tests/eval/optimization/` holds the ADK eval set. The offline test replays it with a scripted model. Running it against a live model is done only with the owner's approval.
