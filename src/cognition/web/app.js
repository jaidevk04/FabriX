import {
  temperatureInstrument,
  dutyInstruments,
} from "./instruments.js?v=fabrix-20261013-1";
import { investigationConsole } from "./console.js";
import { industryInstruments } from "./process-instruments.js";
import { operationsView } from "./operations.js";
import { plantViews } from "./plant-views.js?v=fabrix-20261020-6";
import { fleetView } from "./fleet.js";
import { addPlantPage } from "./add-plant.js";
import { impactPage } from "./impact.js?v=fabrix-20261018-1";
import { facultiesPage } from "./faculties.js";
import { agentsPage } from "./agents.js";
const terminal = investigationConsole();
const $ = (id) => document.getElementById(id);
const make = (tag, text, className) => {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (className) e.className = className;
  return e;
};
const layers = operationsView();
let operationsToken = 0;
// Applies one /operations read model to the twin, gauges and process instruments.
function applyOperations(data) {
  const id = data.snapshot.spec.id;
  if(id !== selectedId) return;
  plants = plants.map(p => p.spec.id === id ? plantLabel(data.snapshot) : p);
  layers.update(data);
  scene?.setState(data.snapshot);
  if(viewingSnapshot) renderTelemetry();
  industryInstruments({plant_id:id,revision:data.snapshot.revision,sim_seconds:data.snapshot.sim_seconds,indicators:data.perceptual.indicators});
  $("process-instruments-title").textContent = {cement:"Kiln & cooler instruments",steel:"Furnace & line instruments",chemical:"Reactor & jacket instruments"}[data.snapshot.spec.industry];
}
async function loadOperations(id) {
  if(currentPage !== "studio") return;
  const token = ++operationsToken;
  try {
    const data = await api(`/api/plants/${encodeURIComponent(id)}/operations`);
    if(token !== operationsToken || id !== selectedId) return;
    applyOperations(data);
  } catch(error) {
    if(token === operationsToken && id === selectedId) layers.unavailable();
  }
}
// Legacy seeded names ("Cement demo") are shown as plants ("Cement plant").
function plantLabel(p) {
  p.spec.name = p.spec.name.replace(/^(Cement|Steel|Chemical) demo$/i, "$1 plant");
  return p;
}
let plants = [],
  incidents = [],
  selectedId = null,
  selectedIncident = null,
  scene = null,
  busy = false;
let trajectory = [],
  trajectoryTarget = 0,
  trajectoryType = "",
  step = 0,
  playing = false,
  playTime = 0,
  previewRevision = null;
let detailToken = 0;
let instrumentToken = 0;
let automationStates = [];
let views = null;
async function loadInstruments(id) {
  const token = ++instrumentToken;
  try {
    const data = await api(`/api/plants/${encodeURIComponent(id)}/instruments`);
    if(token !== instrumentToken || id !== selectedId) return;
    industryInstruments(data);
    $("process-instruments-title").textContent = {
      cement: "Kiln & cooler instruments", steel: "Furnace & line instruments", chemical: "Reactor & jacket instruments",
    }[state().spec.industry];
  } catch (error) {
    if(token !== instrumentToken) return;
    industryInstruments(null);
    $("process-instruments-source").textContent = "Unavailable";
  }
}
const page = location.pathname.split("/")[1] || "fleet";
const pages = {
  fleet: [
    "Plants",
    "Plant fleet",
    "Live condition, process indicators and investigation history for every plant.",
  ],
  studio: [
    "Operations studio",
    "Asset operations",
    "Equipment, process instruments and investigation controls.",
  ],
  faculties: [
    "Specialist Faculties",
    "Cognitive cores",
    "The live world and the four cores that watch it: learning, vision, robot and optimization.",
  ],
  agents: [
    "Agent estate",
    "Agent orchestration",
    "How the main harness, the core agents and the gateways connect, and what each is doing live.",
  ],
  investigations: [
    "Investigations",
    "Incident intelligence",
    "Review proposals, validated responses and the evidence behind every outcome.",
  ],
  impact: [
    "Impact",
    "Business and sustainability",
    "KPIs, orders, energy and CO2e, recommendations, and what each action achieved.",
  ],
  assets: [
    "Add plant",
    "Onboarding",
    "Register another plant from an industry process pack, or import a manifest.",
  ],
  system: [
    "System & harnesses",
    "Platform configuration",
    "Inspect runtime capabilities and available investigation engines.",
  ],
};
const currentPage = pages[page] ? page : "fleet";
document.body.dataset.workspace = currentPage;
document.documentElement.dataset.workspace = currentPage;
document
  .querySelectorAll("[data-pages]")
  .forEach(
    (e) => (e.hidden = !e.dataset.pages.split(" ").includes(currentPage)),
  );
document.querySelectorAll("[data-nav]").forEach((e) => {
  if (e.dataset.nav === currentPage) e.setAttribute("aria-current", "page");
});
const [title, kicker, description] = pages[currentPage];
$("page-title").textContent = title;
$("breadcrumb").textContent = title;
$("page-kicker").textContent = kicker;
$("page-description").textContent = description;
document.title = `${title} | Fabrix`;
document.documentElement.classList.add("ready");
let temperatureUnit = "C";
let viewingSnapshot = true;
let fleetQuery = "",
  incidentFilter = "all";
function table(headers, rows) {
  const t = make("table"),
    head = make("thead"),
    hr = make("tr"),
    body = make("tbody");
  headers.forEach((h) => {
    const th = make("th", h);
    th.scope = "col";
    hr.append(th);
  });
  head.append(hr);
  rows.forEach((r) => {
    [...r.children].forEach((td, index) => (td.dataset.label = headers[index]));
    body.append(r);
  });
  t.append(head, body);
  return t;
}
function cell(content, className) {
  const td = make("td", undefined, className);
  td.append(
    typeof content === "string" ? document.createTextNode(content) : content,
  );
  return td;
}
function empty(text, hint) {
  const e = make("div", undefined, "empty-state");
  e.append(make("strong", text), make("span", hint));
  return e;
}
function renderRegisters() {
  const history = [...incidents].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at),
  );
  const count = (status) => history.filter((i) => i.status === status).length;
  $("inv-summary").textContent = history.length
    ? `${history.length} investigations · ${count("resolved")} recovered · ${count("escalated")} escalated · ${count("failed")} failed`
    : "No investigations yet";
  const entries = history
    .filter((i) => incidentFilter === "all" || i.status === incidentFilter)
    .map((i) => {
      const row = make("tr"),
        open = make("button", "Inspect evidence", "secondary");
      open.disabled = busy;
      open.onclick = async () => {
        try {
          selectPlant(i.plant_id);
          await inspect(i);
          $("evidence").scrollIntoView({
            block: "center",
            behavior: "instant",
          });
        } catch (error) {
          notify(error.message, true);
        }
      };
      row.append(
        cell(make("span", i.status, `status ${i.status}`)),
        cell(i.plant_id),
        cell(i.harness),
        cell(new Date(i.created_at).toLocaleString()),
        cell(i.id.slice(0, 8)),
        cell(open),
      );
      return row;
    });
  $("incident-register").replaceChildren(
    entries.length
      ? table(
          ["Outcome", "Twin", "Harness", "Created", "Incident", "Details"],
          entries,
        )
      : empty(
          "No matching investigations",
          "Run an investigation in Twin studio or change the status filter.",
        ),
  );
}
$("incident-filter").onchange = (e) => {
  incidentFilter = e.target.value;
  renderRegisters();
};
async function api(path, body) {
  const r = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
function notify(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
}
function state() {
  return plants.find((p) => p.spec.id === selectedId);
}
function controls() {
  for (const id of ["inject", "investigate", "reset", "refresh"]) {
    const el = $(id);
    if (el) el.disabled = busy || !state();
  }
  document
    .querySelectorAll(
      ".plant-choice, #onboard button, #incident-register button",
    )
    .forEach((b) => {
      b.disabled = busy;
    });
  if ($("harness")) $("harness").disabled = busy;
  if ($("scenario")) $("scenario").disabled = busy;
  if ($("active-twin")) $("active-twin").disabled = busy;
  // A running simulation owns the plant: its agent responds automatically, so a manual
  // investigation would be a second writer. Say why instead of just greying the button out.
  const live = views?.simActive() ?? false;
  if ($("investigate")) {
    $("investigate").disabled = busy || !state() || live;
    $("investigate").title = live ? "The agent is responding automatically while the simulation runs. Stop it for a manual investigation." : "";
  }
  if ($("reset")) $("reset").disabled = busy || !state() || live;
  if ($("harness")) $("harness").disabled = busy || live;
  if ($("manual-note")) $("manual-note").hidden = !live;
}
async function action(fn) {
  if (busy) return;
  busy = true;
  document.querySelector("main").setAttribute("aria-busy", "true");
  controls();
  try {
    await fn();
    await refresh();
  } catch (e) {
    notify(e.message, true);
  } finally {
    busy = false;
    document.querySelector("main").setAttribute("aria-busy", "false");
    controls();
  }
}
function clearTrajectory() {
  document.body.classList.remove("has-incident");
  viewingSnapshot = true;
  playing = false;
  trajectory = [];
  selectedIncident = null;
  previewRevision = null;
  detailToken++;
  plot();
  $("evidence-label").textContent = "PLATFORM AUDIT";
  $("play").disabled = true;
  $("scrub").disabled = true;
  $("play").textContent = "▶ Replay";
  $("step-label").textContent = "0 / 0";
  $("trajectory-kind").textContent = "AWAITING INVESTIGATION";
  $("caption").textContent =
    "Inject a fault and investigate, or simulate a what-if adjustment.";
  $("audit").replaceChildren();
  $("evidence").textContent =
    "Select an incident to inspect its proposal, evidence and execution record.";
  scene?.setState(state());
  renderTelemetry();
}
function renderFleet() {
  $("active-twin").replaceChildren(
    ...plants.map((p) => {
      const o = make("option", p.spec.name);
      o.value = p.spec.id;
      o.selected = p.spec.id === selectedId;
      return o;
    }),
  );
  $("plants").replaceChildren();
  for (const p of plants) {
    const b = make(
      "button",
      undefined,
      `plant-choice ${p.spec.id === selectedId ? "active" : ""}`,
    );
    b.dataset.plant = p.spec.id;
    b.setAttribute("aria-pressed", String(p.spec.id === selectedId));
    b.append(
      make("span", p.spec.industry.toUpperCase(), "tag"),
      make("strong", p.spec.name),
    );
    const row = make("div", undefined, "plant-meta");
    row.append(
      make("span", `${p.temperature.toFixed(1)} °C`),
      make(
        "span",
        p.quality === "bad"
          ? "Sensor fault"
          : p.stuck
            ? "Actuator fault"
            : p.disturbance
              ? "Disturbed"
              : "Nominal",
      ),
    );
    b.append(row);
    b.onclick = () => selectPlant(p.spec.id);
    $("plants").append(b);
  }
}
function renderTelemetry(value) {
  const p = state();
  if (!p) return;
  const t = value ?? p.temperature;
  temperatureInstrument(
    p,
    t,
    temperatureUnit,
    value === undefined
      ? "Snapshot"
      : trajectoryType === "prediction"
        ? "What-if response"
        : "Recorded response",
  );
  dutyInstruments(p);
  $("scene-reading").textContent =
    `${t.toFixed(1)} °C${value === undefined ? "" : " · replay"}`;
  $("scene-title").textContent = p.spec.name;
  $("industry-label").textContent =
    `${p.spec.industry.toUpperCase()} / ${p.spec.id}`;
  const unhealthy =
    p.quality === "bad" ||
    p.stuck ||
    Math.abs(p.temperature - p.target) >
      { cement: 20, steel: 18, chemical: 3 }[p.spec.industry];
  const label =
    p.quality === "bad"
      ? "Sensor fault"
      : p.stuck
        ? "Actuator stuck"
        : unhealthy
          ? "Disturbed"
          : "Within band";
  $("scene-status").textContent = label;
  $("scene-status").className = `status ${unhealthy ? "fault" : "healthy"}`;
  $("telemetry").replaceChildren();
  for (const [label, val] of [
    ["Target", `${p.target} °C`],
    ["Deviation", `${(p.temperature - p.target).toFixed(1)} °C`],
    ["Commanded duty", `${p.duty.toFixed(0)}%`],
    ["Actuator", `${p.actuator.toFixed(1)}%`],
    ["Signal quality", p.quality],
    ["State revision", `r${p.revision}`],
    ["Operating mode", p.mode],
    [
      "Last sample",
      new Date(p.sampled_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
    ],
  ]) {
    const m = make("div", label, "metric");
    m.append(make("strong", val));
    $("telemetry").append(m);
  }
}
function selectPlant(id) {
  if (busy || selectedId === id) return;
  selectedId = id;
  try { localStorage.setItem("fabrix.plant", id); } catch { /* storage unavailable */ }
  industryInstruments(null);
  loadInstruments(id);
  loadOperations(id);
  clearTrajectory();
  scene?.setState(state());
  renderFleet();
  renderTelemetry();
  renderIncidents();
  controls();
}
function renderIncidents() {
  const list = incidents.filter((i) => i.plant_id === selectedId);
  $("incidents").replaceChildren();
  $("activity-count").textContent =
    `${list.length} INCIDENT${list.length === 1 ? "" : "S"}`;
  if (!list.length)
    $("incidents").append(
      make(
        "p",
        "No incidents for this twin yet. Inject a disturbance to begin.",
      ),
    );
  for (const i of list.slice(0, 20)) {
    const row = make(
      "div",
      undefined,
      `incident ${i.id === selectedIncident ? "active" : ""}`,
    );
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.dataset.incident = i.id;
    row.append(
      make("span", i.status, `status ${i.status}`),
      make(
        "strong",
        i.harness === "reference"
          ? "Reference investigation"
          : `${i.harness} investigation`,
      ),
      make("p", i.reason || "Investigation running"),
      make(
        "time",
        new Date(i.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      ),
    );
    const open = () => inspect(i).catch((e) => notify(e.message, true));
    row.onclick = open;
    row.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    };
    $("incidents").append(row);
  }
}
function addSvg(tag, attrs, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  $("chart").append(e);
  return e;
}
function plot() {
  $("chart").replaceChildren();
  if (!trajectory.length) {
    addSvg(
      "text",
      {
        x: 360,
        y: 105,
        "text-anchor": "middle",
        fill: "#516c85",
        "font-size": 12,
      },
      "Your process response will appear here",
    );
    return;
  }
  const low = Math.min(...trajectory, trajectoryTarget) - 5,
    high = Math.max(...trajectory, trajectoryTarget) + 5;
  const y = (v) => 172 - ((v - low) / (high - low)) * 135,
    x = (i) => 62 + (i / Math.max(trajectory.length - 1, 1)) * 632;
  for (let i = 0; i < 4; i++) {
    const yy = 37 + i * 45;
    addSvg("line", { x1: 62, x2: 694, y1: yy, y2: yy, stroke: "#1c2c3e" });
    addSvg(
      "text",
      { x: 8, y: yy + 3, fill: "#66829b", "font-size": 10 },
      (high - (i * (high - low)) / 3).toFixed(0) + "°",
    );
  }
  addSvg("line", {
    x1: 62,
    x2: 694,
    y1: y(trajectoryTarget),
    y2: y(trajectoryTarget),
    stroke: "#6ca78e",
    "stroke-dasharray": "5 5",
  });
  addSvg(
    "text",
    {
      x: 570,
      y: Math.max(18, y(trajectoryTarget) - 7),
      fill: "#86b6a0",
      "font-size": 10,
    },
    `Target ${trajectoryTarget}°C`,
  );
  addSvg("polyline", {
    points: trajectory.map((v, i) => `${x(i)},${y(v)}`).join(" "),
    fill: "none",
    stroke: trajectoryType === "prediction" ? "#b67521" : "#237ea4",
    "stroke-width": 2.5,
  });
  addSvg("text", { x: 62, y: 194, fill: "#66829b", "font-size": 10 }, "0");
  addSvg(
    "text",
    { x: 596, y: 194, fill: "#66829b", "font-size": 10 },
    `${trajectory.length - 1} steps`,
  );
  addSvg("line", {
    id: "chart-cursor",
    x1: x(step),
    x2: x(step),
    y1: 22,
    y2: 179,
    stroke: "#a2bcde",
    "stroke-dasharray": "3 4",
  });
  addSvg("circle", {
    id: "chart-point",
    cx: x(step),
    cy: y(trajectory[step]),
    r: 4,
    fill: "#236ba1",
  });
  $("chart").onclick = (e) => {
    const rect = $("chart").getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * 720;
    playing = false;
    seek(Math.round(((px - 62) / 632) * (trajectory.length - 1)));
  };
}
function seek(value) {
  if (!trajectory.length) return;
  viewingSnapshot = false;
  step = Math.max(0, Math.min(trajectory.length - 1, value));
  $("scrub").value = step;
  $("step-label").textContent = `${step} / ${trajectory.length - 1}`;
  $("play").textContent = playing ? "Ⅱ Pause" : "▶ Replay";
  const low = Math.min(...trajectory, trajectoryTarget) - 5,
    high = Math.max(...trajectory, trajectoryTarget) + 5;
  const x = 62 + (step / Math.max(trajectory.length - 1, 1)) * 632,
    y = 172 - ((trajectory[step] - low) / (high - low)) * 135;
  const cursor = $("chart-cursor");
  if (cursor) {
    cursor.setAttribute("x1", x);
    cursor.setAttribute("x2", x);
    $("chart-point").setAttribute("cx", x);
    $("chart-point").setAttribute("cy", y);
  }
  scene?.setTemperature(trajectory[step]);
  renderTelemetry(trajectory[step]);
  $("scene-reading").textContent =
    `${trajectory[step].toFixed(1)} °C · ${trajectoryType === "prediction" ? "preview" : "replay"}`;
}
function setTrajectory(values, target, type) {
  trajectory = values;
  trajectoryTarget = target;
  trajectoryType = type;
  step = 0;
  playing = false;
  $("scrub").max = Math.max(values.length - 1, 0);
  $("scrub").disabled = !values.length;
  $("play").disabled = !values.length;
  $("trajectory-kind").textContent =
    type === "prediction" ? "WHAT-IF PREDICTION" : "RECORDED RESPONSE";
  plot();
  if (values.length) seek(0);
  else {
    $("play").textContent = "▶ Replay";
    $("step-label").textContent = "0 / 0";
    scene?.setState(state());
    renderTelemetry();
  }
}
async function inspect(incident) {
  const token = ++detailToken;
  selectedIncident = incident.id;
  previewRevision = null;
  const events = await api(`/api/incidents/${incident.id}/events`);
  if (token !== detailToken || incident.plant_id !== selectedId) return;
  terminal.show(incident, events);
  document.body.classList.add("has-incident");
  $("evidence").textContent = [
    incident.proposal?.summary || incident.reason,
    ...(incident.proposal?.evidence || []),
    incident.proposal?.action
      ? incident.proposal.action.control === "thermal_duty" || typeof incident.proposal.action.value === "number"
        ? `Proposed control: ${incident.proposal.action.control} → ${incident.proposal.action.value}%`
        : incident.proposal.action.control === "maintenance"
          ? `Proposed control: maintenance → ${incident.proposal.action.remedy} on ${incident.proposal.action.equipment}`
          : `Proposed control: monitor config → ${incident.proposal.action.setting} on ${incident.proposal.action.target || incident.proposal.action.core}`
      : "No control action proposed.",
    `Outcome: ${incident.status} — ${incident.reason}`,
  ].join("\n");
  if (currentPage === "investigations") $("evidence-panel").open = true;
  $("audit").replaceChildren(
    ...events.map((e) => make("span", e.kind.replaceAll("_", " "))),
  );
  $("evidence-label").textContent =
    `${incident.harness.toUpperCase()} / ${incident.id.slice(0, 8)}`;
  setTrajectory(incident.trajectory, state().target, "actual");
  $("caption").textContent = incident.trajectory.length
    ? `${state().spec.name} · validated control response · ${incident.trajectory.length - 1} steps`
    : "No command executed. Inspect the escalation or failure evidence.";
  renderIncidents();
}
async function refresh() {
  const [next, history, automation] = await Promise.all([
    api("/api/plants"),
    api("/api/incidents"),
    api("/api/automation"),
  ]);
  const before = state()?.revision;
  plants = next.map(plantLabel);
  incidents = history;
  automationStates = automation;
  if (!selectedId) {
    // The URL wins, then the plant last shown on any page; the first plant is only the last resort.
    let stored = null;
    try { stored = localStorage.getItem("fabrix.plant"); } catch { /* storage unavailable */ }
    const known = (id) => plants.find((q) => q.spec.id === id)?.spec.id;
    selectedId = known(new URLSearchParams(location.search).get("plant")) ?? known(stored) ?? null;
  }
  if (!selectedId || !state()) {
    selectedId = plants[0]?.spec.id;
    clearTrajectory();
  }
  const p = state();
  if (!p) return;
  try { localStorage.setItem("fabrix.plant", selectedId); } catch { /* storage unavailable */ }
  if (
    before !== undefined &&
    before !== p.revision &&
    previewRevision !== null
  ) {
    clearTrajectory();
    notify(
      "Twin changed. Previous prediction cleared; simulate again from the new revision.",
    );
  }
  scene?.setState(p);
  if (trajectory.length && !viewingSnapshot)
    scene?.setTemperature(trajectory[step]);
  renderFleet();
  renderTelemetry(
    trajectory.length && !viewingSnapshot ? trajectory[step] : undefined,
  );
  renderIncidents();
  controls();
  renderRegisters();
  if(currentPage === "studio") await loadOperations(selectedId);
  else await loadInstruments(selectedId);
  if(currentPage === "system") {
    const registry = await api("/api/registry");
    const table = make("table"), header = make("tr");
    for(const label of ["Plant","Kind","Capability","Transport","Access"]) header.append(make("th",label));
    const head = make("thead"); head.append(header); table.append(head);
    const body = make("tbody");
    for(const capability of registry) {
      const row = make("tr");
      for(const value of [capability.plant_id,capability.kind,capability.name,capability.transport,!capability.approved ? "Revoked" : capability.read_only ? "Read / predict" : "Gateway only"]) row.append(make("td",value));
      body.append(row);
    }
    table.append(body); $("registry-table").replaceChildren(table);
    const specialists = await api("/api/specialists");
    $("specialist-list").replaceChildren();
    for(const specialist of specialists) {
      const row = make("div",undefined,"specialist-row");
      row.append(make("span",`${specialist.name} · ${specialist.plant_ids.join(', ')} · ${specialist.approved ? 'Approved' : 'Revoked'}`));
      if(specialist.approved) {
        const revoke = make("button","Revoke approval","secondary");
        revoke.onclick = () => action(async () => { await fetch(`/api/specialists/${encodeURIComponent(specialist.id)}`,{method:'DELETE'}); await refresh(); });
        row.append(revoke);
      }
      $("specialist-list").append(row);
    }
  }
}
$("specialist-form").onsubmit = event => {
  event.preventDefault();
  const fields = new FormData(event.target);
  action(async () => {
    await api("/api/specialists",{id:fields.get("id"), name:fields.get("name"), url:fields.get("url"), plant_ids:[fields.get("plant_id")], approved:fields.has("approved")});
    await refresh(); notify("Specialist registered for its approved plant scope.");
  });
};
if ($("inject")) {
  $("inject").onclick = () =>
    action(async () => {
      clearTrajectory();
      await api(`/api/plants/${selectedId}/scenarios`, {
        scenario: $("scenario").value,
      });
      notify("Fault injected. Run an investigation to test recovery.");
    });
}
if ($("reset")) {
  $("reset").onclick = () =>
    action(async () => {
      clearTrajectory();
      await api(`/api/plants/${selectedId}/reset`, {});
      notify("Twin reset. Incident history retained.");
    });
}
if ($("investigate")) {
  $("investigate").onclick = () =>
    action(async () => {
      clearTrajectory();
      notify(
        "Investigating: reading telemetry, discovering controls and testing actions…",
      );
      let incident;
      try {
        incident = await terminal.run(selectedId, $("harness").value);
      } catch (error) {
        if (error.name !== "AbortError") throw error;
        notify("Investigation cancelled. Check incident history for its final state.");
        return;
      }
    // Update final telemetry before opening the historical response.
    await refresh();
    await inspect(incident);
    notify(
      `${incident.status.toUpperCase()}: ${incident.reason}`,
      incident.status === "failed",
    );
  });
}
$("refresh").onclick = () =>
  action(async () => {
    notify("Twin state refreshed.");
  });
$("play").onclick = () => {
  if (!trajectory.length) return;
  if (step >= trajectory.length - 1) seek(0);
  playing = !playing;
  playTime = performance.now();
  $("play").textContent = playing ? "Ⅱ Pause" : "▶ Replay";
};
$("scrub").oninput = () => {
  playing = false;
  seek(Number($("scrub").value));
};
function animate(time) {
  if (playing && trajectory.length) {
    const interval = 1000 / Number($("speed").value);
    if (time - playTime >= interval) {
      const jump = Math.floor((time - playTime) / interval);
      playTime = time;
      seek(step + jump);
      if (step === trajectory.length - 1) {
        playing = false;
        $("play").textContent = "↻ Replay";
      }
    }
  }
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);
for (const b of document.querySelectorAll("[data-camera]"))
  b.onclick = () => {
    scene?.setCamera(b.dataset.camera);
    document
      .querySelectorAll("[data-camera]")
      .forEach((x) => x.classList.toggle("active", x === b));
    $("view-label").textContent = b.textContent + " view";
  };
$("heatmap").onchange = () => scene?.setHeatmap($("heatmap").checked);
$("cutaway").onchange = () => scene?.setCutaway($("cutaway").checked);
$("motion").onclick = () => {
  if (!scene) return;
  scene.motion = !scene.motion;
  $("motion").textContent = scene.motion ? "Pause motion" : "Resume motion";
  $("motion").setAttribute("aria-pressed", String(!scene.motion));
};
$("active-twin").onchange = (e) => selectPlant(e.target.value);
$("temperature-unit").onclick = () => {
  temperatureUnit = temperatureUnit === "C" ? "F" : "C";
  $("temperature-unit").setAttribute(
    "aria-label",
    `Switch temperature unit to ${temperatureUnit === "C" ? "Fahrenheit" : "Celsius"}`,
  );
  renderTelemetry(
    trajectory.length && !viewingSnapshot ? trajectory[step] : undefined,
  );
  views?.setUnit(temperatureUnit);
};
$("live-snapshot").onclick = () => {
  playing = false;
  viewingSnapshot = true;
  $("play").textContent = "▶ Replay";
  scene?.setState(state());
  renderTelemetry();
};
async function init() {
  if (currentPage === "fleet") return fleetView({ api });
  if (currentPage === "assets") return addPlantPage({ api });
  if (currentPage === "impact") return impactPage({ api });
  if (currentPage === "faculties") return facultiesPage({ api });
  if (currentPage === "agents") return agentsPage({ api });
  const harnesses = await api("/api/harnesses");
  if ($("harness-register")) {
    $("harness-register").replaceChildren(
      ...harnesses.map((h) => {
        const row = make("div", undefined, "harness-row"),
          info = make("div");
        info.append(
          make(
            "strong",
            {
              reference: "Reference baseline",
              deepagents: "Deep Agents",
              adk: "Google ADK",
              antigravity: "Antigravity SDK",
            }[h.name],
          ),
          make(
            "p",
            h.live_model
              ? `${h.isolated ? "Isolated worker" : "Native adapter"} · Live model configuration required`
              : "Deterministic candidate search · No credentials required",
          ),
        );
        row.append(
          info,
          make(
            "span",
            h.configured && h.credentials ? "Configured" : "Setup required",
            `status ${h.configured && h.credentials ? "healthy" : ""}`,
          ),
        );
        return row;
      }),
    );
  }
  const filteredHarnesses = harnesses.filter((h) => h.name !== "adk");
  if ($("harness")) {
    $("harness").replaceChildren(
      ...filteredHarnesses.map((h) => {
        let label = h.name;
        if (h.name === "reference") label = "Reference · offline";
        else if (h.name === "antigravity") label = "Antigravity" + (h.configured && h.credentials ? "" : " · setup required");
        else if (h.name === "deepagents") label = "Deep Agents · not installed";
        const o = make("option", label);
        o.value = h.name;
        o.disabled = !(h.configured && h.credentials);
        return o;
      }),
    );
  }
  await refresh();
  if (currentPage === "studio") {
    views = plantViews({
      api,
      getSelected: () => selectedId,
      select: selectPlant,
      onUnit: (unit) => {
        temperatureUnit = unit;
        $("temperature-unit").setAttribute("aria-label", `Switch temperature unit to ${unit === "C" ? "Fahrenheit" : "Celsius"}`);
        renderTelemetry(trajectory.length && !viewingSnapshot ? trajectory[step] : undefined);
      },
      focusTwin: (id) => scene?.select(id),
      onData: (data) => applyOperations(data),
      terminal,
    });
  }
  try {
    if (currentPage !== "studio") return startPolling();
    const { TwinScene } = await import("./scene.js?v=fabrix-20261019-1");
    scene = new TwinScene($("viewport"), () => {});
    scene.setState(state());
    $("motion").textContent = scene.motion ? "Pause motion" : "Resume motion";
    $("motion").setAttribute("aria-pressed", String(!scene.motion));
  } catch (e) {
    $("scene-error").textContent =
      "3D is unavailable on this browser. Telemetry, faults, predictions and investigations still work.";
    for (const b of document.querySelectorAll("[data-camera], #motion"))
      b.disabled = true;
    console.warn("3D unavailable:", e.message);
  }
  startPolling();
}
function startPolling() {
  const poll = async () => {
    try {
      if (!busy && !document.hidden) await refresh();
    } catch(e) {
        notify(`State sync failed: ${e.message}`, true);
    } finally {
      setTimeout(poll, (views?.simActive() ?? false) ? 2000 : 5000);
    }
  };
  setTimeout(poll, 1000);
}
$("fit-view").onclick = () => scene?.fitSelection();
$("equipment-labels").onchange = () =>
  scene?.setLabels($("equipment-labels").checked);
window.addEventListener("pagehide", () => scene?.destroy());
init().catch((e) => notify(`Unable to load platform: ${e.message}`, true));
