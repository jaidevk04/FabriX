# Fabrix

Fabrix is a **meta-automation harness**: an intelligence layer that sits on top of existing, deterministic industrial automation and gives it a mind. It does not replace the PLCs, DCS and interlocks already in place. It reads what they and the plant's sensors report, reasons about *why* something is happening, anticipates what comes next, and proposes what to do about it.

This repository is a working, simulation-based prototype of that idea. It models a cement kiln, a steel reheating furnace and a chemical reactor, watches them with four specialist cores, and lets AI agents investigate faults and propose a fix. The main investigating agent runs on the Antigravity SDK, and the four core agents run on Google ADK, both with Gemini.

The rule that holds everything together: **cognition proposes, a deterministic gateway validates, the plant executes.** An agent can only return one typed proposal (a single action or an escalation). Only the Gateway can change a plant, and it checks every command against the live state first. Speed and intelligence buy no exemption.

## The idea: a technological organism

Fabrix is built around a biological metaphor, summarised in three pictures.

### Horse, rider and saddle

| Part | Role | In this prototype |
| --- | --- | --- |
| **Horse** (System 1) | Existing deterministic automation: precise, tireless, real-time, blind to wider context | The simulated plant with its feedback control and safety cutoff |
| **Rider** (System 2) | A cognitive agent layer that brings intention, context and reasoning, and copes with novelty | The main agent harness plus the core agents |
| **Saddle** | Middleware that turns intent into machine commands and enforces safety *before* actuation | The Gateway and the order pipeline |

### Three layers, by timescale and authority

| Layer | Brain analogy | Timescale | Role | In this prototype |
| --- | --- | --- | --- | --- |
| Reflexive | Reptilian core | microseconds to milliseconds | Hard real-time control and interlocks. The only layer that actuates. | Simulated feedback control, a high-temperature cutoff and robot zone interlocks |
| Perceptual | Limbic system | milliseconds to seconds | Learned pattern recognition and prediction | Core monitors and a simulated sensor model, evaluated on every tick |
| Cognitive | Neocortex | seconds to minutes | Reasoning, planning, cross-domain correlation | Agent investigations, which take tens of seconds to minutes |

The cognitive layer does not micro-manage the fast loops. It sets their set-points, monitors them, and steps in when context changes the right answer. In the prototype the lever is the thermal duty set-point, which the reflexive feedback then regulates around.

### Homeostasis

Like an organism, Fabrix tries to hold a set of operational set-points (temperature, throughput, quality, energy) in a dynamic equilibrium: **sense, reason, validate, act, and feed back.** Because it forecasts on a copy of the plant before acting, it can correct a developing deviation rather than only react to one.

### Human authority

Operators can override any recommendation, and the platform records it. When an agent cannot or should not act, it escalates to the operator with its evidence instead of guessing.

## The cores: faculties as services

A core is a specialist faculty that the cognitive layer, and the other cores, can call on demand. They are not wired into every workflow. The agent asks for exactly the faculty a situation needs, when it needs it.

| Faculty | Capacity | Prototype core |
| --- | --- | --- |
| Learning | Learn, model and detect drift in signals | **Learning**: multi-rate signals fused by a simulated sensor model, with per-channel baselines, spectra and learned bands |
| Vision | See: measurement and open-ended scene understanding | **Vision**: camera feeds (placeholder frames or recorded clips) read by a simulated detector |
| Robot | Feel and act physically | **Robot**: a simulated inspector, maintainer and carrier fleet with zone interlocks, inspection and repair missions |
| Optimization | Weigh options against objectives | **Optimization** (specific to this prototype): twin search and repair-window planning over a copy of the plant. It owns thermal-duty execution. |

Each core has an always-on, deterministic monitor with a simulated model, a Google ADK agent that is woken when the monitor raises an alert, and scoped tools. Agents are switched on with `COGNITION_CORE_AGENTS=true`. If the model is unavailable, the core's deterministic analyser answers and the UI marks it degraded. Cores answer through an in-process bus (the `ask_core` tool), and advisory external A2A specialists can be registered. All data and models are simulated, with no real ML, cameras or robots.

### What the prototype covers and what it does not

| Implemented in the prototype | Described by the architecture, not implemented here |
| --- | --- |
| Propose, validate, execute with a deterministic Gateway | A separate "Meta-Rider" ethical governor (its hard-constraint role is covered by the Gateway and the operator controls) |
| Reflexive, perceptual and cognitive layers with tiered loops | The DREAM consolidation process and drift-driven model retraining |
| Agent harnesses (Antigravity SDK, Google ADK) using MCP tools and Agent Skills | A persistent memory and knowledge graph |
| Faculties summoned on demand through `ask_core` | Native physical-AI models (sensor-language, vision-language-action, world models) |
| Anticipatory checks: a twin forecast must recover the plant and beat doing nothing | Negotiated arbitration among competing domain agents |
| Human authority: supervised approval, escalation decisions, Stop and a kill switch | An evolving personality, voice or natural-language briefings |
| A full audit trail and an explainable incident record | Federated learning across sites and the deployment topologies beyond a container |
| The same pattern on three industries, with new industries added as packs | |

## What you get

- **Three plants** (cement, steel, chemical) with feedback control, actuator lag, faults and a live world clock.
- **Four cores**: Learning, Vision, Robot and Optimization.
- **Live AI agents**: the main investigating agent runs on the **Antigravity SDK** and is chosen in the studio. The four core agents run on **Google ADK**, and an ADK main-harness adapter is available through the API. Both use Gemini.
- **An operator UI**: a fleet overview, a 3D operations studio (digital twin, process flow, HMI screens), Specialist Faculties, an Agent estate map, Investigations, Impact and an asset registry.
- **Repairs with consequences**: lock-out, repair and unlock missions with simulated downtime, spare parts, work orders and a business and sustainability ledger.
- **Safety controls**: response modes (observe, supervised, autopilot), Stop, a kill switch, "stop after N verified recoveries", and operator decisions when an agent escalates.

## Quick start

### Docker

```bash
cp .env.example .env          # add GOOGLE_API_KEY (or the Vertex AI settings)
docker compose up -d --build
```

Open <http://localhost:8000> (change the published port with `FABRIX_PORT`). Data is kept in the `fabrix-data` volume. Keys are read from `.env` at run time and are never copied into the image.

The agents need Gemini access: set `GOOGLE_API_KEY` (or the Vertex AI settings) in `.env`, and set `COGNITION_CORE_AGENTS=true` to run the four core agents. Agent runs make live model calls that can incur charges.

### Local launcher

Requires Python 3.12 or newer.

```bash
bash start.sh                 # Linux / macOS
start.cmd                     # Windows
```

The launcher creates a single `.venv`, installs the dependencies, creates `.env` if it is missing, starts the server and opens the browser. Options: `--port 8010`, `--no-browser`, `--setup-only`, `--repair` (on Windows: `-Port`, `-NoBrowser`, `-SetupOnly`, `-Repair`).

### Manual

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp,adk,antigravity]"
cognition serve               # http://127.0.0.1:8000
```

The command-line tool is called `cognition`, and the settings use the `COGNITION_` prefix.

## Try it

1. Open **Operations studio**, choose a plant, set Response mode to **Autopilot** and the Agent harness to **Antigravity** (it shows "setup required" until a Gemini key is configured), then press **Start main plant simulation**.
2. In **Inject disturbance**, pick a fault (for example *Kiln drive bearing wear* on cement, or *Burner out* on steel) and press **Inject**.
3. Watch the Live activity strip. The cores raise alerts and their agents analyse, the main agent investigates, the Gateway validates one action, a robot repairs, and the platform verifies recovery on ten steady samples.
4. Visit **Specialist Faculties**, **Agent estate**, **Investigations** and **Impact** to see the evidence, the agent logs, the incident record and the work order.

Other handy controls: **Stop after N recoveries** ends the whole run once N recoveries are verified, and **Reset plant** returns it to baseline.

When an agent cannot or should not act, the run shows **Needs attention** with its reason. You can **Mark fixed** (tells the simulator the problem was repaired and clears the faults), **Investigate again**, or **Dismiss**.

## How an incident flows

A monitor or the automation notices a deviation. The main harness investigates with scoped read and simulation tools and can ask the cores for evidence. It returns one proposal. The platform checks the plant scope, revision, expiry, telemetry freshness, control bounds, and a twin forecast that must recover the plant and beat doing nothing. The order then goes to the owning core, and the Gateway or FleetGateway writes the receipt. In live mode the plant keeps ticking during an investigation, so a duty order that has gone stale is re-sized from the live state before it runs. Recovery is then verified on ten fresh in-band samples.

**Guarantees**

- Only `Gateway.execute` writes plant state, and only `FleetGateway` writes robot missions.
- Commands are idempotent by id and proposal digest.
- Monitors and analysers use sensor-derived evidence only. They never read injected-event labels.
- No hidden retries. A failed run ends as `failed` or `interrupted` and is never re-run silently.
- Exception messages are never stored, because they can contain credentials. Only the exception type is recorded.
- Automation is never re-enabled on restart.

## Configuration

Copy `.env.example` to `.env`. Process environment variables take precedence over `.env`. Restart after editing.

| Setting | Purpose | Default |
| --- | --- | --- |
| `GOOGLE_API_KEY`, `GEMINI_MODEL` | Gemini access and model id | none |
| `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex AI instead of an API key | `false`, none, `us-central1` |
| `COGNITION_DB` | SQLite database path | `data/platform.db` |
| `COGNITION_TIMEOUT` | Seconds allowed for one main-harness investigation | `120` |
| `COGNITION_CORE_AGENTS` | Run the Google ADK core agents (live model calls) | `false` |
| `COGNITION_CORE_MODEL` | Model for the core agents | `GEMINI_MODEL` |
| `COGNITION_CORE_RUN_SECONDS` | Wall-clock ceiling for one core run, `0` is off | `600` |
| `COGNITION_KILL_AFTER_SECONDS` | Stop every agent this long after a run starts, `0` is off | `0` |
| `COGNITION_LIVE_DRIFT` | Plant revisions a proposal may lag behind | `300` |
| `COGNITION_STRICT_MODE` | Freeze sampling during investigations, exact revisions | `false` |
| `COGNITION_TOOL_CAP` | Main-harness tool calls per incident | `200` |
| `COGNITION_WORLD_AUTOSTART` | Start every plant's world clock at launch | `false` |
| `COGNITION_HOST`, `COGNITION_PORT` | Listen address of `cognition serve` | `127.0.0.1`, `8000` |
| `COGNITION_<NAME>_PYTHON` | Run a harness (`ADK`, `ANTIGRAVITY`) in a child process using this environment | blank (in-process) |

## Deploying

The image runs one `cognition serve` process. **The API has no authentication**, so do not expose it directly to the internet. Put it behind an authenticating reverse proxy, a VPN, or a platform with identity checks.

- Run a **single instance**: runs, the world clock and the agents live in one process and in SQLite.
- Keep **CPU always allocated** on serverless platforms, or the simulation stalls between requests.
- Treat storage as **ephemeral** unless you mount a persistent volume for `/data`.
- Give streaming (server-sent event) endpoints a long request timeout and no response buffering.

## Command-line tools

```text
cognition serve [--host H] [--port P]   start the UI and API
cognition mcp                           read-only stdio MCP facade
```

The stdio MCP facade needs the API running and offers `list_plants`, `discover_capabilities` and `predict_action`. It exposes no plant writer.

## Project layout

| Path | Responsibility |
| --- | --- |
| `src/cognition/domain.py` | Typed contracts: state, proposals, receipts, orders |
| `src/cognition/api/` | FastAPI app, schemas and grouped routers |
| `src/cognition/runtime/` | Incident lifecycle, automation, world clock, orders, UI read models |
| `src/cognition/control/` | Gateway, maintenance rules, fleet gateway, connectors |
| `src/cognition/simulation/` | Thermal model and fault engine |
| `src/cognition/industries/` | Cement, steel and chemical packs: signals, faults, tools, skills |
| `src/cognition/layers/` | Reflexive, perceptual and cognitive layers |
| `src/cognition/cores/` | Learning, vision, robot and optimization cores |
| `src/cognition/harnesses/` | Harness contract and the Antigravity and ADK adapters |
| `src/cognition/mcp/` | MCP servers (incident-local, private command server, stdio facade) |
| `src/cognition/business/`, `sensing/` | Business and sustainability model, signal, camera and fleet simulators |
| `src/cognition/insights/` | KPIs, impact ledger, reports, work orders, recommendations |
| `src/cognition/persistence/` | SQLite store and audit trail |
| `src/cognition/web/` | The UI: vanilla JavaScript, vendored Three.js, no build step |
| `scripts/` | Setup, SDK checks and packaging helpers |
| `tests/` | Pytest suite |

## Development

```bash
ruff check .
ruff format --check .
mypy src/cognition
pytest -q
python scripts/core_docs.py     # regenerate the core tool and skill tables
```

Tests never make live model calls. Each core has its own README under `src/cognition/cores/<core>/`.

## Limitations

- Everything is simulated: plants, sensors, cameras, robots and the learned models. The plants are educational thermal surrogates, not calibrated digital twins, and nothing connects to real PLC, DCS or OT systems.
- Business factors, prices and emission factors are placeholders.
- There is no operator authentication or role-based access. Supervised approval is a local workflow.
- One application process is assumed. Distributed worker leases are not implemented.
- Worker isolation separates dependencies and makes cancellation clean. It is not a sandbox for untrusted code.
- Live model calls depend on credentials, quota and model availability, and can incur provider charges.
- Detection and attribution are by signal, so an alert may name a neighbouring equipment group.
