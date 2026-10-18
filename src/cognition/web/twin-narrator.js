// Plain-language live activity card over the 3D view. Reads audit events; never writes.
const POLL_MS = 2000;
const MAX_ITEMS = 80;
const WORKING_MS = 8000;

const words = (text) => String(text ?? "").replaceAll("_", " ");
const cap = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const clip = (text, n = 150) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text);
const firstSentence = (text) => clip(String(text ?? "").split(/(?<=[.!?])\s/)[0], 170);
const core = (name) => `${cap(words(name))} core`;

const READ_TOOLS = /^(discover|read_|list_skills|forecast_)/;

// Returns { tone, text, key? } or null for events that are plumbing. A repeated `key`
// replaces the previous line instead of stacking, so noisy steps stay one line.
export function narrate(e) {
  const b = e.body ?? {};
  switch (e.kind) {
    case "world_started": return { tone: "info", text: "Simulation started" };
    case "automation_enabled": return { tone: "info", text: `Agent response is on (${b.mode})` };
    case "world_stopped": return { tone: "info", text: "Simulation stopped" };
    case "kill_switch_tripped": return { tone: "bad", text: `Kill switch tripped after ${Number(b.after_seconds)} s: agents and harness stopped` };
    case "operator_marked_fixed": return { tone: "ok", text: b.cleared ? `Operator marked it fixed: ${b.cleared} fault${b.cleared === 1 ? "" : "s"} cleared` : "Operator marked the incident fixed" };
    case "attention_resumed": return { tone: "info", text: "Operator asked for a fresh investigation" };
    case "attention_dismissed": return { tone: "info", text: "Operator dismissed the alert" };
    case "run_complete": return { tone: "ok", text: `Run complete: ${b.verified} of ${b.limit} investigations verified, agents stopped` };
    case "plant_reset": return { tone: "info", text: "Plant reset to baseline" };
    case "fault_injected": return { tone: "warn", text: `Fault injected: ${words(b.kind)} (${Math.round((b.severity ?? 0) * 100)}% severity)` };
    case "fault_cleared": return { tone: "ok", text: `Fault cleared: ${words(b.kind)}` };
    case "core_alert":
      if (b.level === "info") return null;
      return { tone: "warn", text: `${core(b.core)} noticed: ${b.title}`, key: `alert:${b.alert}` };
    case "core_query": return { tone: "info", text: `${core(b.core)} is looking into: ${clip(b.question ?? "", 110)}` };
    case "mission_completed": return { tone: "info", text: `A robot finished a ${words(b.kind)} of the ${words(b.target)}` };
    case "started": return { tone: "work", text: `Agent started investigating (plant state r${b.revision})`, start: true };
    case "tool_called": {
      const name = b.name ?? "";
      if (name.startsWith("simulate")) return { tone: "work", text: "Testing a thermal duty change on a copy of the plant", key: "simulate" };
      if (name === "ask_core") return { tone: "work", text: "Asking a specialist core for evidence", key: "ask" };
      if (name === "request_optimization") return { tone: "work", text: "Asking the optimization core for a plan", key: "optimize" };
      if (READ_TOOLS.test(name)) return { tone: "work", text: "Reading plant data and procedures", key: "read" };
      return null;
    }
    case "tool_result":
      if (!String(b.name).startsWith("simulate")) return null;
      return {
        tone: b.safe && b.recovered ? "ok" : "warn",
        text: `Test of ${b.value}% duty: ${b.safe ? "safe" : "outside limits"}, ${b.recovered ? "returns to setpoint" : "does not recover"}`,
        key: "simulate",
      };
    case "proposed": return { tone: "info", text: `Proposal: ${firstSentence(b.summary)}` };
    case "approval_requested": return { tone: "warn", text: "Waiting for your approval" };
    case "order_created": return { tone: "work", text: `Order sent to ${core(b.core)} to adjust ${words(b.control)}` };
    case "core_tool_called":
      if (/execute_order$/.test(b.tool ?? "")) return { tone: "work", text: `${core(b.core)} is carrying out the order`, key: "execute" };
      if (b.tool === "robot_run_mission") return { tone: "work", text: "Dispatching a robot", key: "mission" };
      return null;
    case "action_applied":
      return b.control === "thermal_duty"
        ? { tone: "ok", text: `Duty changed ${Number(b.previous_value).toFixed(0)}% → ${Number(b.commanded_value).toFixed(0)}%` }
        : { tone: "ok", text: `Applied ${words(b.control)}` };
    case "maintenance_applied": return { tone: "ok", text: "Maintenance step applied" };
    case "order_refused":
    case "attention_required": return { tone: "warn", text: `Not applied: ${b.reason}` };
    case "measurement":
      return { tone: "work", text: `Checking recovery: ${Number(b.temperature).toFixed(1)} °C, ${b.stable_samples}/10 steady samples`, key: "verify" };
    case "verified": return { tone: "ok", text: "Recovery verified" };
    case "completed": {
      const tone = b.status === "resolved" ? "ok" : b.status === "failed" ? "bad" : "warn";
      const text = { resolved: "Resolved", escalated: "Escalated to the operator", failed: "Investigation failed", interrupted: "Investigation stopped" }[b.status] ?? words(b.status);
      return { tone, text, done: true };
    }
    case "cancelled": return { tone: "warn", text: "Investigation cancelled", done: true };
    default: return null;
  }
}

export function twinNarrator({ api, host }) {
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const panel = el("aside", "twin-narrator");
  panel.hidden = true;
  panel.setAttribute("aria-label", "What the agents are doing");
  const head = el("div", "tn-head");
  const title = el("strong", "tn-title", "Live activity");
  const pill = el("span", "tn-pill", "Idle");
  pill.setAttribute("role", "status");
  const toggle = el("button", "tn-toggle", "›");
  toggle.type = "button";
  head.append(title, pill, toggle);
  const list = el("ol", "tn-list");
  list.setAttribute("aria-live", "polite");
  panel.append(head, list);
  host.append(panel);

  let plant = null, cursor = null, running = false, timer = null, minimized = false;
  let lastEvent = 0, items = [];

  let drawn = null;
  function render() {
    // Rebuild the list only when its content changed, so rows never flicker between polls.
    const signature = JSON.stringify(items);
    if (signature !== drawn) {
      drawn = signature;
      // Follow new entries only if the reader is already at the bottom; otherwise keep their place.
      const atEnd = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
      const keep = list.scrollTop;
      list.replaceChildren(...items.map((item) => {
      const li = el("li", "tn-item");
      li.dataset.tone = item.tone;
      li.append(el("time", "", item.time), el("span", "", item.text));
      return li;
      }));
      list.scrollTop = atEnd ? list.scrollHeight : keep;
    }
    const working = Date.now() - lastEvent < WORKING_MS;
    pill.textContent = working ? "Working" : "Idle";
    pill.dataset.state = working ? "on" : "off";
    const shown = running && items.length > 0;
    panel.hidden = !shown;
    panel.dataset.min = String(minimized);
    toggle.textContent = minimized ? "‹" : "›";
    toggle.setAttribute("aria-label", minimized ? "Expand live activity" : "Minimise live activity");
    toggle.setAttribute("aria-expanded", String(!minimized));
    if (shown) host.dataset.narrator = minimized ? "min" : "open";
    else delete host.dataset.narrator;
  }

  function add(e) {
    const line = narrate(e);
    if (!line) return;
    const time = new Date(e.time).toLocaleTimeString([], { hour12: false });
    const item = { ...line, time };
    const at = line.key ? items.findIndex((i) => i.key === line.key) : -1;
    if (at >= 0 && at === items.length - 1) items[at] = item;
    else items.push(item);
    items = items.slice(-MAX_ITEMS);
    lastEvent = Date.now();
  }

  async function poll() {
    timer = null;
    const id = plant;
    if (!id || !running) return;
    try {
      const data = await api(`/api/plants/${encodeURIComponent(id)}/narration?after=${cursor ?? -1}`);
      if (id !== plant) return;
      data.events.forEach(add); // the first call replays everything since the simulation started
      cursor = data.last_seq;
      render();
    } catch { /* the next poll retries; this card is advisory */ }
    if (running && id === plant && !timer) timer = setTimeout(poll, POLL_MS);
  }

  toggle.addEventListener("click", () => { minimized = !minimized; render(); });

  return {
    // Called on every sample render with the selected plant and whether a simulation runs.
    update(id, isRunning) {
      if (id !== plant) {
        plant = id; cursor = null; items = []; lastEvent = 0;
        clearTimeout(timer); timer = null;
      }
      if (isRunning !== running) {
        running = isRunning;
        if (!running) { items = []; cursor = null; clearTimeout(timer); timer = null; }
      }
      if (running && !timer) timer = setTimeout(poll, 0);
      render();
    },
  };
}
