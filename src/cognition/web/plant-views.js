// Studio views and the live-simulation panel.
// The sidebar owns the controls: plant, view (twin / process flow / HMI), simulation, response mode
// and fault injection. The main area only shows the selected view.
// Reads the existing /operations read model once a second. The only writes are the documented
// automation, scenario, reset and approval endpoints; the gateway stays the sole command writer.

import { buildContext, evaluate, plantAlarms } from "./plant-signals.js";
import { modelFor } from "./plant-models.js";
import { createProcessFlow } from "./process-flow.js";
import { createHmi } from "./hmi-screens.js";
import { twinNarrator } from "./twin-narrator.js";
import { themeSelect } from "./themed-select.js";

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const TABS = ["twin", "flow", "hmi"];
const POLL_MS = 1000;
const KEEP = 120;
const MODE_HINT = {
  observe: "Advances the plant and shows live data. No agent is called.",
  supervised: "The agent investigates a deviation, then waits for your approval before acting.",
  autopilot: "The agent investigates and applies gateway-validated actions on its own.",
};
const STEPS = [
  ["detect", "Detect"],
  ["investigate", "Investigate"],
  ["propose", "Propose"],
  ["apply", "Apply"],
  ["verify", "Verify"],
];
const STORAGE = { mode: "avenor.sim.mode", harness: "avenor.sim.harness", stopOn: "avenor.sim.stopOn", stopCount: "avenor.sim.stopCount" };
const DEFAULT_STOP_COUNT = 2;
const remember = (key, value) => {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable: choice is per-page */ }
};
const recall = (key, fallback) => {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
};

export function plantViews({ api, getSelected, select, onUnit, onData, focusTwin, terminal }) {
  const params = new URLSearchParams(location.search);
  if (params.get("view") === "cores") {
    // The cores moved to the Specialist Faculties page; keep old links working.
    const plant = params.get("plant");
    location.replace(`/faculties${plant ? `?plant=${encodeURIComponent(plant)}` : ""}`);
  }
  let tab = TABS.includes(params.get("view")) ? params.get("view") : "twin";
  let screen = params.get("eq") || "overview";
  let preference = "C";
  let mode = recall(STORAGE.mode, "autopilot");
  if (!MODE_HINT[mode]) mode = "autopilot";
  let plants = [];
  let automation = [];
  let last = null;
  let built = null;
  let flow = null;
  let hmi = null;
  let stopped = false;
  let acting = false;
  let watched = null;
  let restoredFor = null;
  const stores = new Map();

  const storeFor = (id) => {
    if (!stores.has(id)) stores.set(id, { revision: -1, seconds: -1, series: {}, clocks: [], active: new Map(), events: [] });
    return stores.get(id);
  };
  const trends = {
    values: (tagId) => storeFor(getSelected()).series[tagId] ?? [],
    clocks: () => storeFor(getSelected()).clocks,
  };
  const narrator = twinNarrator({ api, host: $("viewport") });
  const runFor = (id) => automation.find((item) => item.plant_id === id);

  // ---- URL and views ----
  function syncUrl() {
    const url = new URL(location.href);
    const id = getSelected();
    if (id) url.searchParams.set("plant", id);
    if (tab === "twin") url.searchParams.delete("view");
    else url.searchParams.set("view", tab);
    if (tab === "hmi" && screen !== "overview") url.searchParams.set("eq", screen);
    else url.searchParams.delete("eq");
    window.history.replaceState(null, "", url);
  }

  function setTab(next, equipment) {
    tab = next;
    if (equipment) screen = equipment;
    document.documentElement.dataset.studioTab = tab;
    for (const id of TABS) {
      const button = $(`view-tab-${id}`);
      button.setAttribute("aria-selected", String(id === tab));
      button.tabIndex = id === tab ? 0 : -1;
    }
    $("flow-panel").hidden = tab !== "flow";
    $("hmi-panel").hidden = tab !== "hmi";
    if (tab !== "flow") { flow?.destroy(); flow = null; }
    if (tab !== "hmi") { hmi?.destroy(); hmi = null; }
    syncUrl();
    render();
    if (tab === "twin") window.dispatchEvent(new Event("resize"));
  }

  for (const id of TABS) $(`view-tab-${id}`).addEventListener("click", () => setTab(id));
  $("view-tabs").addEventListener("keydown", (event) => {
    const forward = event.key === "ArrowRight";
    const back = event.key === "ArrowLeft";
    const edge = event.key === "Home" || event.key === "End";
    if (!forward && !back && !edge) return;
    event.preventDefault();
    const next = edge
      ? TABS[event.key === "Home" ? 0 : TABS.length - 1]
      : TABS[(TABS.indexOf(tab) + (forward ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next);
    $(`view-tab-${next}`).focus();
  });

  // ---- sidebar: response mode and harness ----
  const modeButtons = [...document.querySelectorAll("#sim-modes [data-mode]")];
  function renderMode(running) {
    for (const button of modeButtons) {
      button.setAttribute("aria-checked", String(button.dataset.mode === mode));
      button.tabIndex = button.dataset.mode === mode ? 0 : -1;
      button.disabled = running;
    }
    $("sim-mode-hint").textContent = MODE_HINT[mode];
    const live = mode !== "observe";
    $("sim-harness-row").hidden = !live;
    $("sim-stop-row").hidden = !live;
    $("sim-stop-toggle").disabled = running;
    $("sim-stop-count").disabled = running || !$("sim-stop-toggle").checked;
    const harness = $("harness");
    if (harness) {
      harness.disabled = running;
    }
  }
  // "Stop the run after N verified recoveries": remembered in the browser, applied when a run starts.
  const stopToggle = $("sim-stop-toggle");
  const stopCount = $("sim-stop-count");
  const stopLimit = () => Math.max(1, Math.min(20, Math.round(Number(stopCount.value)) || DEFAULT_STOP_COUNT));
  stopToggle.checked = recall(STORAGE.stopOn, "on") === "on";
  stopCount.value = String(Math.max(1, Math.min(20, Number(recall(STORAGE.stopCount, DEFAULT_STOP_COUNT)) || DEFAULT_STOP_COUNT)));
  const stopUnit = () => { $("sim-stop-unit").textContent = stopLimit() === 1 ? "recovery" : "recoveries"; };
  stopUnit();
  stopToggle.addEventListener("change", () => { remember(STORAGE.stopOn, stopToggle.checked ? "on" : "off"); renderMode(false); });
  stopCount.addEventListener("input", stopUnit);
  stopCount.addEventListener("change", () => { stopCount.value = String(stopLimit()); remember(STORAGE.stopCount, stopCount.value); stopUnit(); });
  for (const button of modeButtons) {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      mode = button.dataset.mode;
      remember(STORAGE.mode, mode);
      renderMode(false);
    });
  }
  $("sim-modes").addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    const keys = modeButtons.map((b) => b.dataset.mode);
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : keys.length - 1;
    mode = keys[(keys.indexOf(mode) + step) % keys.length];
    remember(STORAGE.mode, mode);
    renderMode(false);
    modeButtons.find((b) => b.dataset.mode === mode)?.focus();
  });
  function syncHarness() {
    const harness = $("harness");
    if (!harness) return;
    const saved = recall(STORAGE.harness, "reference");
    const usable = [...harness.options].find((o) => o.value === saved && !o.disabled);
    harness.value = usable ? saved : "reference";
  }
  $("harness")?.addEventListener("change", () => {
    remember(STORAGE.harness, $("harness").value);
    renderMode(false);
  });

  // ---- sidebar: simulation state and agent response ----
  const setMessage = (text, error = false) => {
    $("sim-message").textContent = text;
    $("sim-message").dataset.error = String(error);
  };
  const stepList = $("sim-steps");
  for (const [id, label] of STEPS) {
    const item = el("li", "sim-step");
    item.dataset.step = id;
    item.dataset.state = "pending";
    item.append(el("i", "sim-step-dot"), el("span", "", label));
    stepList.append(item);
  }

  // Maps the platform's automation phase onto the five-step response story.
  function stage(run, c, incident) {
    const failedStatus = incident && ["escalated", "failed", "interrupted"].includes(incident.status);
    const states = Object.fromEntries(STEPS.map(([id]) => [id, "pending"]));
    const out = c.state.quality !== "good" || Math.abs(c.state.temperature - c.state.target) > c.limits.band;
    if (!run) return { states, text: "" };
    const set = (upTo, active, failed) => {
      const ids = STEPS.map(([id]) => id);
      ids.slice(0, upTo).forEach((id) => (states[id] = "done"));
      if (active) states[ids[upTo]] = failed ? "failed" : "active";
    };
    switch (run.phase) {
      case "observing":
        if (out) set(0, true);
        break;
      case "planning": set(1, true); break;
      case "awaiting_approval": set(2, true); break;
      case "awaiting_parts": set(2, true); break;
      case "verifying": set(4, true); break;
      case "cooldown": set(5, false); break;
      case "attention":
        if (failedStatus || incident?.proposal?.escalation) set(2, true, true);
        else set(1, true, true);
        break;
      default: break;
    }
    return { states };
  }

  // The two studio dropdowns use the themed list; the native selects stay as the source of truth.
  themeSelect($("harness"));
  themeSelect($("fault-select"));

  // The disturbance you picked or injected is remembered per plant, so it is still selected after
  // visiting another page. Disturbances that are active right now carry an "Active" tag in the list.
  const faultKey = (id) => `avenor.fault.${id}`;
  const recalledFault = (id) => { try { return localStorage.getItem(faultKey(id)); } catch { return null; } };
  const rememberFault = (id, kind) => { try { localStorage.setItem(faultKey(id), kind); } catch { /* storage unavailable */ } };
  let activeFaults = [];
  let faultsPolledAt = 0;
  function markActiveFaults() {
    const select = $("fault-select");
    if (!select) return;
    const kinds = new Set(activeFaults.map((event) => event.kind));
    for (const option of select.options) {
      if (kinds.has(option.value)) { if (option.dataset.badge !== "Active") option.dataset.badge = "Active"; }
      else if (option.dataset.badge) delete option.dataset.badge;
    }
  }
  async function loadActiveFaults() {
    const id = getSelected();
    if (!id) return;
    faultsPolledAt = Date.now();
    try {
      const events = await api(`/api/plants/${encodeURIComponent(id)}/faults`);
      if (id !== getSelected()) return;
      activeFaults = events.filter((event) => event.state !== "cleared");
      markActiveFaults();
    } catch { /* the next poll retries */ }
  }

  let catalogueFor = null;
  let catalogueList = [];
  async function loadFaultCatalogue() {
    const id = getSelected();
    if (!id || catalogueFor === id) return;
    catalogueFor = id;
    try {
      catalogueList = await api(`/api/plants/${encodeURIComponent(id)}/fault-catalogue`);
    } catch {
      catalogueList = [];
      return;
    }
    const select = $("fault-select");
    if (!select) return;
    select.replaceChildren();
    const faults = catalogueList.filter((item) => item.domain === "fault");
    const business = catalogueList.filter((item) => item.domain === "business");
    const addGroup = (label, items) => {
      const g = document.createElement("optgroup");
      g.label = label;
      for (const item of items) {
        const o = document.createElement("option");
        o.value = item.id;
        o.textContent = `${item.name}${item.equipment !== "plant" ? ` (${item.equipment})` : ""}`;
        g.appendChild(o);
      }
      return g;
    };
    if (faults.length) select.appendChild(addGroup("Equipment & Process Faults", faults));
    if (business.length) select.appendChild(addGroup("Business & Supply Events", business));
    await loadActiveFaults();
    if (id !== getSelected()) return;
    // Restore the last choice for this plant; otherwise the newest disturbance that is active.
    const has = (kind) => kind && [...select.options].some((option) => option.value === kind);
    const newest = [...activeFaults].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0]?.kind;
    const pick = [recalledFault(id), newest].find(has);
    if (pick) select.value = pick;
    updateFaultDesc();
  }

  function updateFaultDesc() {
    const select = $("fault-select");
    const desc = $("fault-desc");
    if (!select || !desc) return;
    const found = catalogueList.find((item) => item.id === select.value);
    desc.textContent = found ? `${found.description}` : "";
  }
  $("fault-select")?.addEventListener("change", () => {
    updateFaultDesc();
    const select = $("fault-select");
    if (select?.value) rememberFault(getSelected(), select.value);
  });

  // "m:ss" for a number of seconds.
  const killClock = (seconds) => {
    const total = Math.max(0, Math.round(seconds));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  };
  // The countdown chip beside the status pill: armed while a run is going, red once it has tripped.
  function renderKill(kill, running) {
    const chip = $("sim-kill");
    if (!chip) return;
    const armed = Boolean(running && kill?.configured && kill.seconds_left !== null);
    chip.hidden = !(armed || kill?.tripped);
    if (chip.hidden) return;
    if (kill.tripped && !running) {
      chip.dataset.state = "tripped";
      chip.textContent = `Stopped at ${killClock(kill.after_seconds)}`;
    } else {
      chip.dataset.state = kill.seconds_left <= 60 ? "soon" : "armed";
      chip.textContent = `Kill switch in ${killClock(kill.seconds_left)}`;
    }
  }

  function renderSim(c) {
    const id = c.state.spec.id;
    if (catalogueFor === id && Date.now() - faultsPolledAt > 3000) loadActiveFaults();
    const run = runFor(id);
    const worldRunning = Boolean(c.time?.world_running);
    const running = Boolean(run?.enabled || worldRunning);
    const incident = run?.incident_id && c.incident?.id === run.incident_id ? c.incident : null;
    const panel = $("sim-panel");
    panel.dataset.running = String(running);
    const pill = $("sim-state");
    let level = "off";
    let text = "Stopped";
    let detail = "";
    const kill = c.time?.kill;
    if (!running && kill?.tripped) {
      level = "kill";
      text = "Kill switch tripped";
      detail = `The ${killClock(kill.after_seconds)} limit was reached, so every agent and the harness were stopped. Reset the plant or start a new run.`;
    } else if (run?.phase === "attention") {
      // The agent handed this run to the operator; the card below offers the next steps.
      level = "attention";
      text = "Needs attention";
      detail = "The agent handed this to you. Choose what happens next.";
    } else if (running) {
      const phase = run?.phase || (worldRunning ? "observing" : "off");
      level = phase === "planning" || phase === "verifying" || phase === "awaiting_parts" ? "work" : phase === "awaiting_approval" ? "wait" : "live";
      text = { observing: run?.config?.mode === "observe" ? "Observing" : "Watching", planning: "Investigating", awaiting_approval: "Awaiting approval", awaiting_parts: "Parts ordered", verifying: "Verifying", cooldown: "Recovered" }[phase] ?? (worldRunning ? "World ticking" : "Running");
      detail = run?.reason || "Simulation and world clock running at 1s per tick.";
      if (phase === "observing" && run?.config?.mode !== "observe") detail = `Watching for a deviation. ${run?.config?.mode === "autopilot" ? "The agent will act on its own." : "The agent will ask you before acting."}`;
      if (phase === "verifying") detail = `Command applied. ${run?.stable_samples ?? 0} of 10 fresh samples stable.`;
      if (phase === "planning") detail = `${run?.config?.harness ?? "Agent"} is reading telemetry and testing actions.`;
      if (run?.config?.stop_when_done) detail += ` The run stops after ${run.config.max_investigations} verified recoveries (${run.completed} so far).`;
    } else if (!running && run?.run_complete) {
      level = "done";
      text = "Run complete";
      detail = `${run.completed} of ${run.config.max_investigations} investigations were verified, so the simulation, agents and robots were stopped. Reset the plant or start a new run.`;
    }
    pill.dataset.level = level;
    pill.textContent = text;
    renderKill(kill, running);
    $("sim-clock").textContent = c.time.simulated_clock;
    narrator.update(id, running);
    $("sim-rev").textContent = `r${c.state.revision}`;
    $("sim-detail").textContent = detail;
    const toggle = $("sim-toggle");
    toggle.dataset.state = running ? "on" : "off";
    toggle.setAttribute("aria-label", running ? "Stop main plant simulation" : "Start main plant simulation");
    toggle.title = running ? "Stop main plant simulation" : "Start main plant simulation";
    toggle.querySelector(".sim-toggle-label").textContent = running ? "Stop main plant simulation" : "Start main plant simulation";
    toggle.disabled = acting;
    if (running && run) {
      mode = run.config.mode;
      const harness = $("harness");
      if (harness && [...harness.options].some((o) => o.value === run.config.harness)) harness.value = run.config.harness;
    }
    renderMode(running);
    // Response story: visible while running, or for a run that ended in an outcome that needs a look.
    const show = running || run?.phase === "attention";
    stepList.hidden = !show;
    if (show) {
      const { states } = stage(run, c, incident);
      for (const item of stepList.children) item.dataset.state = states[item.dataset.step];
    }
    // Approval
    const waiting = running && run?.phase === "awaiting_approval" && incident?.proposal?.action;
    $("sim-approval").hidden = !waiting;
    if (waiting) {
      const act = incident.proposal.action;
      const actText =
        act.control === "thermal_duty" || typeof act.value === "number"
          ? `Set thermal duty to ${act.value}%?`
          : act.control === "maintenance"
            ? `Execute repair: ${act.remedy} on ${act.equipment}?`
            : `Apply monitor config: ${act.setting} on ${act.target || act.core}?`;
      $("sim-proposal").textContent = `${actText} ${incident.proposal.summary}`;
    }
    $("sim-approve").disabled = $("sim-reject").disabled = acting;
    // Escalation card: why the agent stopped, and how the operator can move on.
    const needsYou = run?.phase === "attention" && !run.enabled;
    $("sim-attention").hidden = !needsYou;
    if (needsYou) {
      const reason = run.reason || "";
      $("sim-attention-reason").textContent = reason.length > 420 ? `${reason.slice(0, 417)}…` : reason;
      $("sim-attention-reason").title = reason;
    }
    for (const buttonId of ["sim-fixed", "sim-investigate", "sim-dismiss"]) $(buttonId).disabled = acting;
    if ($("fault-inject")) $("fault-inject").disabled = acting;
    $("sim-reset").disabled = acting;
    // Stream the agent's work into the investigation console as soon as the incident exists.
    if ((running || run?.phase === "attention") && incident && watched !== incident.id) {
      watched = incident.id;
      terminal?.watch(incident.id).catch((error) => { if (error.name !== "AbortError") watched = null; });
    } else if (
      running && !watched && c.incident && restoredFor !== c.incident.id && run?.started_at
      && Date.parse(c.incident.created_at) >= Date.parse(run.started_at) - 1000
    ) {
      // Back on the page between investigations: show the latest run of this simulation instead of an empty console.
      const finished = c.incident;
      restoredFor = finished.id;
      api(`/api/incidents/${encodeURIComponent(finished.id)}/events`)
        .then((events) => { if (!watched && getSelected() === finished.plant_id) terminal?.show(finished, events); })
        .catch(() => { restoredFor = null; });
    }
  }

  async function perform(label, work) {
    if (acting) return;
    acting = true;
    setMessage(`${label}…`);
    if (last) renderSim(last.c);
    try {
      await work();
      setMessage("");
    } catch (error) {
      setMessage(error.message || `${label} failed`, true);
    } finally {
      acting = false;
      await poll(true);
    }
  }
  const automationPath = () => `/api/plants/${encodeURIComponent(getSelected())}/automation`;
  async function stopRun() {
    await api(`/api/plants/${encodeURIComponent(getSelected())}/world/stop`, {}).catch(() => {});
    const response = await fetch(automationPath(), { method: "DELETE" }).catch(() => null);
    if (response && !response.ok && response.status !== 404) throw new Error("Could not stop the simulation. Try again.");
  }
  async function startRun() {
    watched = null;
    await api(`/api/plants/${encodeURIComponent(getSelected())}/world/start`, { interval_seconds: 1 });
    return api(automationPath(), {
      mode,
      harness: mode === "observe" ? "reference" : $("harness")?.value || "reference",
      interval_seconds: 1,
      max_investigations: mode !== "observe" && stopToggle.checked ? stopLimit() : 20,
      stop_when_done: mode !== "observe" && stopToggle.checked,
      cooldown_seconds: 5,
    });
  }
  $("sim-toggle").addEventListener("click", () => {
    const id = getSelected();
    const run = runFor(id);
    const worldRunning = Boolean(last?.c?.time?.world_running);
    if (run?.enabled || worldRunning) perform("Stopping", stopRun);
    else perform("Starting", startRun);
  });
  $("fault-inject")?.addEventListener("click", () => {
    const select = $("fault-select");
    if (!select?.value) return;
    rememberFault(getSelected(), select.value);
    perform("Injecting fault", async () => {
      await api(`/api/plants/${encodeURIComponent(getSelected())}/faults`, {
        kind: select.value,
        severity: 0.8,
      });
      await loadActiveFaults();
    });
  });
  $("sim-reset").addEventListener("click", () =>
    perform("Resetting plant", async () => {
      const was = runFor(getSelected())?.enabled;
      if (was) await stopRun();
      await api(`/api/plants/${encodeURIComponent(getSelected())}/reset`, {});
      watched = null;
      terminal?.detach(true);
      if (was) setMessage("Simulation stopped for the reset. Start it again to resume.");
    }),
  );
  for (const [buttonId, action, label] of [
    ["sim-fixed", "fixed", "Marking fixed"],
    ["sim-investigate", "investigate", "Starting a fresh investigation"],
    ["sim-dismiss", "dismiss", "Dismissing"],
  ]) {
    $(buttonId).addEventListener("click", () =>
      perform(label, async () => {
        watched = null;
        await api(`/api/plants/${encodeURIComponent(getSelected())}/attention`, { action });
      }),
    );
  }
  for (const [id, accepted] of [["sim-approve", true], ["sim-reject", false]]) {
    $(id).addEventListener("click", () =>
      perform(accepted ? "Approving" : "Rejecting", () => {
        const run = runFor(getSelected());
        return api(`/api/incidents/${encodeURIComponent(run.incident_id)}/approval?accepted=${accepted}`, {});
      }),
    );
  }
  $("sim-unit").addEventListener("click", () => {
    const next = preference === "C" ? "F" : "C";
    setUnit(next);
    onUnit?.(next);
  });
  function setUnit(next) {
    preference = next;
    $("sim-unit").textContent = `°${next}`;
    $("sim-unit").setAttribute("aria-label", `Temperature unit ${next === "C" ? "Celsius" : "Fahrenheit"}. Switch to ${next === "C" ? "Fahrenheit" : "Celsius"}.`);
    render();
  }

  // ---- data ingest ----
  function record(c, T) {
    const store = storeFor(c.state.spec.id);
    const seconds = c.time.simulated_seconds;
    if (seconds < store.seconds) {
      store.series = {};
      store.clocks = [];
      store.revision = -1;
    }
    if (c.state.revision !== store.revision) {
      store.revision = c.state.revision;
      store.seconds = seconds;
      for (const [id, tag] of T) {
        const values = store.series[id] ?? (store.series[id] = []);
        values.push(tag.value);
        if (values.length > KEEP) values.shift();
      }
      store.clocks.push(c.time.simulated_clock);
      if (store.clocks.length > KEEP) store.clocks.shift();
    }
    const current = new Map(plantAlarms(c).map((alarm) => [alarm.id, alarm]));
    for (const [id, alarm] of current) {
      const known = store.active.get(id);
      if (!known) {
        store.active.set(id, { ...alarm, since: c.time.simulated_clock });
        store.events.unshift({ kind: "raised", level: alarm.level, text: alarm.text, clock: c.time.simulated_clock });
      } else Object.assign(known, alarm);
    }
    for (const [id, known] of store.active) {
      if (!current.has(id)) {
        store.active.delete(id);
        store.events.unshift({ kind: "cleared", level: "ok", text: known.text, clock: c.time.simulated_clock });
      }
    }
    store.events.length = Math.min(store.events.length, 40);
    return store;
  }

  let shownPlant = null;
  function ingest(op) {
    const c = buildContext(op);
    const model = modelFor(c.industry);
    if (shownPlant !== c.state.spec.id) {
      if (shownPlant !== null) { watched = null; restoredFor = null; terminal?.detach(true); }
      shownPlant = c.state.spec.id;
      loadFaultCatalogue();
      syncUrl();
    }
    if (!built || built.industry !== c.industry) {
      flow?.destroy(); flow = null;
      hmi?.destroy(); hmi = null;
      built = { industry: c.industry, model };
    }
    const T = evaluate(model, c, preference);
    const store = record(c, T);
    last = { c, model, activeAlarms: [...store.active.values()], events: store.events };
    renderSim(c);
    render();
    onData?.(op);
  }

  function render() {
    if (!last) return;
    const { c, model } = last;
    // Evaluated on every render so the unit toggle applies immediately.
    const T = evaluate(model, c, preference);
    const payload = { c, T, activeAlarms: last.activeAlarms, events: last.events, preference };
    if (tab === "flow") {
      if (!flow) {
        flow = createProcessFlow($("flow-host"), model, { onOpen: (id) => setTab("hmi", id) });
        $("flow-title").textContent = `${model.title}: process flow`;
      }
      flow.update(c, T);
    } else if (tab === "hmi") {
      if (!hmi) {
        hmi = createHmi($("hmi-host"), model, {
          history: trends,
          onNavigate: (id) => { screen = id; syncUrl(); hmi.show(id); },
          onFlow: () => setTab("flow"),
          onTwin: (id) => { setTab("twin"); focusTwin?.(id); },
        });
        hmi.show(screen);
      }
      hmi.update(payload);
    }
  }

  // ---- polling ----
  let timer = 0;
  let inflight = false;
  async function poll(immediate = false) {
    if (stopped) return;
    clearTimeout(timer);
    if (inflight) return;
    if (document.hidden && !immediate) { timer = setTimeout(poll, POLL_MS); return; }
    inflight = true;
    const id = getSelected();
    try {
      const [list, runs, op] = await Promise.all([
        api("/api/plants"),
        api("/api/automation"),
        id ? api(`/api/plants/${encodeURIComponent(id)}/operations`) : Promise.resolve(null),
      ]);
      plants = list;
      automation = runs;
      $("plant-hub").dataset.stale = "false";
      $("sim-panel").dataset.stale = "false";
      if (op && id === getSelected()) ingest(op);
    } catch {
      $("plant-hub").dataset.stale = "true";
      $("sim-panel").dataset.stale = "true";
      $("sim-state").dataset.level = "attention";
      $("sim-state").textContent = "Connection lost";
      $("sim-detail").textContent = "Showing the last values received. Retrying every second.";
    } finally {
      inflight = false;
      timer = setTimeout(poll, POLL_MS);
    }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
  window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); });

  syncHarness();
  loadFaultCatalogue();
  renderMode(false);
  setTab(tab);
  setUnit(preference);
  poll(true);

  return {
    setUnit,
    setTab,
    simActive: () => Boolean(runFor(getSelected())?.enabled),
  };
}
