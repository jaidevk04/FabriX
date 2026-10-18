// HMI screens: a plant overview plus one faceplate screen per equipment.
// Display only. Control changes go through the investigation workflow and the gateway, never here.

import { createSymbol, mount, unmount, svgEl } from "./symbols.js";
import { BASIS } from "./plant-signals.js";
import { html, lamp, chip, trendChart, LEVEL_TEXT } from "./hmi-parts.js";
import { createOverview } from "./hmi-overview.js";

// Horizontal bargraph with the display band shaded and an optional setpoint marker.
function bargraph(label) {
  const bar = html("div", "hmi-bar");
  bar.setAttribute("role", "meter");
  bar.setAttribute("aria-label", label);
  bar.append(html("span", "hmi-bar-band"), html("span", "hmi-bar-fill"), html("span", "hmi-bar-mark"));
  return {
    el: bar,
    set(tag, marker) {
      bar.dataset.level = tag.level;
      bar.style.setProperty("--p", String(tag.norm ?? 0));
      bar.style.setProperty("--lo", String(tag.bandNorm?.[0] ?? 0));
      bar.style.setProperty("--hi", String(tag.bandNorm?.[1] ?? 0));
      bar.dataset.band = String(Boolean(tag.bandNorm));
      bar.dataset.empty = String(tag.value === null);
      bar.style.setProperty("--m", String(marker?.norm ?? 0));
      bar.dataset.marker = String(Boolean(marker && marker.norm !== null));
      if (tag.value === null) bar.removeAttribute("aria-valuenow");
      else {
        bar.setAttribute("aria-valuemin", String(tag.min));
        bar.setAttribute("aria-valuemax", String(tag.max));
        bar.setAttribute("aria-valuenow", String(tag.value));
        bar.setAttribute("aria-valuetext", `${tag.text} ${tag.unit}`);
      }
    },
  };
}

function sparkline() {
  const svg = svgEl("svg", { viewBox: "0 0 100 22", class: "hmi-spark", "aria-hidden": "true", preserveAspectRatio: "none" });
  const line = svgEl("polyline", { fill: "none", "vector-effect": "non-scaling-stroke" }, svg);
  return {
    el: svg,
    set(values, tag) {
      const points = values.slice(-40);
      const span = tag.max - tag.min || 1;
      const step = 100 / 39;
      const offset = (40 - points.length) * step;
      const path = [];
      points.forEach((value, i) => {
        if (value === null) return;
        const y = 20 - Math.max(0, Math.min(1, (value - tag.min) / span)) * 18;
        path.push(`${(offset + i * step).toFixed(1)},${y.toFixed(1)}`);
      });
      line.setAttribute("points", path.join(" "));
    },
  };
}

function alarmList(empty) {
  const list = html("ul", "hmi-alarms");
  return {
    el: list,
    set(alarms) {
      list.replaceChildren();
      if (!alarms.length) {
        const item = html("li", "hmi-alarm-empty", empty);
        list.append(item);
        return;
      }
      for (const alarm of alarms) {
        const item = html("li", "hmi-alarm");
        item.dataset.level = alarm.level;
        item.append(lamp(alarm.level), html("span", "hmi-alarm-text", alarm.text), html("time", "", alarm.since ? `since ${alarm.since}` : ""));
        list.append(item);
      }
    },
  };
}

function card(title, className) {
  const section = html("section", `hmi-card ${className ?? ""}`);
  const heading = html("h4", "", title);
  section.append(heading);
  return { el: section, heading };
}

export function createHmi(host, model, { onNavigate, onFlow, onTwin, history }) {
  host.replaceChildren();
  const tabs = html("div", "hmi-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "HMI screens");
  const stage = html("div", "hmi-stage");
  host.append(tabs, stage);

  const screens = new Map();
  const tabButtons = new Map();
  const entries = [{ id: "overview", name: "Plant overview" }, ...model.equipment];
  for (const entry of entries) {
    const button = html("button", "hmi-tab");
    button.type = "button";
    button.id = `hmi-tab-${entry.id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", `hmi-screen-${entry.id}`);
    button.append(lamp("info"), html("span", "", entry.name));
    button.addEventListener("click", () => onNavigate(entry.id));
    tabButtons.set(entry.id, button);
    tabs.append(button);
  }
  tabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const ids = entries.map((entry) => entry.id);
    const at = ids.indexOf(current);
    const next = ids[(at + (event.key === "ArrowRight" ? 1 : ids.length - 1)) % ids.length];
    onNavigate(next);
    tabButtons.get(next).focus();
  });

  let current = "overview";
  let last = null;

  function buildOverview() {
    return createOverview(model, { history, onNavigate });
  }

  function buildEquipment(item) {
    const root = html("article", "hmi-screen");
    root.id = `hmi-screen-${item.id}`;
    root.setAttribute("role", "tabpanel");
    root.setAttribute("aria-labelledby", `hmi-tab-${item.id}`);

    const head = html("header", "hmi-head");
    const title = html("div", "hmi-title");
    title.append(html("span", "hmi-code", item.code), html("h3", "", item.name), html("p", "hmi-role", item.role));
    const status = html("div", "hmi-status");
    const links = html("div", "hmi-links");
    const flowButton = html("button", "secondary", "Process flow");
    const twinButton = html("button", "secondary", "3D twin");
    flowButton.type = twinButton.type = "button";
    flowButton.addEventListener("click", () => onFlow());
    twinButton.addEventListener("click", () => onTwin(item.id));
    links.append(flowButton, twinButton);
    head.append(title, status, links);

    const face = card("Equipment");
    const faceHost = html("div", "hmi-face");
    face.el.append(faceHost);
    const node = model.flow.nodes.find((entry) => entry.id === (item.node ?? item.id));
    const faceSvg = svgEl("svg", { viewBox: `-24 -34 ${node.w + 48} ${node.h + 68}`, class: "hmi-face-svg", role: "img", "aria-label": `${item.name} schematic` }, faceHost);
    const symbol = createSymbol(node);
    faceSvg.append(symbol.g);

    const primary = card("Primary signal", "hmi-primary");
    const pv = html("div", "hmi-pv");
    const pvLabel = html("span", "hmi-pv-label");
    const pvRow = html("div", "hmi-pv-row");
    const pvValue = html("strong", "hmi-pv-value");
    const pvUnit = html("small", "hmi-pv-unit");
    pvRow.append(pvValue, pvUnit);
    const pvBar = bargraph(model.tags[item.primary].label);
    const pvBand = html("p", "hmi-pv-band");
    pv.append(pvLabel, pvRow, pvBar.el, pvBand);
    primary.el.append(pv);

    const trendDef = model.tags[item.primary];
    const trendCard = card(`Trend · ${trendDef.label}`);
    const trend = trendChart({
      series: [{ tag: item.primary, name: trendDef.label, cls: "is-primary" }],
      band: item.primary,
      marker: item.tags.includes("sp") && item.primary === "temp" ? "sp" : null,
      unit: trendDef.unit,
      title: `${trendDef.label} trend`,
    });
    trendCard.el.append(trend.el);

    const signals = card("Signals", "span-2");
    const table = html("table", "hmi-signals");
    const headRow = html("tr");
    for (const label of ["Tag", "Signal", "Value", "Range", "Trend", "Basis"]) headRow.append(html("th", "", label));
    const thead = html("thead");
    thead.append(headRow);
    const tbody = html("tbody");
    const rows = item.tags.map((id) => {
      const def = model.tags[id];
      const row = html("tr");
      const bar = bargraph(def.label);
      const spark = sparkline();
      const cells = ["td", "td", "td", "td", "td", "td"].map(() => html("td"));
      cells[0].className = "pf-code";
      cells[0].textContent = def.code || "—";
      cells[1].textContent = def.label;
      cells[2].className = "pf-num";
      cells[3].append(bar.el);
      cells[4].append(spark.el);
      cells[5].append(chip(BASIS[def.basis]));
      row.append(...cells);
      tbody.append(row);
      return { id, row, cells, bar, spark };
    });
    table.append(thead, tbody);
    const tableWrap = html("div", "table-scroll");
    tableWrap.append(table);
    signals.el.append(tableWrap);

    const alarmCard = card("Alarms for this equipment");
    const alarms = alarmList("No active alarms for this equipment.");
    alarmCard.el.append(alarms.el);

    const notes = card("Basis and limits");
    const authority = html("p", "hmi-note", "Read-only display. Setpoints and duty change only through an approved investigation and the independent gateway.");
    const modelled = html("p", "hmi-note");
    modelled.append(html("strong", "", "Not modelled: "), document.createTextNode(item.notModelled.join("; ") + "."));
    const basisKey = html("p", "hmi-note", "SIM = simulated plant state. EST = derived estimate, not a sensor. CALC = calculated from simulated state. REFLEX = reflexive-layer output.");
    notes.el.append(authority, modelled, basisKey);

    const grid = html("div", "hmi-grid");
    grid.append(face.el, primary.el, trendCard.el, signals.el, alarmCard.el, notes.el);
    root.append(head, grid);

    return {
      root,
      symbol,
      node,
      update({ c, T, activeAlarms, preference }) {
        const state = item.status(c, T);
        status.dataset.level = state.level;
        status.replaceChildren(lamp(state.level), html("strong", "", state.text), html("small", "", LEVEL_TEXT[state.level]));
        if (node.drive) symbol.set(node.drive(c, T));
        const tag = T.get(item.primary);
        pvLabel.textContent = `${tag.label}${tag.code ? ` · ${tag.code}` : ""}`;
        pvValue.textContent = tag.text;
        pvUnit.textContent = tag.value === null ? "" : tag.unit;
        pv.dataset.level = tag.level;
        pvBar.set(tag, item.primary === "temp" ? T.get("sp") : null);
        pvBand.textContent = tag.value === null ? "Signal unavailable. Numeric display is suppressed." : tag.bandText ? `Display band ${tag.bandText}` : "No display band for this signal.";
        trend.update({ values: history.values, clocks: history.clocks, T, preference });
        for (const row of rows) {
          const t = T.get(row.id);
          row.row.dataset.level = t.level;
          row.cells[2].textContent = t.value === null ? "—" : `${t.text} ${t.unit}`;
          row.bar.set(t, null);
          row.spark.set(history.values(row.id), t);
        }
        alarms.set(activeAlarms.filter((alarm) => alarm.tags.some((id) => item.tags.includes(id))));
      },
    };
  }

  function ensure(id) {
    if (screens.has(id)) return screens.get(id);
    const item = model.equipment.find((entry) => entry.id === id);
    const screen = id === "overview" ? buildOverview() : buildEquipment(item);
    screens.set(id, screen);
    stage.append(screen.root);
    return screen;
  }

  function render() {
    if (!last) return;
    const screen = screens.get(current);
    screen?.update(last);
    for (const [id, button] of tabButtons) {
      const item = model.equipment.find((entry) => entry.id === id);
      const level = item ? item.status(last.c, last.T).level : worstOf(model.equipment.map((entry) => entry.status(last.c, last.T).level));
      const dot = button.querySelector(".hmi-lamp");
      dot.dataset.level = level;
    }
  }
  const symbolsOf = (screen) => screen?.symbols ?? (screen?.symbol ? [screen.symbol] : []);
  const rank = { crit: 3, warn: 2, unavail: 1, ok: 0, info: 0 };
  const worstOf = (levels) => levels.reduce((a, b) => (rank[b] > rank[a] ? b : a), "ok");

  function show(id) {
    const target = id === "overview" || model.equipment.some((entry) => entry.id === id) ? id : "overview";
    const previous = screens.get(current);
    for (const symbol of symbolsOf(previous)) unmount(symbol);
    current = target;
    const screen = ensure(target);
    for (const [key, value] of screens) value.root.hidden = key !== target;
    for (const [key, button] of tabButtons) {
      button.setAttribute("aria-selected", String(key === target));
      button.tabIndex = key === target ? 0 : -1;
    }
    for (const symbol of symbolsOf(screen)) mount(symbol);
    render();
  }

  return {
    show,
    current: () => current,
    update(payload) {
      last = payload;
      render();
    },
    destroy() {
      for (const screen of screens.values()) {
        for (const symbol of symbolsOf(screen)) unmount(symbol);
        screen.destroy?.();
      }
      host.replaceChildren();
    },
  };
}
