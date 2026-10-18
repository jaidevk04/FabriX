// Plants page: each plant is a live card with a 3D hero of its own equipment.
// The hero is the studio's model rendered small. It holds a still pose while the plant is stopped
// and turns and animates while the simulation runs (or the card is hovered or focused).
// The whole page is sized to the viewport: a single scale unit is fitted to the screen and to the
// number of plants, so cards grow and shrink with the resolution instead of scrolling.
// Read-only: it polls existing endpoints and links into the studio.

import { buildContext, evaluate, plantCondition } from "./plant-signals.js";
import { modelFor } from "./plant-models.js";
import { createSymbol, mount, unmount, setPaused, svgEl } from "./symbols.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
// Card footprint in scale units (1 unit = the fitted font size), used to fit cards to the screen.
const CARD_W = 32;
const CARD_H = 43;
const GAP = 1.5;
const MIN_UNIT = 9;
const MAX_UNIT = 26;
// How far a symbol paints outside its own box, for the fallback schematic crop.
const OVERHANG = { burner: [100, 0, 0, 0], burnerbank: [0, 0, 0, 52], kiln: [14, 0, 18, 0] };
const ICON = {
  reflexive: "M12 3 4.5 6v5.5c0 4.2 2.9 7.3 7.5 9 4.6-1.7 7.5-4.8 7.5-9V6L12 3Z M8.6 12.2l2.5 2.5 4.4-5",
  perceptual: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z M12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6Z",
  cognitive: "M8.2 11.3l7.6-4.1 M8.2 12.7l7.6 4.1 M6 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z M18 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z M18 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  flow: "M3 5h6v5H3z M15 5h6v5h-6z M9 15h6v5H9z M9 7.5h6 M6 10v2.5h12V10 M12 12.5V15",
  hmi: "M3 5h18v12H3z M8 21h8 M12 17v4 M7 13l3-3 3 2 4-4",
  cement: "M2.5 10.5h4l1.5-2h8l1.5 2h4v5h-4l-1.5 2h-8l-1.5-2h-4z M7 20.5h2 M15 20.5h2 M10 12.5h4",
  steel: "M3 20h18 M4.5 20V9.5l7.5-5 7.5 5V20 M8.5 20v-6h7v6 M9 11.5h6",
  chemical: "M9 3h6 M10 3v5.5L5.5 17a2.5 2.5 0 0 0 2.2 3.5h8.6a2.5 2.5 0 0 0 2.2-3.5L14 8.5V3 M7.8 14.5h8.4",
  arrow: "M7 17 17 7 M8 7h9v9",
};
const LAYER_LEVEL = { regulating: "ok", blocked: "warn", interlocked: "crit", nominal: "ok", normal: "ok", conflict: "warn", anomaly: "warn", attention: "warn", idle: "info" };

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
function icon(name, className = "fl-svg") {
  const svg = svgEl("svg", { viewBox: "0 0 24 24", class: className, "aria-hidden": "true" });
  svgEl("path", { d: ICON[name] }, svg);
  return svg;
}
// Writes a value and replays a short highlight when it changed.
function put(node, text) {
  if (node.textContent === text) return;
  node.textContent = text;
  node.classList.remove("flash");
  void node.offsetWidth;
  node.classList.add("flash");
}
const titleCase = (text) => text.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
const ago = (iso) => {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
};

// The 3D module is large, so it loads after the cards are on screen. Without WebGL, cards fall back
// to the animated schematic.
let sceneModule;
const loadScene = () => (sceneModule ??= import("./scene.js?v=avenor-20261019-1").catch(() => null));

function buildFallback(view) {
  const model = view.model;
  const nodes = model.flow.card.map((id) => model.flow.nodes.find((n) => n.id === id));
  let box = model.flow.cardView;
  if (!box) {
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const n of nodes) {
      const [l, t, r, b] = OVERHANG[n.kind] ?? [0, 0, 0, 0];
      x0 = Math.min(x0, n.x - l); y0 = Math.min(y0, n.y - t);
      x1 = Math.max(x1, n.x + n.w + r); y1 = Math.max(y1, n.y + n.h + b);
    }
    box = [x0 - 26, y0 - 26, x1 - x0 + 52, y1 - y0 + 52];
  }
  const svg = svgEl("svg", { viewBox: box.join(" "), class: "fl-scene", preserveAspectRatio: "xMidYMid meet", "aria-hidden": "true" });
  const items = nodes.map((node) => {
    const symbol = createSymbol(node);
    svgEl("g", { transform: `translate(${node.x} ${node.y})` }, svg).append(symbol.g);
    mount(symbol);
    return { node, symbol };
  });
  view.hero.append(svg);
  view.hero.classList.add("is-ready", "is-schematic");
  view.fallback = { svg, items };
  view.sync();
}

async function attachHero(view) {
  const module = await loadScene();
  if (view.destroyed) return;
  try {
    if (!module) throw new Error("scene unavailable");
    const scene = new module.TwinScene(view.hero, () => {}, { compact: true });
    view.three = scene;
    scene.setState(view.plant);
    scene.setActive(view.running || view.hover);
    view.hero.classList.add("is-ready");
  } catch {
    view.three = null;
    buildFallback(view);
  }
}

// ---- a ring gauge for one process indicator ----
function buildRing(item) {
  const root = el("li", "fl-ring");
  const dial = el("div", "fl-ring-dial");
  const svg = svgEl("svg", { viewBox: "0 0 40 40", class: "fl-ring-svg", "aria-hidden": "true" }, dial);
  const base = { cx: 20, cy: 20, r: 16, fill: "none", pathLength: 100, transform: "rotate(-90 20 20)" };
  svgEl("circle", { ...base, class: "ring-track" }, svg);
  const band = svgEl("circle", { ...base, class: "ring-band" }, svg);
  const value = svgEl("circle", { ...base, class: "ring-value" }, svg);
  const reading = el("strong", "fl-ring-value");
  dial.append(reading);
  root.append(dial, el("span", "fl-ring-name", item.name));
  return {
    root,
    set(indicator) {
      const span = indicator.maximum - indicator.minimum || 1;
      const lo = (indicator.band[0] - indicator.minimum) / span;
      const hi = (indicator.band[1] - indicator.minimum) / span;
      band.setAttribute("stroke-dasharray", `${Math.max(0, (hi - lo) * 100)} 100`);
      band.setAttribute("stroke-dashoffset", String(-lo * 100));
      const p = indicator.value === null ? 0 : Math.max(0.004, Math.min(1, (indicator.value - indicator.minimum) / span));
      value.setAttribute("stroke-dasharray", "100 100");
      value.setAttribute("stroke-dashoffset", String(100 - p * 100));
      root.dataset.condition = indicator.condition;
      const digits = ["rpm", "bar"].includes(indicator.unit) || indicator.id === "oxygen" ? 2 : 0;
      put(reading, indicator.value === null ? "—" : indicator.value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits }));
      root.title = indicator.value === null ? `${indicator.name}: unavailable` : `${indicator.name}: ${reading.textContent} ${indicator.unit}`;
    },
  };
}

function buildCard(plant, index) {
  const id = plant.spec.id;
  const model = modelFor(plant.spec.industry);
  const card = el("article", "fl-card");
  card.dataset.plant = id;
  card.style.setProperty("--i", String(index));

  const head = el("header", "fl-top");
  const title = el("div", "fl-title");
  const badge = el("span", "fl-badge");
  badge.append(icon(plant.spec.industry in ICON ? plant.spec.industry : "flow"));
  const link = el("a", "fl-name");
  link.href = `/studio?plant=${encodeURIComponent(id)}`;
  link.append(el("h2", "", plant.spec.name.replace(/\s+demo$/i, " plant")));
  title.append(badge, link);
  const live = el("span", "fl-live");
  live.append(el("i"), el("span", "", "Stopped"));
  head.append(title, live);

  const stage = el("div", "fl-stage");
  const hero = el("div", "fl-hero");
  hero.setAttribute("role", "img");
  hero.setAttribute("aria-label", `${plant.spec.name} equipment`);
  const reading = el("div", "fl-reading");
  const value = el("strong", "fl-temp");
  reading.append(value, el("span", "fl-unit", "°C"));
  const chip = el("span", "fl-chip");
  stage.append(hero, reading, chip);

  const meter = el("div", "fl-meter");
  const track = el("div", "fl-track");
  track.setAttribute("role", "meter");
  track.append(el("span", "fl-track-band"), el("span", "fl-track-mark"));
  const labels = el("div", "fl-meter-labels");
  const setpoint = el("span");
  const deviation = el("span");
  labels.append(setpoint, deviation);
  meter.append(track, labels);

  const rings = el("ul", "fl-rings");
  rings.setAttribute("aria-label", "Process indicators, derived estimates");

  const layers = el("ul", "fl-layers");
  layers.setAttribute("aria-label", "Automation layers");
  const layerViews = {};
  for (const [key, label] of [["reflexive", "Reflexive"], ["perceptual", "Perceptual"], ["cognitive", "Cognitive"]]) {
    const item = el("li", "fl-layer");
    const word = el("span", "");
    item.append(icon(key), word);
    layers.append(item);
    layerViews[key] = { item, word, label };
  }

  const actions = el("div", "fl-actions");
  const open = el("a", "fl-open");
  open.href = link.href;
  const arrow = el("span", "fl-open-icon");
  arrow.append(icon("arrow"));
  open.append(el("span", "", "Open studio"), arrow);
  const tools = [["flow", "Process flow", "&view=flow"], ["hmi", "HMI screens", "&view=hmi"]].map(([name, label, query]) => {
    const tool = el("a", "fl-tool");
    tool.href = link.href + query;
    tool.title = label;
    tool.setAttribute("aria-label", `${plant.spec.name} ${label.toLowerCase()}`);
    tool.append(icon(name));
    return tool;
  });
  const record = el("p", "fl-record");
  actions.append(open, ...tools);

  const coreLamps = el("ul", "fl-cores");
  coreLamps.setAttribute("aria-label", "Cognitive cores");
  const coreViews = {};
  for (const [key, letter, label] of [["learning", "L", "Learning"], ["vision", "V", "Vision"], ["robot", "R", "Robot"], ["optimization", "O", "Optimization"]]) {
    const item = el("li", "fl-core", letter);
    item.dataset.level = "off";
    item.title = `${label} core`;
    coreLamps.append(item);
    coreViews[key] = { item, label };
  }
  card.append(head, stage, meter, rings, layers, coreLamps, record, actions);
  const view = { id, plant, model, card, live, stage, hero, value, chip, track, setpoint, deviation, rings, ringViews: new Map(), layerViews, coreViews, record, running: false, hover: false, three: null, fallback: null, destroyed: false };
  // Motion runs while live or while the card is hovered or focused; otherwise the hero holds a still pose.
  view.sync = () => {
    const active = view.running || view.hover;
    view.three?.setActive(active);
    if (view.fallback) for (const item of view.fallback.items) setPaused(item.symbol, !active);
  };
  const set = (value_) => () => { view.hover = value_; view.sync(); };
  card.addEventListener("pointerenter", set(true));
  card.addEventListener("pointerleave", set(false));
  card.addEventListener("focusin", set(true));
  card.addEventListener("focusout", set(false));
  attachHero(view);
  return view;
}

function destroyView(view) {
  view.destroyed = true;
  view.three?.destroy();
  if (view.fallback) for (const item of view.fallback.items) unmount(item.symbol);
}

export function fleetView({ api }) {
  const grid = $("fleet-cards");
  const search = $("fleet-card-search");
  const main = document.querySelector("main");
  const views = new Map();
  let query = "";
  let timer = 0;
  let renderedOnce = false;
  let lastFit = "";
  $("fl-empty").hidden = true;

  // Fits one scale unit to the screen: tries every column count and keeps the one that lets the
  // cards be largest while all rows still fit the viewport.
  function fit() {
    const visible = [...views.values()].filter((v) => !v.card.hidden).length || 1;
    const width = grid.clientWidth;
    const top = grid.getBoundingClientRect().top + window.scrollY;
    const height = window.innerHeight - top - 18;
    let best = null;
    for (let cols = 1; cols <= visible; cols++) {
      const rows = Math.ceil(visible / cols);
      const unit = Math.min(width / (cols * CARD_W + (cols - 1) * GAP), height / (rows * CARD_H + (rows - 1) * GAP));
      if (!best || unit > best.unit + 0.05) best = { unit, cols, rows };
    }
    const unit = Math.max(MIN_UNIT, Math.min(MAX_UNIT, best.unit));
    // Give each row the height that is left, so the stage absorbs spare space (capped for tall screens).
    const perRow = (height - (best.rows - 1) * GAP * unit) / best.rows / unit;
    const cardEm = Math.max(CARD_H, Math.min(52, perRow));
    const key = `${unit.toFixed(1)}|${best.cols}|${best.rows}|${cardEm.toFixed(1)}`;
    if (key === lastFit) return;
    lastFit = key;
    main.style.setProperty("--u", `${unit.toFixed(2)}px`);
    grid.style.setProperty("--cols", String(best.cols));
    grid.style.setProperty("--card-h", `${cardEm.toFixed(2)}em`);
  }
  const refit = () => requestAnimationFrame(fit);
  window.addEventListener("resize", refit);
  new ResizeObserver(refit).observe(main);

  function update(view, plant, op, run, incidents, cores) {
    const condition = plantCondition(plant);
    const c = op ? buildContext(op) : null;
    view.plant = plant;
    view.running = Boolean(run?.enabled);
    view.card.dataset.level = condition.level;
    view.live.dataset.on = String(view.running);
    view.live.lastChild.textContent = view.running ? `Live · ${run.config.mode}` : "Stopped";
    put(view.chip, condition.label);
    view.chip.dataset.level = condition.level;
    put(view.value, plant.quality === "good" ? plant.temperature.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "—");
    if (view.three) {
      view.three.setState(plant);
      if (!view.three.active) view.three.renderOnce();
    }
    view.sync();
    if (!c) return;
    const T = evaluate(view.model, c, "C");
    const temp = T.get("temp");
    // Warm glow behind the equipment above the setpoint, cool below it.
    const lean = temp.norm === null ? 0 : (temp.norm - 0.5) * 2;
    view.stage.dataset.lean = lean > 0.04 ? "hot" : lean < -0.04 ? "cold" : "ok";
    view.stage.style.setProperty("--glow", String(Math.min(1, Math.abs(lean) * 2.4).toFixed(2)));
    view.track.style.setProperty("--m", String(temp.norm ?? 0.5));
    view.track.style.setProperty("--lo", String(temp.bandNorm?.[0] ?? 0));
    view.track.style.setProperty("--hi", String(temp.bandNorm?.[1] ?? 0));
    view.track.dataset.level = temp.level;
    view.track.dataset.empty = String(temp.value === null);
    put(view.setpoint, `Setpoint ${plant.target.toLocaleString(undefined, { maximumFractionDigits: 0 })} °C`);
    const dev = T.get("dev");
    put(view.deviation, dev.value === null ? "Signal invalid" : `${dev.value >= 0 ? "+" : "−"}${Math.abs(dev.value).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`);
    view.deviation.dataset.level = dev.level;
    if (view.fallback) for (const item of view.fallback.items) if (item.node.drive) item.symbol.set(item.node.drive(c, T));

    if (!view.ringViews.size) {
      for (const indicator of op.perceptual.indicators) {
        const ring = buildRing(indicator);
        view.ringViews.set(indicator.id, ring);
        view.rings.append(ring.root);
      }
    }
    for (const indicator of op.perceptual.indicators) view.ringViews.get(indicator.id)?.set(indicator);

    const states = {
      reflexive: op.reflexive.status,
      perceptual: op.perceptual.conflicts?.length ? "conflict" : op.perceptual.status,
      cognitive: op.cognitive.phase,
    };
    for (const [key, layer] of Object.entries(view.layerViews)) {
      const status = String(states[key]);
      layer.item.dataset.level = LAYER_LEVEL[status] ?? "info";
      layer.item.dataset.busy = String(key === "cognitive" && !["idle", "attention", "off"].includes(status));
      layer.item.title = `${layer.label}: ${status.replaceAll("_", " ")}`;
      put(layer.word, titleCase(status));
    }

    for (const [key, lamp] of Object.entries(view.coreViews)) {
      const status = cores?.cores?.[key];
      lamp.item.dataset.level = { normal: "ok", watch: "warn", alert: "crit" }[status] ?? "off";
      lamp.item.title = status ? `${lamp.label} core: ${status}${cores.world ? "" : " (world stopped)"}` : `${lamp.label} core`;
    }

    const mine = incidents.filter((i) => i.plant_id === plant.spec.id).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const recovered = mine.filter((i) => i.status === "resolved").length;
    view.record.textContent = mine.length
      ? `${mine.length} investigation${mine.length === 1 ? "" : "s"} · ${recovered} recovered · last ${ago(mine[0].created_at)}`
      : "No investigations yet";
  }

  function applyFilter() {
    let shown = 0;
    for (const view of views.values()) {
      const p = view.plant;
      const match = !query || `${p.spec.name} ${p.spec.id} ${p.spec.industry}`.toLowerCase().includes(query);
      view.card.hidden = !match;
      if (match) shown++;
    }
    const empty = $("fl-empty");
    empty.hidden = shown > 0 || (!views.size && !renderedOnce);
    if (!shown) {
      empty.replaceChildren();
      if (!views.size) {
        empty.append(document.createTextNode("No plants yet. "));
        const add = el("a", "ap-link", "Add your first plant");
        add.href = "/assets";
        empty.append(add);
      } else empty.textContent = "No plants match your search.";
    }
    fit();
  }

  function summarise(plants, runs, incidents) {
    const attention = plants.filter((p) => plantCondition(p).level !== "ok").length;
    const live = runs.filter((r) => r.enabled).length;
    $("fl-summary").textContent = [
      `${plants.length} plant${plants.length === 1 ? "" : "s"}`,
      `${live} live`,
      attention ? `${attention} need${attention === 1 ? "s" : ""} attention` : "all within band",
      `${incidents.length} investigation${incidents.length === 1 ? "" : "s"}`,
    ].join(" · ");
  }

  async function tick() {
    clearTimeout(timer);
    if (document.hidden) { timer = setTimeout(tick, POLL_MS); return; }
    try {
      const [plants, runs, incidents, overview] = await Promise.all([api("/api/plants"), api("/api/automation"), api("/api/incidents"), api("/api/cores/overview").catch(() => null)]);
      const operations = await Promise.all(plants.map((p) => api(`/api/plants/${encodeURIComponent(p.spec.id)}/operations`).catch(() => null)));
      $("fl-status").hidden = true;
      const ids = plants.map((p) => `${p.spec.id}:${p.spec.industry}`).join("|");
      if (grid.dataset.ids !== ids) {
        for (const view of views.values()) destroyView(view);
        grid.dataset.ids = ids;
        grid.replaceChildren();
        views.clear();
        plants.forEach((plant, index) => {
          const view = buildCard(plant, index);
          views.set(plant.spec.id, view);
          grid.append(view.card);
        });
      }
      plants.forEach((plant, index) => {
        update(views.get(plant.spec.id), plant, operations[index], runs.find((r) => r.plant_id === plant.spec.id), incidents, overview?.plants?.[plant.spec.id]);
      });
      renderedOnce = true;
      summarise(plants, runs, incidents);
      applyFilter();
    } catch {
      $("fl-status").hidden = false;
    } finally {
      timer = setTimeout(tick, POLL_MS);
    }
  }

  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase();
    applyFilter();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  window.addEventListener("pagehide", () => { clearTimeout(timer); for (const view of views.values()) destroyView(view); });
  return tick();
}
