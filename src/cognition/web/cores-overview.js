// Visual building blocks for the Specialist Faculties overview: animated core illustrations,
// the headline stat strip and the faculty tiles. Pure DOM builders; no data fetching, no writes.
import { badge, chip, el, glyph, icon, svg } from "./cores-parts.js";

const path = (d, cls) => svg("path", { d, class: cls ?? "" });

// ---------- animated illustrations (CSS drives the motion; reduced-motion switches it off) ----------
const ILLUSTRATIONS = {
  // Two slow waveforms on a hairline baseline: the multi-rate signals.
  learning(root) {
    root.append(svg("line", { x1: 20, x2: 140, y1: 45, y2: 45, class: "ill-grid" }));
    const wave = (amp, cls) => {
      let d = "M-40 45";
      for (let x = -40; x < 220; x += 40) d += ` q10 ${-amp} 20 0 t20 0`;
      const g = svg("g", { class: cls });
      g.append(path(d, "ill-line"));
      return g;
    };
    const clip = svg("clipPath", { id: "ill-learning-clip" });
    clip.append(svg("rect", { x: 20, y: 8, width: 120, height: 74 }));
    const body = svg("g", { "clip-path": "url(#ill-learning-clip)" });
    body.append(wave(30, "ill-wave"), wave(14, "ill-wave ill-wave--slow"));
    root.append(clip, body);
  },
  // A camera frame with a lens and one slow scan line.
  vision(root) {
    root.append(svg("rect", { x: 34, y: 16, width: 92, height: 58, rx: 8, class: "ill-line ill-line--soft" }));
    root.append(svg("circle", { cx: 80, cy: 45, r: 14, class: "ill-line" }), svg("circle", { cx: 80, cy: 45, r: 4, class: "ill-dot ill-iris" }));
    root.append(svg("rect", { x: 38, y: 20, width: 84, height: 1.6, rx: 0.8, class: "ill-scan" }));
  },
  // A robot head with a blink and a quiet beacon.
  robot(root) {
    root.append(path("M80 17v9", "ill-line ill-line--soft"), svg("circle", { cx: 80, cy: 14, r: 2.6, class: "ill-dot ill-beacon" }));
    root.append(svg("rect", { x: 56, y: 26, width: 48, height: 38, rx: 10, class: "ill-line" }));
    root.append(svg("circle", { cx: 69, cy: 44, r: 3.2, class: "ill-dot ill-eye" }), svg("circle", { cx: 91, cy: 44, r: 3.2, class: "ill-dot ill-eye" }));
    root.append(path("M72 55h16", "ill-line ill-line--soft"));
  },
  // Three sliders settling towards a target line.
  optimization(root) {
    root.append(path("M96 18v54", "ill-line ill-line--soft ill-target"));
    [[28, "a"], [45, "b"], [62, "c"]].forEach(([y, k]) => {
      root.append(path(`M36 ${y}H124`, "ill-line ill-line--soft"));
      const knob = svg("g", { class: `ill-knob ill-knob--${k}` });
      knob.append(svg("circle", { cx: 64, cy: y, r: 4.6, class: "ill-knob-dot" }));
      root.append(knob);
    });
  },
};

export function illustration(name, level) {
  const root = svg("svg", { viewBox: "0 0 160 90", class: "ill", "aria-hidden": "true", preserveAspectRatio: "xMidYMid meet" });
  root.dataset.level = level;
  root.dataset.core = name;
  ILLUSTRATIONS[name]?.(root);
  return root;
}

// ---------- headline stat strip ----------
const STAT_ICONS = {
  alerts: "M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7ZM10 20a2 2 0 0 0 4 0",
  runs: "M13 3 5 14h6l-1 7 8-11h-6l1-7Z",
  orders: "M9 4h6v3H9ZM7 5H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-1M9 12h6M9 16h4",
  work: "M14 4a5 5 0 0 0-4 7l-6 6 3 3 6-6a5 5 0 0 0 7-4l-3 3-3-1-1-3 3-3a5 5 0 0 0-2-2Z",
};

export function statStrip(stats) {
  const strip = el("div", "ov-stats");
  for (const stat of stats) {
    const tile = el("div", "ov-stat");
    tile.dataset.level = stat.level;
    tile.dataset.live = String(Boolean(stat.live));
    const glyph = svg("svg", { viewBox: "0 0 24 24", class: `ov-stat-icon ov-stat-icon--${stat.id}`, "aria-hidden": "true" });
    glyph.append(path(STAT_ICONS[stat.id]));
    const text = el("div", "ov-stat-text");
    text.append(el("strong", "ov-stat-value", String(stat.value)), el("span", "ov-stat-label", stat.label));
    tile.append(glyph, text);
    if (stat.hint) tile.append(el("span", "ov-stat-hint", stat.hint));
    strip.append(tile);
  }
  return strip;
}

// ---------- faculty tile ----------
const STATUS_TEXT = { ok: "Normal", warn: "Watch", crit: "Alert", info: "Normal", off: "Off" };

// Builds one tile and returns it with an update() that patches text and state in place. The tile is never
// rebuilt on a refresh, so the illustration and the alert glow keep animating without restarting.
export function facultyTile({ name, title, role, level, report, run, onOpen, onStop }) {
  const tile = el("article", "ov-core");
  const art = el("div", "ov-core-art");
  const ill = illustration(name, level);
  art.append(ill);
  const head = el("header", "ov-core-head");
  const text = el("div");
  text.append(el("h3", "", `${title} core`), el("p", "cr-sub", role));
  const status = el("span", "ov-status");
  head.append(icon(name), text, status);
  const summary = el("p", "ov-core-summary");
  const chips = el("div", "cr-chips");
  const foot = el("div", "ov-core-foot");
  tile.append(art, head, summary, chips, foot);
  let runKey = null;

  function update(next) {
    const { level: lv, report: rep, run: current } = next;
    tile.dataset.level = lv;
    ill.dataset.level = lv;
    status.dataset.level = lv;
    status.textContent = STATUS_TEXT[lv] ?? "Normal";
    status.title = `${title} core ${rep.status}`;
    if (summary.textContent !== rep.summary) summary.textContent = rep.summary;
    const chipKey = JSON.stringify([rep.model, rep.alerts.length, rep.degraded, lv]);
    if (chips.dataset.key !== chipKey) {
      chips.dataset.key = chipKey;
      chips.replaceChildren(badge("simulated model", rep.model));
      if (rep.alerts.length) chips.append(chip(`${rep.alerts.length} alert${rep.alerts.length === 1 ? "" : "s"}`, lv));
      if (rep.degraded) chips.append(chip("degraded", "warn", "The agent was unavailable; the reference analyser answered"));
    }
    const key = current ? `${current.id}:${current.kind}` : "idle";
    if (key !== runKey) {
      runKey = key;
      foot.replaceChildren();
      if (current) {
        const live = el("span", "ov-run");
        live.append(glyph("bolt", "cr-glyph ov-run-icon"), document.createTextNode(`Agent ${current.kind} running`));
        const stop = el("button", "cr-btn cr-btn--small cr-btn--danger", "Stop");
        stop.type = "button";
        stop.setAttribute("aria-label", `Stop the ${name} core run`);
        stop.addEventListener("click", onStop);
        foot.append(live, stop);
      } else foot.append(el("span", "ov-run ov-run--idle", "No agent run"));
      if (onOpen) {
        const open = el("button", "cr-btn cr-btn--small cr-btn--quiet", "Open");
        open.type = "button";
        open.setAttribute("aria-label", `Open the ${title} core`);
        open.addEventListener("click", onOpen);
        foot.append(open);
      }
    }
  }

  // The whole tile opens the core with a mouse click. Keyboard users keep the Open button; Stop is left alone.
  if (onOpen) {
    tile.dataset.clickable = "true";
    tile.addEventListener("click", (event) => {
      if (!event.target.closest("button") && !window.getSelection()?.toString()) onOpen();
    });
  }
  update({ level, report, run });
  tile.update = update;
  return tile;
}
