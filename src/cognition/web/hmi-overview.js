// HMI plant overview: an instrument cluster, live trends, an equipment rail with animated symbols,
// an attention feed and the process indicators. Display only; opening equipment is navigation, not control.

import { createSymbol, svgEl } from "./symbols.js";
import { BASIS, convert } from "./plant-signals.js";
import { html, trendChart } from "./hmi-parts.js";
import { ownerOf } from "./process-flow.js";

const ICON = {
  reflexive: "M12 3 4.5 6v5.5c0 4.2 2.9 7.3 7.5 9 4.6-1.7 7.5-4.8 7.5-9V6L12 3Z M8.6 12.2l2.5 2.5 4.4-5",
  perceptual: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z M12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6Z",
  cognitive: "M8.2 11.3l7.6-4.1 M8.2 12.7l7.6 4.1 M6 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z M18 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z M18 14a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  warn: "M12 3.5 2.8 19.5h18.4L12 3.5Z M12 10v4.4 M12 17.1v.1",
  crit: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z M12 7.5v5.2 M12 15.9v.1",
  check: "M5 12.5l4.6 4.6L19 7.4",
};
const LAYER_LEVEL = { regulating: "ok", blocked: "warn", interlocked: "crit", nominal: "ok", normal: "ok", conflict: "warn", anomaly: "warn", attention: "warn", idle: "info" };
const IDLE_PHASES = ["idle", "attention", "off"];

function icon(name, className = "ov-ico") {
  const svg = svgEl("svg", { viewBox: "0 0 24 24", class: className, "aria-hidden": "true" });
  svgEl("path", { d: ICON[name] }, svg);
  return svg;
}
const titleCase = (text) => String(text).replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
const sign = (value) => (value > 0 ? "+" : "");

// Symbols are drawn in model coordinates. These boxes frame each one for the small equipment rail:
// long conveyors are cropped, and flames get room to burn.
const ART = {
  hopper: [-6, -6, 122, 112],
  kiln: [-22, -12, 444, 94],
  motor: [-4, -4, 88, 132],
  burner: [-100, -8, 262, 52],
  furnace: [-6, -6, 512, 162],
  burnerbank: [-6, -6, 412, 124],
  rollers: [0, -6, 250, 38],
  billets: [0, -4, 250, 32],
  vessel: [-6, 0, 270, 310],
  agitator: [0, -4, 120, 224],
  valve: [-6, -6, 52, 52],
  pump: [-6, -6, 52, 52],
  heater: [-4, -4, 98, 148],
};

// ---- temperature dial ----
const D = { cx: 130, cy: 126, r: 92, start: -120, sweep: 240 };
const polar = (deg, r = D.r) => {
  const a = (deg * Math.PI) / 180;
  return [D.cx + r * Math.sin(a), D.cy - r * Math.cos(a)];
};
function arcPath(r) {
  const [x1, y1] = polar(D.start, r);
  const [x2, y2] = polar(D.start + D.sweep, r);
  return `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 1 1 ${x2.toFixed(2)},${y2.toFixed(2)}`;
}

function buildDial() {
  const svg = svgEl("svg", { viewBox: "0 0 260 208", class: "ov-dial-svg", role: "img" });
  svgEl("path", { d: arcPath(D.r), class: "ov-dial-track", pathLength: 100 }, svg);
  const band = svgEl("path", { d: arcPath(D.r), class: "ov-dial-band", pathLength: 100 }, svg);
  const ticks = svgEl("g", { class: "ov-dial-ticks" }, svg);
  for (let i = 0; i <= 20; i++) {
    const deg = D.start + (i * D.sweep) / 20;
    const major = i % 5 === 0;
    const [x1, y1] = polar(deg, D.r + 12);
    const [x2, y2] = polar(deg, D.r + (major ? 21 : 16));
    svgEl("line", { x1: x1.toFixed(1), y1: y1.toFixed(1), x2: x2.toFixed(1), y2: y2.toFixed(1), class: major ? "is-major" : "" }, ticks);
  }
  const value = svgEl("path", { d: arcPath(D.r), class: "ov-dial-value", pathLength: 100 }, svg);
  const setpoint = svgEl("g", { class: "ov-dial-rot ov-dial-sp" }, svg);
  svgEl("line", { x1: D.cx, x2: D.cx, y1: D.cy - D.r - 13, y2: D.cy - D.r + 13 }, setpoint);
  const knob = svgEl("g", { class: "ov-dial-rot ov-dial-knob" }, svg);
  svgEl("circle", { cx: D.cx, cy: D.cy - D.r, r: 9, class: "ov-dial-ping" }, knob);
  svgEl("circle", { cx: D.cx, cy: D.cy - D.r, r: 9, class: "ov-dial-dot" }, knob);
  svgEl("circle", { cx: D.cx, cy: D.cy - D.r, r: 3, class: "ov-dial-core" }, knob);
  const number = svgEl("text", { x: D.cx, y: D.cy + 14, "text-anchor": "middle", class: "ov-dial-number" }, svg);
  const unit = svgEl("text", { x: D.cx, y: D.cy + 38, "text-anchor": "middle", class: "ov-dial-unit" }, svg);
  const [lx, ly] = polar(D.start, D.r);
  const [rx, ry] = polar(D.start + D.sweep, D.r);
  const min = svgEl("text", { x: lx, y: ly + 24, "text-anchor": "middle", class: "ov-dial-end" }, svg);
  const max = svgEl("text", { x: rx, y: ry + 24, "text-anchor": "middle", class: "ov-dial-end" }, svg);
  const turn = (node, norm) => { node.style.transform = `rotate(${(D.start + D.sweep * norm).toFixed(1)}deg)`; };
  return {
    el: svg,
    set(tag, sp, preference) {
      const empty = tag.value === null;
      svg.dataset.empty = String(empty);
      const norm = tag.norm ?? 0;
      value.style.strokeDasharray = `${(norm * 100).toFixed(2)} 200`;
      turn(knob, norm);
      if (sp.norm === null) setpoint.style.display = "none";
      else { setpoint.style.display = ""; turn(setpoint, sp.norm); }
      if (tag.bandNorm) {
        const [lo, hi] = tag.bandNorm;
        band.style.strokeDasharray = `0 ${(lo * 100).toFixed(2)} ${((hi - lo) * 100).toFixed(2)} 200`;
        band.style.display = "";
      } else band.style.display = "none";
      number.textContent = tag.text;
      unit.textContent = empty ? "Signal unavailable" : tag.unit;
      const shown = (v) => convert(v, tag.def.unit, preference).value.toLocaleString(undefined, { maximumFractionDigits: 0 });
      min.textContent = shown(tag.min);
      max.textContent = shown(tag.max);
      svg.setAttribute("aria-label", empty ? `${tag.label}: signal unavailable` : `${tag.label} ${tag.text} ${tag.unit}, setpoint ${sp.text} ${sp.unit}`);
    },
  };
}

// ---- command and actuator response ----
function buildCommand() {
  const root = html("div", "ov-cmd");
  const flame = svgEl("svg", { viewBox: "0 0 24 32", class: "ov-flame", "aria-hidden": "true" });
  svgEl("path", { d: "M12 2c1 5 7 8 7 15a7 7 0 0 1-14 0c0-3 1.5-5 3-6.5.3 2 1.2 3 2.2 3.5C9.5 9 10 5 12 2Z", class: "ov-flame-body" }, flame);
  svgEl("path", { d: "M12 17c.7 2 3 3 3 5.5a3 3 0 0 1-6 0c0-1.6 1-2.6 1.8-3.4.2.8.6 1.3 1.2 1.5-.2-1.4 0-2.6 0-3.6Z", class: "ov-flame-core" }, flame);
  const body = html("div", "ov-cmd-body");
  const rowA = html("div", "ov-cmd-row");
  const duty = html("strong");
  rowA.append(html("span", "", "Commanded duty"), duty);
  const track = html("div", "ov-track");
  const fill = html("span", "ov-track-fill");
  const gap = html("span", "ov-track-gap");
  const mark = html("span", "ov-track-mark");
  track.append(fill, gap, mark);
  const rowB = html("div", "ov-cmd-row");
  const actuator = html("strong");
  rowB.append(html("span", "", "Actuator position"), actuator);
  const note = html("p", "ov-cmd-note");
  body.append(rowA, track, rowB, note);
  root.append(flame, body);
  return {
    el: root,
    set(T, status) {
      const d = T.get("duty");
      const a = T.get("act");
      duty.textContent = d.value === null ? "—" : `${d.text} ${d.unit}`;
      actuator.textContent = a.value === null ? "—" : `${a.text} ${a.unit}`;
      const dv = d.value ?? 0;
      const av = a.value ?? 0;
      root.style.setProperty("--a", String(Math.max(0, Math.min(1, av / 100))));
      track.style.setProperty("--d", `${Math.max(0, Math.min(100, dv))}%`);
      track.style.setProperty("--av", `${Math.max(0, Math.min(100, av))}%`);
      track.style.setProperty("--g0", `${Math.min(dv, av)}%`);
      track.style.setProperty("--g1", `${Math.abs(dv - av)}%`);
      track.dataset.gap = String(Math.abs(dv - av) > 1);
      root.dataset.level = status.level;
      note.textContent = status.text;
    },
  };
}

// ---- layer chain in the ribbon ----
function buildLayers() {
  const list = html("ol", "ov-chain");
  list.setAttribute("aria-label", "Automation layers");
  const items = {};
  [["reflexive", "Reflexive"], ["perceptual", "Perceptual"], ["cognitive", "Cognitive"]].forEach(([key, label], index) => {
    if (index) list.append(html("li", "ov-link"));
    const item = html("li", "ov-layer");
    const ring = html("span", "ov-layer-ico");
    ring.append(icon(key));
    const text = html("span", "ov-layer-text");
    const word = html("strong");
    text.append(html("small", "", label), word);
    item.append(ring, text);
    list.append(item);
    items[key] = { item, word };
  });
  list.querySelectorAll(".ov-link").forEach((node) => node.setAttribute("aria-hidden", "true"));
  return { el: list, items };
}

export function createOverview(model, { history, onNavigate }) {
  const root = html("article", "hmi-screen hmi-screen--overview ov");
  root.id = "hmi-screen-overview";
  root.setAttribute("role", "tabpanel");
  root.setAttribute("aria-labelledby", "hmi-tab-overview");

  // Ribbon: plant state, simulator facts and the three automation layers.
  const ribbon = html("header", "ov-ribbon");
  const headline = html("div", "ov-headline");
  const beacon = html("span", "ov-beacon");
  beacon.setAttribute("aria-hidden", "true");
  const headText = html("div", "ov-head-text");
  const stateText = html("strong");
  const facts = html("dl", "ov-facts");
  const factValues = {};
  for (const key of ["Mode", "Signal", "Simulator", "Revision"]) {
    const cell = html("div");
    const value = html("dd");
    cell.append(html("dt", "", key), value);
    facts.append(cell);
    factValues[key] = value;
  }
  headText.append(stateText, facts);
  beacon.title = model.title;
  headline.append(beacon, headText);
  const layers = buildLayers();
  ribbon.append(headline, layers.el);

  // Instrument cluster: dial and command response.
  const cluster = html("section", "ov-cluster");
  cluster.setAttribute("aria-label", "Process temperature and control response");
  const clusterHead = html("header", "ov-cluster-head");
  const clusterTitle = html("h4");
  const tempBasis = model.tags.temp.basis;
  const tempChip = html("span", "ov-chip", BASIS[tempBasis].code);
  tempChip.title = BASIS[tempBasis].name;
  clusterHead.append(clusterTitle, tempChip);
  const dial = buildDial();
  const reading = html("div", "ov-reading");
  const spValue = html("strong");
  const devValue = html("strong");
  const spCell = html("div");
  spCell.append(html("span", "", "Setpoint"), spValue);
  const devCell = html("div");
  devCell.append(html("span", "", "Deviation"), devValue);
  reading.append(spCell, devCell);
  const dialKey = html("p", "ov-dial-key");
  dialKey.append(html("i", "is-band"), document.createTextNode("Recovery band"), html("i", "is-sp"), document.createTextNode("Setpoint"));
  const command = buildCommand();
  cluster.append(clusterHead, dial.el, reading, dialKey, command.el);

  // Trends.
  const trends = html("section", "ov-trends");
  trends.setAttribute("aria-label", "Live trends");
  const tempTrend = trendChart({
    series: [{ tag: "temp", name: "Measured", cls: "is-primary" }],
    band: "temp", marker: "sp", unit: "°C", title: "Process temperature trend with recovery band", height: 200, fit: "fill",
  });
  const ctlTrend = trendChart({
    series: [{ tag: "duty", name: "Commanded duty", cls: "is-primary" }, { tag: "act", name: "Actuator position", cls: "is-secondary" }],
    band: "act", unit: "%", title: "Commanded duty and actuator position", height: 130, fit: "fill",
  });
  const tempHead = html("header", "ov-section-head");
  const tempTitle = html("h4", "", "Process temperature");
  tempHead.append(tempTitle);
  const ctlHead = html("header", "ov-section-head");
  ctlHead.append(html("h4", "", "Command and response"));
  trends.append(tempHead, tempTrend.el, ctlHead, ctlTrend.el);

  // Equipment rail with live symbols.
  const equipment = html("section", "ov-equipment");
  const eqHead = html("header", "ov-section-head");
  eqHead.append(html("h4", "", "Equipment"), html("small", "", "Open a screen"));
  const eqList = html("ul", "ov-eq");
  const symbols = [];
  const rows = model.equipment.map((item) => {
    const node = model.flow.nodes.find((entry) => entry.eq === item.id) ?? model.flow.nodes.find((entry) => entry.id === item.node);
    const box = ART[node.kind] ?? [0, 0, node.w, node.h];
    const art = svgEl("svg", { viewBox: box.join(" "), class: "ov-eq-art", "aria-hidden": "true", preserveAspectRatio: "xMidYMid meet" });
    const symbol = createSymbol(node);
    art.append(symbol.g);
    symbols.push(symbol);
    const li = html("li");
    const button = html("button", "ov-eq-row");
    button.type = "button";
    const name = html("strong", "ov-eq-name", item.name);
    const status = html("span", "ov-eq-status");
    const value = html("span", "ov-eq-value");
    const number = html("b");
    const unit = html("small");
    value.append(number, document.createTextNode(" "), unit);
    button.append(art, name, value, status);
    button.addEventListener("click", () => onNavigate(item.id));
    li.append(button);
    eqList.append(li);
    return { item, node, symbol, button, status, number, unit };
  });
  equipment.append(eqHead, eqList);

  // Attention feed: active alarms first, then recent transitions.
  const feed = html("section", "ov-feed");
  const feedHead = html("header", "ov-section-head");
  const count = html("span", "ov-count");
  feedHead.append(html("h4", "", "Alarms and events"), count);
  const clear = html("div", "ov-clear");
  const check = svgEl("svg", { viewBox: "0 0 48 48", class: "ov-clear-art", "aria-hidden": "true" });
  svgEl("circle", { cx: 24, cy: 24, r: 20, class: "ov-clear-ring" }, check);
  svgEl("path", { d: "M14 25l7 7 13-15", class: "ov-clear-tick" }, check);
  const clearText = html("div");
  clearText.append(html("strong", "", "All clear"), html("small", "", "No active alarms"));
  clear.append(check, clearText);
  const alerts = html("ul", "ov-alerts");
  const timeline = html("ol", "ov-timeline");
  const timelineHead = html("p", "ov-subhead", "Recent");
  feed.append(feedHead, clear, alerts, timelineHead, timeline);

  // Process indicators (estimates).
  const indicatorIds = Object.entries(model.tags).filter(([, def]) => def.basis === "est").map(([id]) => id);
  const strip = html("section", "ov-indicators");
  strip.setAttribute("aria-label", "Process indicators");
  const stripHead = html("header", "ov-strip-head");
  const estChip = html("span", "ov-chip", BASIS.est.code);
  estChip.title = `${BASIS.est.name}. Derived estimates, not sensor readings.`;
  const stripTitle = html("div", "ov-strip-title");
  stripTitle.append(html("h4", "", "Process indicators"), estChip);
  stripHead.append(stripTitle, html("small", "", "Derived estimates"));
  const tiles = html("ul", "ov-tiles");
  const indicatorViews = indicatorIds.map((id) => {
    const li = html("li");
    const button = html("button", "ov-tile");
    button.type = "button";
    const ring = svgEl("svg", { viewBox: "0 0 44 44", class: "ov-ring", "aria-hidden": "true" });
    svgEl("circle", { cx: 22, cy: 22, r: 17, class: "ov-ring-track", pathLength: 100 }, ring);
    const bandArc = svgEl("circle", { cx: 22, cy: 22, r: 17, class: "ov-ring-band", pathLength: 100 }, ring);
    const arc = svgEl("circle", { cx: 22, cy: 22, r: 17, class: "ov-ring-value", pathLength: 100 }, ring);
    svgEl("circle", { cx: 22, cy: 22, r: 3, class: "ov-ring-core" }, ring);
    const text = html("span", "ov-tile-text");
    const label = html("small");
    const value = html("strong");
    text.append(label, value);
    button.append(ring, text);
    button.title = model.tags[id].label;
    const owner = ownerOf(model, id);
    button.addEventListener("click", () => owner && onNavigate(owner.id));
    li.append(button);
    tiles.append(li);
    return { id, button, bandArc, arc, label, value };
  });
  strip.append(stripHead, tiles);

  root.append(ribbon, cluster, trends, equipment, strip, feed);

  return {
    root,
    symbols,
    destroy() {
      tempTrend.destroy();
      ctlTrend.destroy();
    },
    update({ c, T, activeAlarms, events, preference }) {
      // Ribbon
      const overall = model.equipment[0].status(c, T);
      beacon.dataset.level = overall.level;
      ribbon.dataset.level = overall.level;
      stateText.textContent = overall.text;
      factValues.Mode.textContent = c.state.mode === "automatic" ? "Automatic" : "Manual";
      factValues.Signal.textContent = c.state.quality === "good" ? "Valid" : "Invalid";
      factValues.Signal.dataset.level = c.state.quality === "good" ? "ok" : "crit";
      factValues.Simulator.textContent = c.time.simulated_clock;
      factValues.Simulator.dataset.live = String(Boolean(c.time.advancing));
      factValues.Simulator.title = c.time.advancing ? "Simulator advancing" : "Simulator stopped";
      factValues.Revision.textContent = `r${c.state.revision}`;
      factValues.Revision.title = `Tick ${c.time.tick}`;
      layers.el.dataset.live = String(Boolean(c.time.advancing));
      const layerStatus = {
        reflexive: c.reflexive.status,
        perceptual: c.perceptual.conflicts?.length ? "conflict" : c.perceptual.status,
        cognitive: c.cognitive.phase,
      };
      for (const [key, view] of Object.entries(layers.items)) {
        const status = String(layerStatus[key]);
        view.item.dataset.level = LAYER_LEVEL[status] ?? "info";
        view.item.dataset.busy = String(key === "cognitive" && !IDLE_PHASES.includes(status));
        view.word.textContent = titleCase(status);
      }

      // Cluster
      const temp = T.get("temp");
      const sp = T.get("sp");
      const dev = T.get("dev");
      clusterTitle.textContent = temp.label;
      tempTitle.textContent = `${temp.label} trend`;
      cluster.dataset.level = temp.level;
      dial.set(temp, sp, preference);
      spValue.textContent = `${sp.text} ${sp.unit}`;
      devValue.textContent = dev.value === null ? "—" : `${sign(dev.value)}${dev.text} ${dev.unit}`;
      devCell.dataset.level = dev.level;
      const actor = model.equipment.find((entry) => entry.primary === "act");
      command.set(T, actor ? actor.status(c, T) : { level: "info", text: "" });

      // Trends
      tempTrend.update({ values: history.values, clocks: history.clocks, T, preference });
      ctlTrend.update({ values: history.values, clocks: history.clocks, T, preference });

      // Equipment rail
      for (const row of rows) {
        const status = row.item.status(c, T);
        const primary = T.get(row.item.primary);
        row.button.dataset.level = status.level;
        row.status.textContent = status.text;
        row.status.title = status.text;
        row.number.textContent = primary.value === null ? "—" : primary.text;
        row.unit.textContent = primary.value === null ? "" : primary.unit;
        row.button.setAttribute("aria-label", `${row.item.name}: ${status.text}. ${primary.label} ${primary.value === null ? "unavailable" : `${primary.text} ${primary.unit}`}. Open screen.`);
        if (row.node.drive) row.symbol.set(row.node.drive(c, T));
      }

      // Feed
      const total = activeAlarms.length;
      count.textContent = total ? String(total) : "";
      count.dataset.level = activeAlarms.some((alarm) => alarm.level === "crit") ? "crit" : "warn";
      count.hidden = !total;
      clear.hidden = total > 0;
      alerts.replaceChildren();
      for (const alarm of activeAlarms) {
        const li = html("li", "ov-alert");
        li.dataset.level = alarm.level;
        const text = html("span", "ov-alert-text", alarm.text);
        li.append(icon(alarm.level === "crit" ? "crit" : "warn", "ov-alert-ico"), text, html("time", "", alarm.since ? `since ${alarm.since}` : ""));
        alerts.append(li);
      }
      timeline.replaceChildren();
      const recent = events.slice(0, 5);
      timelineHead.hidden = !recent.length;
      for (const event of recent) {
        const li = html("li");
        li.dataset.level = event.level;
        li.append(html("time", "", event.clock), html("span", "", `${event.kind === "raised" ? "Raised" : "Cleared"}: ${event.text}`));
        timeline.append(li);
      }

      // Indicators
      for (const view of indicatorViews) {
        const tag = T.get(view.id);
        view.button.dataset.level = tag.level;
        view.label.textContent = tag.label;
        view.value.textContent = tag.value === null ? "—" : `${tag.text} ${tag.unit}`;
        view.arc.style.strokeDasharray = `${((tag.norm ?? 0) * 100).toFixed(2)} 200`;
        view.arc.style.display = tag.value === null ? "none" : "";
        if (tag.bandNorm) {
          const [lo, hi] = tag.bandNorm;
          view.bandArc.style.strokeDasharray = `0 ${(lo * 100).toFixed(2)} ${((hi - lo) * 100).toFixed(2)} 200`;
          view.bandArc.style.display = "";
        } else view.bandArc.style.display = "none";
      }
    },
  };
}
