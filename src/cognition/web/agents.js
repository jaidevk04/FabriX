// Agent estate page: the main harness, the four core agents and the two gateways as one connection map,
// with what each is doing right now, and a live log, an action table and an overview for the selected agent.
// Read only. The server keeps the log until the plant is reset, so it survives page changes.
import { ago, badge, chip, clock, el, glyph, http, svg, words } from "./cores-parts.js";

const MAP_POLL_MS = 1500;
const LOG_POLL_MS = 1000;
const NODE_W = 210;
const NODE_H = 88;

// Fixed layout on a 1160 x 580 canvas. Three layer bands with a label gutter on the left; edges come from the
// server and geometry is local. Every node sits inside its band.
const POS = {
  harness: { x: 635, y: 90, w: 300, h: 84 },
  learning: { x: 260, y: 250, w: NODE_W, h: NODE_H },
  vision: { x: 510, y: 250, w: NODE_W, h: NODE_H },
  robot: { x: 760, y: 250, w: NODE_W, h: NODE_H },
  optimization: { x: 1010, y: 250, w: NODE_W, h: NODE_H },
  fleet: { x: 560, y: 410, w: 200, h: 80 },
  gateway: { x: 940, y: 410, w: 220, h: 80 },
  plant: { x: 750, y: 530, w: 300, h: 40 },
};
const BANDS = [
  ["ORCHESTRATION", "decides, never writes", 20, 160],
  ["SPECIALIST AGENTS", "watch and advise", 180, 320],
  ["GOVERNANCE", "the only writers", 345, 475],
  ["WORLD", "", 495, 565],
];
const AGENT_IDS = ["harness", "learning", "vision", "robot", "optimization", "gateway", "fleet"];
const TAGS = {
  TEXT: "text", THINK: "text", FINAL: "text", TOOL: "tool", RESULT: "tool", ORDER: "order", COMMAND: "order",
  ACTION: "order", MISSION: "order", PROPOSAL: "order", APPROVAL: "order", ALERT: "alert", WARN: "alert",
  RUN: "run", AUTO: "run", ASK: "bus", BUS: "bus", REPORT: "run", REFERENCE: "run", VERIFY: "order", OBS: "bus",
};
const FILTERS = [["all", "All"], ["tool", "Tools"], ["text", "Reasoning"], ["order", "Orders and actions"], ["alert", "Alerts"], ["bus", "Evidence bus"], ["bad", "Problems"]];

const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);
const point = (id, side) => {
  const p = POS[id];
  return side === "top" ? { x: p.x, y: p.y - p.h / 2 } : side === "bottom" ? { x: p.x, y: p.y + p.h / 2 } : { x: p.x, y: p.y };
};

export async function agentsPage({ api }) {
  const host = document.getElementById("agents-host");
  const params = new URLSearchParams(location.search);
  let plants;
  try { plants = await api("/api/plants"); } catch (error) {
    host.replaceChildren(el("p", "cr-banner", `Unable to load plants: ${error.message}`));
    return;
  }
  if (!plants.length) { host.replaceChildren(el("p", "cr-empty", "No plants yet. Add a plant to see its agents.")); return; }
  let stored = null;
  try { stored = localStorage.getItem("avenor.plant"); } catch { /* storage unavailable */ }
  const known = (id) => plants.find((p) => p.spec.id === id)?.spec.id;
  const plantId = known(params.get("plant")) ?? known(stored) ?? plants[0].spec.id;
  const plantName = plants.find((p) => p.spec.id === plantId)?.spec.name ?? plantId;
  const base = `/api/plants/${encodeURIComponent(plantId)}`;

  let estate = null;
  let selected = params.get("agent") && AGENT_IDS.includes(params.get("agent")) ? params.get("agent") : "harness";
  let hovered = null;
  let tab = "log";
  let showTraffic = true;
  let filter = "all";
  let follow = true;
  let floor = 0;
  const logs = new Map(); // agent -> { entries, cursor }
  let logTimer = null;
  let mapTimer = null;
  let destroyed = false;

  // ---------- skeleton ----------
  const root = el("div", "ae");
  const head = el("header", "ae-head");
  const headChips = el("div", "ae-head-chips");
  head.append(headChips);
  const mapCard = el("section", "ae-card ae-mapcard");
  const mapHead = el("div", "ae-map-head");
  const mapTitle = el("div", "ae-map-title");
  mapTitle.append(el("strong", "", "ORCHESTRATION MAP"), el("span", "ae-ref", "live traffic on the edges · click any agent"));
  const toggle = el("label", "ae-toggle");
  const box = el("input");
  box.type = "checkbox"; box.checked = true;
  toggle.append(box, el("span", "ae-toggle-slider"), el("span", "ae-toggle-text", "Live traffic flow"));
  mapHead.append(mapTitle, toggle);
  const mapWrap = el("div", "ae-map-wrap");
  mapCard.append(mapHead, mapWrap);
  const detail = el("section", "ae-card ae-detail");
  root.append(head, mapCard, detail);
  host.replaceChildren(root);

  box.addEventListener("change", () => { showTraffic = box.checked; drawMap(); });

  // ---------- map ----------
  let svgRoot = null;
  let nodeEls = new Map();
  let edgeEls = new Map();

  function edgePath(edge) {
    const id = edge.id;
    if (id === "harness>gateway") {
      const a = point("harness", "bottom"); const b = point("gateway", "top");
      const ch = b.y - 30;
      return `M${a.x},${a.y} V${ch - 12} Q${a.x},${ch} ${a.x + 12},${ch} H${b.x - 12} Q${b.x},${ch} ${b.x},${ch + 12} V${b.y}`;
    }
    if (id.startsWith("harness>")) {
      const a = point("harness", "bottom"); const b = point(edge.to, "top");
      return `M${a.x},${a.y} C${a.x},${a.y + 56} ${b.x},${b.y - 56} ${b.x},${b.y}`;
    }
    if (id.startsWith("bus:")) {
      const a = POS[edge.from]; const b = POS[edge.to];
      return `M${a.x + a.w / 2},${a.y} H${b.x - b.w / 2}`;
    }
    const a = point(edge.from, "bottom"); const b = point(edge.to, "top");
    return `M${a.x},${a.y} C${a.x},${a.y + 48} ${b.x},${b.y - 48} ${b.x},${b.y}`;
  }

  function related(edge) {
    const focus = hovered ?? selected;
    if (!focus) return false;
    return edge.from === focus || edge.to === focus;
  }

  function drawMap() {
    if (!estate) return;
    if (!svgRoot) buildMap();
    const nodes = new Map(estate.nodes.map((n) => [n.id, n]));
    const focus = hovered ?? selected;
    for (const edge of estate.edges) {
      const node = edgeEls.get(edge.id);
      if (!node) continue;
      node.dataset.active = String(showTraffic && edge.active);
      node.dataset.related = String(related(edge));
      node.dataset.dim = String(Boolean(focus) && !related(edge));
    }
    for (const [id, key] of [["gateway>plant", "gateway"], ["fleet>plant", "fleet"]]) {
      const node = edgeEls.get(id);
      if (node) { node.dataset.active = String(showTraffic && nodes.get(key)?.state === "working"); node.dataset.dim = String(Boolean(focus) && focus !== key); node.dataset.related = String(focus === key); }
    }
    for (const [id, n] of nodes) {
      const g = nodeEls.get(id);
      if (!g) continue;
      g.dataset.state = n.state;
      g.dataset.selected = String(id === selected);
      g.querySelector(".ae-node-mode").textContent = n.mode;
      g.querySelector(".ae-node-live").textContent = n.state === "working" ? (n.last ? clip(n.last.title, 22) : "working") : n.phase && n.phase !== "off" && n.kind === "harness" ? words(n.phase) : "idle";
      const sub = g.querySelector(".ae-node-sub");
      if (n.kind === "harness") sub.textContent = n.model ? `${n.subtitle} · ${n.model}` : n.subtitle;
    }
  }

  function buildMap() {
    svgRoot = svg("svg", { viewBox: "0 0 1160 580", class: "ae-svg", role: "img", "aria-label": "Agent orchestration map" });
    const defs = svg("defs");
    const glow = svg("filter", { id: "ae-glow", x: "-20%", y: "-20%", width: "140%", height: "140%" });
    glow.append(svg("feGaussianBlur", { stdDeviation: 5, result: "b" }), svg("feComposite", { in: "SourceGraphic", in2: "b", operator: "over" }));
    defs.append(glow);
    svgRoot.append(defs);
    for (const [label, note, top, bottom] of BANDS) {
      const band = svg("g", { class: "ae-band" });
      band.append(svg("rect", { x: 8, y: top, width: 1144, height: bottom - top, rx: 12 }));
      band.append(svg("text", { x: 22, y: top + 24, class: "ae-tier" }, label));
      if (note) band.append(svg("text", { x: 22, y: top + 40, class: "ae-tier-note" }, note));
      svgRoot.append(band);
    }
    const edgeLayer = svg("g", { class: "ae-edges" });
    for (const edge of estate.edges) {
      const path = svg("path", { d: edgePath(edge), class: `ae-edge${edge.id.startsWith("bus:") ? " ae-edge--bus" : ""}` });
      path.append(svg("title", {}, edge.label));
      edgeEls.set(edge.id, path);
      edgeLayer.append(path);
    }
    for (const [id, from] of [["gateway>plant", "gateway"], ["fleet>plant", "fleet"]]) {
      const a = point(from, "bottom"); const b = point("plant", "top");
      const path = svg("path", { d: `M${a.x},${a.y} C${a.x},${a.y + 30} ${b.x},${b.y - 30} ${b.x},${b.y}`, class: "ae-edge ae-edge--plant" });
      edgeEls.set(id, path);
      edgeLayer.append(path);
    }
    svgRoot.append(edgeLayer);
    for (const n of estate.nodes) svgRoot.append(buildNode(n));
    // Plant sink
    const p = POS.plant;
    const sink = svg("g", { class: "ae-sink" });
    sink.append(svg("rect", { x: p.x - p.w / 2, y: p.y - p.h / 2, width: p.w, height: p.h, rx: 8 }), svg("text", { x: p.x, y: p.y + 4, "text-anchor": "middle" }, "Simulated plant · only the Gateways write here"));
    svgRoot.append(sink);
    mapWrap.replaceChildren(svgRoot);
  }

  function buildNode(n) {
    const p = POS[n.id];
    const g = svg("g", { class: "ae-node", "data-kind": n.kind, "data-id": n.id, tabindex: 0, role: "button", "aria-label": `${n.name}. Show its live log` });
    const x = p.x - p.w / 2; const y = p.y - p.h / 2;
    g.append(svg("rect", { x, y, width: p.w, height: p.h, rx: 10, class: "ae-node-body" }));
    g.append(svg("text", { x: x + 16, y: y + 24, class: "ae-node-name" }, n.name));
    const sub = svg("text", { x: x + 16, y: y + 41, class: "ae-node-sub" }, clip(n.subtitle, p.w > 250 ? 52 : p.w > 205 ? 33 : 28));
    g.append(sub);
    g.append(svg("text", { x: x + 16, y: y + p.h - 12, class: "ae-node-live" }, "idle"));
    // Status beacon
    const bx = x + p.w - 18; const by = y + 20;
    g.append(svg("circle", { cx: bx, cy: by, r: 8, class: "ae-beacon-aura" }), svg("circle", { cx: bx, cy: by, r: 4, class: "ae-beacon" }));
    // Mode tag
    const tag = svg("g", { class: "ae-node-tag" });
    tag.append(svg("rect", { x: x + p.w - 106, y: y + p.h - 26, width: 94, height: 16, rx: 4 }), svg("text", { x: x + p.w - 59, y: y + p.h - 14.5, "text-anchor": "middle", class: "ae-node-mode" }, n.mode));
    g.append(tag);
    g.addEventListener("click", () => select(n.id));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(n.id); } });
    g.addEventListener("mouseenter", () => { hovered = n.id; drawMap(); });
    g.addEventListener("mouseleave", () => { hovered = null; drawMap(); });
    nodeEls.set(n.id, g);
    return g;
  }

  // ---------- detail ----------
  const switcher = el("div", "ae-switcher");
  const header = el("div", "ae-detail-head");
  const pulse = el("div", "ae-pulse");
  const tabBar = el("div", "ae-tabs");
  tabBar.setAttribute("role", "tablist");
  const body = el("div", "ae-body");
  detail.append(switcher, header, pulse, tabBar, body);
  for (const [id, label] of [["log", "Live log"], ["actions", "Actions"], ["overview", "Overview"]]) {
    const button = el("button", "ae-tab", label);
    button.type = "button"; button.dataset.tab = id; button.setAttribute("role", "tab");
    button.addEventListener("click", () => { tab = id; renderDetail(); });
    tabBar.append(button);
  }

  function select(id) {
    selected = id;
    const url = new URL(location.href);
    url.searchParams.set("agent", id);
    window.history.replaceState(null, "", url);
    drawMap();
    renderDetail();
    pollLog(true);
  }

  const node = () => estate?.nodes.find((n) => n.id === selected);
  const cache = () => {
    if (!logs.has(selected)) logs.set(selected, { entries: [], cursor: 0 });
    return logs.get(selected);
  };

  function renderSwitcher() {
    switcher.replaceChildren(el("span", "ae-switch-label", "AGENTS"), ...AGENT_IDS.map((id) => {
      const n = estate?.nodes.find((x) => x.id === id);
      const b = el("button", `ae-chip${id === selected ? " is-selected" : ""}`);
      b.type = "button";
      const dot = el("i", "ae-chip-dot");
      dot.dataset.state = n?.state ?? "idle";
      b.append(dot, document.createTextNode(n?.name ?? id));
      b.addEventListener("click", () => select(id));
      return b;
    }));
  }

  function renderHeader() {
    const n = node();
    if (!n) return;
    const title = el("div", "ae-title-line");
    title.append(glyph(n.kind === "harness" ? "sparkle" : n.kind === "core" ? "chip" : "shield", "cr-glyph ae-title-icon"), el("h3", "", n.name));
    const pill = el("span", "ae-pill", n.state === "working" ? "Working" : "Idle");
    pill.dataset.state = n.state;
    title.append(pill, chip(n.mode, n.mode === "ADK agent" || n.mode === "live model" ? "info" : "off", n.detail || n.description));
    if (n.model) title.append(el("span", "ae-model", n.model));
    header.replaceChildren(title, el("p", "ae-desc", n.description));
  }

  function renderPulse() {
    const n = node();
    const c = logs.get(selected)?.entries ?? [];
    const last = n?.last;
    const stats = [
      ["Now", n?.state === "working" ? (last ? clip(last.title, 60) : "Working") : "Waiting for work"],
      ["Phase", n ? words(n.phase) : "—"],
      ["Log entries", String(c.length)],
      ["Tool calls", String(c.filter((e) => e.tag === "TOOL").length)],
      ["Last activity", last ? ago(last.time) : "none yet"],
    ];
    pulse.replaceChildren(...stats.map(([label, value], i) => {
      const item = el("div", "ae-stat");
      if (i === 0) { const dot = el("i", "ae-live-dot"); dot.dataset.state = n?.state ?? "idle"; item.append(dot); }
      const text = el("div");
      text.append(el("span", "ae-stat-label", label), el("strong", "", value));
      item.append(text);
      return item;
    }));
  }

  function renderDetail() {
    renderSwitcher();
    renderHeader();
    renderPulse();
    for (const b of tabBar.children) { b.setAttribute("aria-selected", String(b.dataset.tab === tab)); b.classList.toggle("is-active", b.dataset.tab === tab); }
    if (tab === "log") renderLog(true);
    else if (tab === "actions") renderActions();
    else renderOverview();
  }

  // ---------- live log ----------
  const logBar = el("div", "ae-logbar");
  const logList = el("ol", "ae-log");
  logList.setAttribute("aria-label", "Live agent log");
  logList.setAttribute("aria-live", "off");
  let logBuilt = false;

  const category = (e) => TAGS[e.tag] ?? "run";
  const visible = (e) => filter === "all" || (filter === "bad" ? e.level === "crit" || e.level === "warn" : category(e) === filter);

  function rowFor(e) {
    const li = el("li", "ae-row");
    li.dataset.level = e.level;
    li.dataset.seq = e.seq;
    li.dataset.group = e.group || "";
    li.dataset.tag = e.tag;
    const tag = el("span", "ae-tag", e.tag);
    tag.dataset.cat = category(e);
    const text = el("span", "ae-text", e.title);
    li.append(el("time", "ae-time", clock(e.time)), tag, text);
    if (e.detail) {
      const pre = el("pre", "ae-detail-json", prettify(e.detail));
      pre.hidden = true;
      li.append(pre);
      li.classList.add("has-detail");
      li.addEventListener("click", () => { pre.hidden = !pre.hidden; li.classList.toggle("is-open", !pre.hidden); });
    }
    return li;
  }

  function prettify(detail) {
    try { return JSON.stringify(JSON.parse(detail), null, 2); } catch { return detail; }
  }

  function renderLog(rebuild = false) {
    if (tab !== "log") return;
    if (rebuild || !logBuilt) {
      body.replaceChildren(logBar, logList);
      logBar.replaceChildren(
        ...FILTERS.map(([id, label]) => {
          const b = el("button", `ae-filter${id === filter ? " is-active" : ""}`, label);
          b.type = "button";
          b.addEventListener("click", () => { filter = id; renderLog(true); });
          return b;
        }),
        el("span", "ae-spacer"),
        (() => {
          const f = el("button", `ae-follow${follow ? " is-on" : ""}`, follow ? "Following" : "Paused");
          f.type = "button";
          f.setAttribute("aria-pressed", String(follow));
          f.addEventListener("click", () => { follow = !follow; renderLog(true); if (follow) logList.scrollTop = logList.scrollHeight; });
          return f;
        })(),
      );
      logList.replaceChildren();
      const entries = cache().entries.filter(visible);
      if (!entries.length) logList.append(emptyLog());
      else appendRows(entries);
      logBuilt = true;
    }
  }

  function emptyLog() {
    const n = node();
    const box_ = el("li", "ae-empty");
    box_.append(glyph("list", "cr-glyph ae-empty-icon"), el("strong", "", "No activity yet"), el("span", "cr-sub", n?.mode === "reference analyser"
      ? "This core runs as an offline reference analyser. Its answers and orders appear here. Turn on core agents (COGNITION_CORE_AGENTS=true) to see ADK reasoning and tool calls."
      : "Start the simulation and inject a fault. Everything this agent does is logged here and kept until the plant is reset."));
    return box_;
  }

  // Consecutive text chunks from one run are one paragraph, not one row each.
  function appendRows(entries) {
    logList.querySelector(".ae-empty")?.remove();
    for (const e of entries) {
      const last = logList.lastElementChild;
      if (e.tag === "TEXT" && last && last.dataset.tag === "TEXT" && last.dataset.group === (e.group || "")) {
        last.querySelector(".ae-text").textContent += e.title;
        last.dataset.seq = e.seq;
        continue;
      }
      logList.append(rowFor(e));
    }
    while (logList.children.length > 800) logList.firstElementChild.remove();
    if (follow) logList.scrollTop = logList.scrollHeight;
  }

  // ---------- actions ----------
  function renderActions() {
    const entries = cache().entries;
    const actionTags = new Set(["TOOL", "ORDER", "COMMAND", "ACTION", "MISSION", "PROPOSAL", "APPROVAL", "VERIFY"]);
    const rows = [];
    entries.forEach((e, i) => {
      if (!actionTags.has(e.tag)) return;
      let outcome = "";
      if (e.tag === "TOOL") {
        const name = e.title.replace(/^Called /, "");
        const result = entries.slice(i + 1, i + 12).find((r) => r.tag === "RESULT" && r.group === e.group && r.title.startsWith(name));
        outcome = result?.detail ?? "";
      }
      rows.push({ e, outcome });
    });
    const wrap = el("div", "ae-table-wrap");
    if (!rows.length) {
      wrap.append(emptyLogLike("No actions yet", "Tool calls, orders, commands and missions appear here with their inputs and results."));
      body.replaceChildren(wrap);
      return;
    }
    const table = el("table", "ae-table");
    const thead = el("thead");
    const hr = el("tr");
    for (const t of ["Time", "Kind", "Action", "Input", "Outcome"]) hr.append(el("th", "", t));
    thead.append(hr);
    const tbody = el("tbody");
    for (const { e, outcome } of rows.slice(-300).reverse()) {
      const tr = el("tr");
      tr.dataset.level = e.level;
      const kind = el("td");
      const tag = el("span", "ae-tag", e.tag);
      tag.dataset.cat = category(e);
      kind.append(tag);
      tr.append(el("td", "ae-mono", clock(e.time)), kind, el("td", "ae-action", e.title), el("td", "ae-mono ae-cell", clip(e.tag === "TOOL" ? e.detail : "", 200)), el("td", "ae-mono ae-cell", clip(e.tag === "TOOL" ? outcome : e.detail, 260)));
      tbody.append(tr);
    }
    table.append(thead, tbody);
    wrap.append(table);
    body.replaceChildren(wrap);
  }

  function emptyLogLike(title, text) {
    const box_ = el("div", "ae-empty ae-empty--block");
    box_.append(glyph("list", "cr-glyph ae-empty-icon"), el("strong", "", title), el("span", "cr-sub", text));
    return box_;
  }

  // ---------- overview ----------
  function renderOverview() {
    const n = node();
    if (!n) return;
    const grid = el("div", "ae-overview");
    const facts = el("section", "ae-block");
    facts.append(el("h4", "cr-mini", "Identity"));
    const list = el("dl", "ae-facts");
    for (const [k, v] of [["Role", n.description], ["Mode", n.mode], ["Model", n.model ?? "none"], ["Phase", words(n.phase)], ["Note", n.detail || "—"]]) {
      list.append(el("dt", "", k), el("dd", "", v));
    }
    facts.append(list);
    const conn = el("section", "ae-block");
    conn.append(el("h4", "cr-mini", "Connections"));
    const links = el("ul", "ae-links");
    const nameOf = (id) => estate.nodes.find((x) => x.id === id)?.name ?? id;
    for (const edge of estate.edges.filter((x) => x.from === n.id || x.to === n.id)) {
      const li = el("li");
      const out = edge.from === n.id;
      li.append(el("span", "ae-link-dir", out ? "to" : "from"), el("strong", "", nameOf(out ? edge.to : edge.from)), el("span", "cr-sub", edge.label));
      if (edge.active) li.append(chip("active", "info"));
      links.append(li);
    }
    if (!links.children.length) links.append(el("li", "cr-empty", "No connections."));
    conn.append(links);
    const tools = el("section", "ae-block");
    tools.append(el("h4", "cr-mini", `Tools (${n.tools.length})`));
    const toolChips = el("div", "cr-chips");
    for (const t of n.tools) toolChips.append(el("span", "lv-chip", words(t)));
    if (!n.tools.length) toolChips.append(el("span", "cr-sub", n.kind === "harness" ? "Scoped industry tools, served over MCP per investigation." : "None. This component is deterministic code."));
    tools.append(toolChips);
    const skills = el("section", "ae-block");
    skills.append(el("h4", "cr-mini", `Skills (${n.skills.length})`));
    const skillChips = el("div", "cr-chips");
    for (const s of n.skills) skillChips.append(el("span", "lv-chip", words(s)));
    if (!n.skills.length) skillChips.append(el("span", "cr-sub", "None."));
    skills.append(skillChips);
    grid.append(facts, conn, tools, skills);
    body.replaceChildren(grid);
  }

  // ---------- polling ----------
  // Kill switch status: armed with the time left, tripped, or nothing when it is off.
  function killChips(kill) {
    if (!kill) return [];
    if (kill.tripped) return [chip("kill switch tripped", "crit", "All agents and the harness were stopped. Reset the plant or start a new run.")];
    if (kill.seconds_left !== null && kill.configured) {
      const total = Math.max(0, Math.round(kill.seconds_left));
      return [chip(`kill switch in ${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`, total <= 60 ? "warn" : "info", "All agents and the harness stop when this runs out")];
    }
    return [];
  }

  function renderHead_() {
    const a = estate.agents;
    headChips.replaceChildren(
      chip(plantName, "info"),
      chip(a.enabled && a.available ? "Core agents: ADK" : "Core agents: reference analysers", a.enabled && a.available ? "ok" : "off", a.reason || "Core agents are on and a model is configured."),
      chip("log kept until the plant is reset", "off", "The log restarts only when the plant is reset"),
      ...killChips(estate.kill),
      badge("SIM", "Simulated plant and agents' inputs"),
    );
  }

  async function pollMap() {
    clearTimeout(mapTimer);
    if (destroyed) return;
    try {
      const data = await http("GET", `${base}/agents/estate`);
      if (data.floor !== floor) { floor = data.floor; logs.clear(); logBuilt = false; }
      const first = !estate;
      estate = data;
      renderHead_();
      drawMap();
      if (first) { renderDetail(); pollLog(true); } else { renderSwitcher(); renderHeader(); renderPulse(); if (tab === "overview") renderOverview(); }
    } catch { /* the next poll retries */ }
    if (!destroyed) mapTimer = setTimeout(pollMap, document.hidden ? MAP_POLL_MS * 4 : MAP_POLL_MS);
  }

  async function pollLog(now = false) {
    clearTimeout(logTimer);
    if (destroyed) return;
    const agent = selected;
    const c = cache();
    try {
      const data = await http("GET", `${base}/agents/${agent}/log?after=${c.cursor}&limit=500`);
      if (agent !== selected) return;
      if (data.floor !== floor) { floor = data.floor; logs.clear(); logBuilt = false; return pollLog(true); }
      if (data.entries.length) {
        c.entries.push(...data.entries);
        if (c.entries.length > 1500) c.entries.splice(0, c.entries.length - 1500);
        c.cursor = data.last_seq;
        if (tab === "log") {
          if (!logBuilt) renderLog(true); else appendRows(data.entries.filter(visible));
        } else if (tab === "actions") renderActions();
      } else if (tab === "log" && !logBuilt) renderLog(true);
      renderPulse();
    } catch { /* the next poll retries */ }
    if (!destroyed) logTimer = setTimeout(pollLog, document.hidden ? LOG_POLL_MS * 4 : LOG_POLL_MS);
  }

  pollMap();
  const onVisible = () => { if (!document.hidden) { pollMap(); pollLog(true); } };
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("pagehide", () => {
    destroyed = true;
    clearTimeout(mapTimer); clearTimeout(logTimer);
    document.removeEventListener("visibilitychange", onVisible);
  });
}
