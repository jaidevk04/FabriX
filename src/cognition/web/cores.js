// Specialist Faculties page: the four cores. One view shows the overview (core tiles, activity, orders and
// runs); each core has its own view with its report and workspace.
// Reads one aggregate endpoint once a second. Writes go only through documented endpoints:
// core Stop and follow-up approval. The world clock and fault injection live on the studio page. Robots and plant
// commands still pass through FleetGateway and the Gateway; nothing here can bypass them.

import {
  ALERT_LEVEL, STATUS_LEVEL, ago, badge, chip, clock, el, glyph, http, icon, lamp, layoutZones, meter, number,
  svg, words,
} from "./cores-parts.js";
import { facultyTile, statStrip } from "./cores-overview.js";
import { createLearningView } from "./learning-view.js";
import { createVisionView } from "./vision-view.js";
import { createRobotView } from "./robot-view.js";
import { createOptimizationView } from "./optimization-view.js";

const POLL_MS = 1000;
const GOALS = [
  ["recovery", "Recovery"], ["energy", "Energy"], ["co2e", "CO2e"],
  ["scrap", "Scrap"], ["due_date", "Due dates"], ["balanced", "Balanced"],
];
const CORE_TITLE = { learning: "Learning", vision: "Vision", robot: "Robot", optimization: "Optimization" };
const STATUS_TEXT = { ok: "Normal", warn: "Watch", crit: "Alert" };
const CORE_ROLE = {
  learning: "Sensor channels", vision: "Cameras", robot: "Fleet and zones", optimization: "Twin search",
};
const FILTERS = [["all", "All"], ["alert", "Alerts"], ["bus", "Bus"], ["robot", "Robots"], ["order", "Orders"], ["fault", "Faults"]];
const CATEGORY = (kind) => {
  if (kind.startsWith("core_alert")) return "alert";
  if (/^core_(request|answer|refused|query)/.test(kind)) return "bus";
  if (/^(mission_|fleet_)/.test(kind)) return "robot";
  if (/^(fault_|business_|world_|plant_reset)/.test(kind)) return "fault";
  return "order";
};

function describe(e) {
  const b = e.body ?? {};
  const map = {
    core_alert: () => `${CORE_TITLE[b.core] ?? b.core} core raised ${b.level}: ${b.title}`,
    core_alert_cleared: () => `${CORE_TITLE[b.core] ?? b.core} core cleared ${b.alert}`,
    core_request: () => `${b.from} asked ${b.to} for ${words(b.kind)}`,
    core_answer: () => `${b.from} answered a bus request`,
    core_refused: () => `Bus request refused: ${b.reason}`,
    core_query: () => `Asked the ${b.core} core to analyse`,
    mission_completed: () => `${b.robot?.split("-").pop() ?? "Robot"} ${b.kind} on ${b.target} (${b.tier})`,
    mission_refused: () => `Mission refused: ${b.reason}`,
    fleet_recalled: () => "Robots recalled to the dock",
    order_created: () => `Order for the ${b.core} core (${words(b.control)})`,
    order_receipt: () => "Order completed with a committed receipt",
    order_refused: () => `Order refused: ${b.reason}`,
    order_failed: () => `Order failed (${b.type})`,
    order_interrupted: () => "Order interrupted",
    followup_executed: () => "Follow-up correction applied",
    followup_pending: () => "Follow-up correction waiting for approval",
    followup_rejected: () => `Follow-up rejected: ${b.reason}`,
    followup_declined: () => "Follow-up declined",
    core_run_started: () => `${CORE_TITLE[b.core]} agent ${b.kind} run started`,
    core_run_completed: () => `${CORE_TITLE[b.core]} agent run finished`,
    core_run_interrupted: () => `${CORE_TITLE[b.core]} agent run stopped`,
    core_run_failed: () => `${CORE_TITLE[b.core]} agent run failed (${b.type})`,
    core_run_timeout: () => `${CORE_TITLE[b.core]} agent run hit its time ceiling`,
    core_stop: () => `Stop pressed for the ${b.core} core`,
    core_stop_all: () => "Stop pressed for all core runs",
    core_degraded: () => `${CORE_TITLE[b.core]} core degraded: ${b.reason}`,
    core_config_changed: () => `${b.core} monitor: ${words(b.setting)} ${b.target ?? ""}`,
    work_order_created: () => "Work order created",
    work_order_started: () => "Work order started",
    work_order_completed: () => "Work order completed",
    work_order_released: () => "Work order put back to open",
    work_order_cancelled: () => "Work order cancelled",
    impact_recorded: () => `Impact recorded (${b.outcome})`,
    fault_injected: () => `Fault injected: ${words(b.kind)} (severity ${b.severity})`,
    fault_ramping: () => `Fault ramping in: ${words(b.kind)}`,
    fault_active: () => `Fault at full strength: ${words(b.kind)}`,
    fault_cleared: () => `Fault cleared by ${b.cleared_by}: ${words(b.kind)}`,
    business_injected: () => `Business event: ${words(b.kind)}`,
    business_cleared: () => `Business event ended: ${words(b.kind)}`,
    world_started: () => "World clock started",
    world_stopped: () => "World clock stopped",
    plant_reset: () => "Plant reset",
  };
  return (map[e.kind] ?? (() => words(e.kind)))();
}

function eventLevel(e) {
  if (e.kind === "core_alert") return ALERT_LEVEL[e.body.level] ?? "info";
  if (/refused|failed|timeout|rejected/.test(e.kind)) return "crit";
  if (/interrupted|stop|degraded|pending/.test(e.kind)) return "warn";
  if (/receipt|completed|executed|cleared|recorded/.test(e.kind)) return "ok";
  return "info";
}

export const CORE_VIEWS = ["overview", "learning", "vision", "robot", "optimization"];

export function createCores(host, { getPlant, view: initialView = "overview", onOpen = null }) {
  let view = CORE_VIEWS.includes(initialView) ? initialView : "overview";
  let plantId = null;
  let after = 0;
  let timer = null;
  let destroyed = false;
  let busy = false;
  let panel = null;
  let events = [];
  let filter = "all";
  let goal = "balanced";
  let optimizationAt = 0;
  let frameAt = 0;
  const generation = { value: 0 };

  // ---------- skeleton ----------
  const root = el("div", "cr");
  const message = el("p", "cr-message");
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");

  const banner = el("p", "cr-banner", "Connection lost. Showing the last values and retrying.");
  banner.hidden = true;
  const coresRow = el("section", "cr-cores");
  coresRow.setAttribute("aria-label", "Cores");

  const card = (id, title, subtitle, tag) => {
    const section = el("section", `cr-card cr-card--${id}`);
    const head = el("header", "cr-card-head");
    const text = el("div");
    text.append(el("h3", "", title), el("p", "cr-sub", subtitle));
    head.append(text);
    if (tag) head.append(tag);
    const body = el("div", "cr-body");
    section.append(head, body);
    return { section, body, head };
  };
  const activity = card("activity", "Activity", "Core bus events, orders and alerts as they happen");
  const ops = card("ops", "Orders, work and runs", "What the cores have been asked to do");
  // Created before the layout runs: the Learning view is one of the pieces the grid can show.
  const learning = createLearningView({ base: () => `/api/plants/${encodeURIComponent(plantId)}` });
  const learningPiece = { section: learning.root };
  const vision = createVisionView({ base: () => `/api/plants/${encodeURIComponent(plantId)}` });
  const visionPiece = { section: vision.root };
  const robot = createRobotView();
  const robotPiece = { section: robot.root };
  const optimizationView = createOptimizationView({ base: () => `/api/plants/${encodeURIComponent(plantId)}` });
  const optimizationPiece = { section: optimizationView.root };
  const statsHost = el("section", "ov-stats-host");
  statsHost.setAttribute("aria-label", "Summary");
  const grid = el("div", "cr-grid");
  const pieces = {
    overview: [activity, ops], learning: [learningPiece], vision: [visionPiece], robot: [robotPiece], optimization: [optimizationPiece],
  };
  function layout() {
    grid.replaceChildren(...pieces[view].map((piece) => piece.section));
    grid.dataset.count = String(pieces[view].length);
    coresRow.dataset.single = String(view !== "overview");
    root.dataset.view = view;
    root.replaceChildren(...(view === "overview" ? [banner, message, statsHost, coresRow, grid] : [banner, message, coresRow, grid]));
  }
  layout();
  host.replaceChildren(root);

  const gated = (node, signature, build) => {
    if (node.dataset.sig === signature) return;
    node.dataset.sig = signature;
    node.replaceChildren(...build());
  };
  const say = (text, error = false) => {
    message.textContent = text;
    message.dataset.error = String(error);
  };
  const base = () => `/api/plants/${encodeURIComponent(plantId)}`;
  const act = async (label, work) => {
    try {
      await work();
      say("");
    } catch (error) {
      say(`${label}: ${error.message}`, true);
    }
    await poll(true);
  };

  // ---------- headline stats ----------
  function renderStats(data) {
    const alerts = data.cores.reduce((sum, c) => sum + c.report.alerts.length, 0);
    const live = data.runs.filter((r) => r.status === "running").length;
    const openOrders = data.orders.filter((o) => ["running", "pending"].includes(o.status) || o.pending_followup).length;
    const openWork = data.work_orders.filter((w) => w.status !== "completed").length;
    const worst = data.cores.some((c) => c.report.alerts.some((a) => a.level === "escalate")) ? "crit" : alerts ? "warn" : "ok";
    const stats = [
      { id: "alerts", label: alerts === 1 ? "Active alert" : "Active alerts", value: alerts, level: worst },
      { id: "runs", label: live === 1 ? "Agent run live" : "Agent runs live", value: live, level: live ? "info" : "off", live: live > 0 },
      { id: "orders", label: "Open orders", value: openOrders, level: openOrders ? "info" : "off", hint: `${data.orders.length} recent` },
      { id: "work", label: "Open work orders", value: openWork, level: openWork ? "warn" : "off" },
    ];
    gated(statsHost, JSON.stringify(stats), () => [statStrip(stats)]);
  }

  function alertList(report) {
    const list = el("ul", "cr-list cr-alerts");
    if (!report.alerts.length) {
      list.append(el("li", "cr-empty", "No alerts. The monitor sees nothing unusual."));
      return list;
    }
    for (const a of report.alerts) {
      const level = ALERT_LEVEL[a.level] ?? "info";
      const item = el("li", "cr-alert");
      item.dataset.level = level;
      const head = el("div", "cr-alert-head");
      head.append(glyph("alert", "cr-glyph cr-alert-glyph"), el("strong", "", a.title), chip(a.level, level), el("span", "cr-num cr-sub", `${Math.round(a.confidence * 100)}%`));
      item.append(head, el("p", "cr-sub", a.summary));
      list.append(item);
    }
    return list;
  }

  const overviewTiles = new Map();
  function renderCores(data) {
    const runs = data.runs.filter((r) => r.status === "running");
    const shown = view === "overview" ? data.cores : data.cores.filter((c) => c.name === view);
    if (view === "overview") {
      // Overview tiles are patched in place so their animations never restart on a refresh.
      const key = `overview:${shown.map((s) => s.name).join(",")}`;
      if (coresRow.dataset.sig !== key) {
        coresRow.dataset.sig = key;
        overviewTiles.clear();
        coresRow.replaceChildren(...shown.map(({ name, report }) => {
          const tile = facultyTile({
            name, title: CORE_TITLE[name], role: CORE_ROLE[name], level: STATUS_LEVEL[report.status] ?? "info", report,
            run: runs.find((r) => r.core === name),
            onOpen: onOpen ? () => onOpen(name) : null,
            onStop: () => act("Stop", () => http("POST", `${base()}/cores/${name}/stop`)),
          });
          overviewTiles.set(name, tile);
          return tile;
        }));
      } else {
        for (const { name, report } of shown) overviewTiles.get(name)?.update({ level: STATUS_LEVEL[report.status] ?? "info", report, run: runs.find((r) => r.core === name) });
      }
      return;
    }
    // Core tabs: rebuild only when the structure changes (status, alert set, run). Text is patched below.
    gated(coresRow, JSON.stringify([view, shown.map((c) => [c.report.status, c.report.source, c.report.degraded, c.report.alerts.map((a) => [a.id, a.level])]), runs.map((r) => r.id)]), () =>
      shown.map(({ name, report }) => {
        const level = STATUS_LEVEL[report.status] ?? "info";
        // Two fixed panes: status on the left, alerts on the right (scrolls), so the panel never changes height.
        const article = el("article", "cr-core cr-core--split");
        article.dataset.level = level;
        const main = el("div", "cr-core-main");
        const head = el("header", "cr-core-head");
        head.append(icon(name));
        const title = el("div");
        title.append(el("h3", "", `${CORE_TITLE[name]} core`), el("p", "cr-sub", CORE_ROLE[name]));
        head.append(title, chip(STATUS_TEXT[level] ?? "Normal", level, `${CORE_TITLE[name]} core ${report.status}`));
        const summary = el("p", "cr-core-summary", report.summary);
        const chips = el("div", "cr-chips");
        chips.append(badge("simulated model", report.model));
        if (report.degraded) chips.append(chip("degraded", "warn", "The agent was unavailable; the reference analyser answered"));
        main.append(head, summary, chips);
        const run = runs.find((r) => r.core === name);
        const fact = (iconName, label, value) => {
          const item = el("div", "cr-fact");
          const text = el("div", "cr-fact-text");
          text.append(el("span", "cr-fact-label", label), el("strong", "cr-fact-value", value));
          item.append(glyph(iconName, "cr-glyph cr-fact-icon"), text);
          return item;
        };
        const facts = el("div", "cr-facts-row");
        facts.append(
          fact("bell", "Active alerts", String(report.alerts.length)),
          fact("chip", "Report source", report.source === "monitor" ? "Monitor" : words(report.source)),
        );
        const agent = fact("bolt", "Agent", run ? `${words(run.kind)} running` : "Idle");
        if (run) {
          const stop = el("button", "cr-btn cr-btn--small cr-btn--danger", "Stop");
          stop.type = "button";
          stop.setAttribute("aria-label", `Stop the ${name} core run`);
          stop.addEventListener("click", () => act("Stop", () => http("POST", `${base()}/cores/${name}/stop`)));
          agent.append(stop);
        }
        facts.append(agent);
        main.append(facts);
        const side = el("aside", "cr-core-alerts");
        side.setAttribute("aria-label", `${CORE_TITLE[name]} alerts`);
        const sideHead = el("div", "cr-core-alerts-head");
        sideHead.append(el("h4", "cr-mini", "Alerts"), chip(String(report.alerts.length), report.alerts.length ? level : "off"));
        side.append(sideHead, alertList(report));
        article.append(main, side);
        return article;
      }));
    // Live text is patched in place so the panel (and its alert glow) is not rebuilt on every refresh.
    const summaryNode = coresRow.querySelector(".cr-core-summary");
    if (summaryNode && shown[0] && summaryNode.textContent !== shown[0].report.summary) summaryNode.textContent = shown[0].report.summary;
  }

  // ---------- signal rack (Learning view) ----------
  function renderLearning(data) {
    const report = data.cores.find((c) => c.name === "learning")?.report;
    learning.update(data, report?.alerts ?? []);
  }

  // ---------- camera wall (Vision view) ----------
  const renderCameras = (data) => vision.update(data);

  // ---------- Robot and Optimization views ----------
  const renderMap = (data) => robot.update(data);

  // ---------- bus and actions ----------
  const filterBar = el("div", "cr-filters");
  filterBar.setAttribute("role", "group");
  filterBar.setAttribute("aria-label", "Timeline filter");
  for (const [id, label] of FILTERS) {
    const button = el("button", "cr-filter", label);
    button.type = "button";
    button.dataset.filter = id;
    button.addEventListener("click", () => { filter = id; syncFilters(); renderTimeline(); });
    filterBar.append(button);
  }
  const syncFilters = () => filterBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === filter)));
  const actionsHost = el("div", "cr-actions");
  const timeline = el("ol", "cr-timeline");
  timeline.setAttribute("aria-label", "Core event timeline");
  activity.body.append(filterBar, timeline);
  ops.body.append(actionsHost);
  syncFilters();

  function renderActions(data) {
    const sections = [];
    const group = (title, items, empty) => {
      const wrap = el("div", "cr-group");
      wrap.append(el("h4", "cr-mini", title));
      const list = el("ul", "cr-list");
      list.append(...(items.length ? items : [el("li", "cr-empty", empty)]));
      wrap.append(list);
      return wrap;
    };
    const orderRows = [...data.orders].reverse().map((o) => {
      const li = el("li", "cr-row");
      const level = { completed: "ok", running: "info", refused: "warn", failed: "crit", interrupted: "warn" }[o.status] ?? "info";
      li.append(chip(o.status, level), el("span", "cr-row-main", `${CORE_TITLE[o.core]} · ${words(o.control)}${o.followups ? ` · ${o.followups} follow-up` : ""}`));
      if (o.pending_followup) {
        const yes = el("button", "cr-btn cr-btn--small", "Approve follow-up");
        const no = el("button", "cr-btn cr-btn--small", "Decline");
        yes.type = no.type = "button";
        yes.addEventListener("click", () => act("Follow-up", () => http("POST", `/api/orders/${o.id}/followup/approval?accepted=true`)));
        no.addEventListener("click", () => act("Follow-up", () => http("POST", `/api/orders/${o.id}/followup/approval?accepted=false`)));
        li.append(yes, no);
      }
      return li;
    });
    const workRows = data.work_orders.map((w) => {
      const li = el("li", "cr-row");
      const level = { open: "warn", in_progress: "info", completed: "ok" }[w.status] ?? "info";
      li.append(chip(words(w.status), level), el("span", "cr-row-main", w.title), el("span", "cr-sub", w.part ?? "no part"));
      return li;
    });
    const runRows = data.runs.slice(0, 4).map((r) => {
      const li = el("li", "cr-row");
      const level = { running: "info", completed: "ok", interrupted: "warn", failed: "crit", timeout: "crit" }[r.status] ?? "info";
      li.append(chip(r.status, level), el("span", "cr-row-main", `${CORE_TITLE[r.core]} · ${r.kind}`), el("time", "cr-time", ago(r.started_at)));
      return li;
    });
    sections.push(group("Orders", orderRows, "No orders yet."), group("Work orders", workRows, "No open work orders."), group("Agent runs", runRows, data.agents.enabled ? "No runs yet." : "Core agents are off; reference analysers answer."));
    gated(actionsHost, JSON.stringify([data.orders, data.work_orders.map((w) => [w.id, w.status]), data.runs.map((r) => [r.id, r.status])]), () => sections);
  }

  function renderTimeline() {
    const shown = events.filter((e) => e.kind !== "core_tool_called" && (filter === "all" || CATEGORY(e.kind) === filter)).slice(-40).reverse();
    gated(timeline, JSON.stringify([filter, shown.map((e) => e.seq)]), () =>
      shown.length
        ? shown.map((e) => {
          const li = el("li", "cr-event");
          li.dataset.level = eventLevel(e);
          li.dataset.category = CATEGORY(e.kind);
          const ref = e.body?.correlation_id ? e.body.correlation_id.slice(0, 8) : "";
          li.append(lamp(eventLevel(e)), el("time", "cr-time", clock(e.time)), el("span", "cr-event-text", describe(e)));
          if (ref) li.append(el("code", "cr-ref", ref));
          li.title = `${e.kind}${ref ? ` · correlation ${e.body.correlation_id}` : ""}`;
          return li;
        })
        : [el("li", "cr-empty", "No events for this filter yet.")]);
  }

  // ---------- polling ----------
  function apply(data) {
    panel = data;
    renderCores(data);
    if (view === "learning") renderLearning(data);
    if (view === "vision") renderCameras(data);
    if (view === "robot") renderMap(data);
    if (view === "overview") { renderStats(data); renderActions(data); }
    if (data.events.length) {
      events = [...events, ...data.events.filter((e) => e.seq > after)].slice(-150);
      after = data.last_seq;
    }
    if (view === "overview") renderTimeline();
    root.dataset.stale = "false";
  }

  async function poll(immediate = false) {
    clearTimeout(timer);
    if (destroyed) return;
    const id = getPlant();
    if (!id) { timer = setTimeout(poll, POLL_MS); return; }
    if (id !== plantId) {
      plantId = id; after = 0; events = []; panel = null; learning.reset();
      generation.value += 1; frameAt = 0; robot.reset(); optimizationView.reset();
      for (const node of [coresRow, statsHost, actionsHost, timeline]) delete node.dataset.sig;
      vision.reset();
    }
    if (document.hidden && !immediate) { timer = setTimeout(poll, POLL_MS); return; }
    if (busy) return;
    busy = true;
    try {
      const data = await http("GET", `${base()}/cores/panel?after=${after}`);
      if (destroyed || id !== plantId) return;
      banner.hidden = true;
      apply(data);
      if (view === "optimization") optimizationView.update();
    } catch {
      banner.hidden = false;
      root.dataset.stale = "true";
    } finally {
      busy = false;
      if (!destroyed) timer = setTimeout(poll, POLL_MS);
    }
  }

  const onVisible = () => { if (!document.hidden) poll(true); };
  document.addEventListener("visibilitychange", onVisible);
  poll(true);
  if (view === "learning") learning.start();

  function setView(next) {
    if (!CORE_VIEWS.includes(next) || next === view) return;
    view = next;
    frameAt = 0;
    for (const node of [coresRow, statsHost, actionsHost, timeline]) delete node.dataset.sig;
    layout();
    if (view === "learning") learning.start(); else learning.stop();
    if (panel) apply(panel);
    poll(true);
  }

  return {
    setView,
    destroy() {
      destroyed = true;
      learning.destroy();
      vision.destroy();
      robot.destroy();
      optimizationView.destroy();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      host.replaceChildren();
    },
  };
}
