// Impact page: plant performance, orders and stock, sustainability, the impact ledger, recommendations,
// work orders and incident reports. Read-only except for dismissing or accepting a recommendation
// (which only creates a work order) and cancelling an open work order.
// Every number is simulated; basis badges say so. Live tiles are patched in place so animations keep running.

import { badge, chip, clock, el, glyph, http, lamp, meter, money, number, sparkline, svg, words, ago } from "./cores-parts.js";

const POLL_MS = 2000;
const REC_MS = 5000;
const KIND = {
  repair: ["Repair", "crit", "wrench"], spare_reorder: ["Spare part", "warn", "box"],
  orders_at_risk: ["Orders", "warn", "clock"], energy_saving: ["Energy", "info", "bolt"],
};
const WO_LEVEL = { open: "warn", in_progress: "info", completed: "ok", cancelled: "off" };
const levelOf = (ratio, good = 0.75, ok = 0.4) => (ratio >= good ? "ok" : ratio >= ok ? "warn" : "crit");

export function impactPage({ api }) {
  const host = document.getElementById("impact-host");
  const params = new URLSearchParams(location.search);
  let plants = [];
  let plantId = params.get("plant");
  let timer = null;
  let busy = false;
  let recAt = 0;
  let recs = [];
  let token = 0;
  let deepLink = params.get("report");

  // ---------- helpers ----------
  const card = (cls, title, icon, tag) => {
    const node = el("section", `ix-card ${cls}`);
    const head = el("header", "ix-card-head");
    const left = el("div", "ix-card-title");
    left.append(glyph(icon, "cr-glyph ix-card-icon"), el("h3", "", title));
    head.append(left);
    if (tag) head.append(tag);
    const body = el("div", "ix-card-body");
    node.append(head, body);
    return { node, body, head };
  };
  const gated = (node, signature, build) => {
    if (node.dataset.sig === signature) return;
    node.dataset.sig = signature;
    node.replaceChildren(...build());
  };
  const base = () => `/api/plants/${encodeURIComponent(plantId)}`;
  const say = (text, error = false) => { message.textContent = text; message.dataset.error = String(error); };
  const iconBox = (name, level = "info") => {
    const box = el("span", "ix-icon");
    box.dataset.level = level;
    box.append(glyph(name, "cr-glyph"));
    return box;
  };

  // ---------- skeleton ----------
  const top = el("header", "ix-top");
  const message = el("p", "cr-message");
  message.setAttribute("role", "status");
  const banner = el("p", "cr-banner", "Connection lost. Showing the last values and retrying.");
  banner.hidden = true;

  // Hero: concentric OEE rings + KPI tiles, built once and patched on every poll.
  const hero = el("section", "ix-hero");
  hero.setAttribute("aria-label", "Key indicators");
  const oeeCard = el("article", "ix-oee");
  const RINGS = [["Availability", 74], ["Performance", 58], ["Quality", 42]];
  const ringSvg = svg("svg", { viewBox: "0 0 180 180", class: "ix-rings", role: "img", "aria-label": "OEE with availability, performance and quality rings" });
  const arcs = RINGS.map(([name, r]) => {
    const c = 2 * Math.PI * r;
    ringSvg.append(svg("circle", { cx: 90, cy: 90, r, class: "ix-ring-track" }));
    const arc = svg("circle", { cx: 90, cy: 90, r, class: "ix-ring-arc", "stroke-dasharray": `0 ${c}`, transform: "rotate(-90 90 90)" });
    arc.dataset.ring = name.toLowerCase();
    ringSvg.append(arc);
    return { arc, c };
  });
  const oeeValue = svg("text", { x: 90, y: 94, class: "ix-oee-num", "text-anchor": "middle" }, "—");
  const oeeLabel = svg("text", { x: 90, y: 110, class: "ix-oee-label", "text-anchor": "middle" }, "OEE");
  ringSvg.append(oeeValue, oeeLabel);
  const legend = el("ul", "ix-oee-legend");
  const legendValues = RINGS.map(([name]) => {
    const li = el("li");
    li.dataset.ring = name.toLowerCase();
    const value = el("strong", "", "—");
    li.append(el("i"), el("span", "", name), value);
    legend.append(li);
    return value;
  });
  const oeeSpark = el("div", "ix-oee-spark");
  oeeCard.append(el("p", "ix-label", "Overall equipment effectiveness"), ringSvg, legend, oeeSpark);

  const TILES = [
    ["output", "Good output", "box", "t/h"], ["energy", "Energy cost", "bolt", "/h"], ["co2", "CO2e", "leaf", "kg/h"],
    ["specific", "Specific energy", "flame", "GJ/t"], ["risk", "Orders at risk", "clock", ""], ["downtime", "Downtime", "wrench", "h"],
    ["cost", "Simulated cost", "coin", ""], ["tariff", "Tariff", "chart", "×"],
  ];
  const tileRefs = {};
  const tileGrid = el("div", "ix-tiles");
  for (const [id, label, icon, unit] of TILES) {
    const node = el("article", "ix-tile");
    const head = el("div", "ix-tile-head");
    const box = iconBox(icon);
    head.append(box, el("span", "ix-label", label));
    const value = el("strong", "ix-value", "—");
    const unitNode = el("span", "ix-unit", unit);
    const line = el("div", "ix-value-line");
    line.append(value, unitNode);
    const spark = el("div", "ix-spark");
    const bar = el("div", "ix-tile-bar");
    node.append(head, line, spark, bar);
    tileRefs[id] = { node, box, value, spark, bar };
    tileGrid.append(node);
  }
  hero.append(oeeCard, tileGrid);

  const orders = card("ix-orders", "Orders and stock", "box", badge("SIM", "Simulated orders and stock"));
  const green = card("ix-green", "Sustainability", "leaf", badge("CALC", "Calculated from simulated state with placeholder factors"));
  const ledger = card("ix-ledger", "Impact ledger", "chart", badge("CALC", "Forecast comparison on the twin"));
  const recsCard = card("ix-recs", "Recommendations", "sparkle");
  const work = card("ix-work", "Work orders", "wrench");
  const reportsCard = card("ix-reports", "Incident reports", "report");
  const rowA = el("div", "ix-row ix-row--three");
  rowA.append(orders.node, green.node, ledger.node);
  const rowB = el("div", "ix-row ix-row--recs");
  rowB.append(recsCard.node, el("div", "ix-stack"));
  rowB.lastChild.append(work.node, reportsCard.node);
  const dialog = el("dialog", "im-dialog");
  dialog.setAttribute("aria-labelledby", "im-dialog-title");
  host.replaceChildren(top, banner, message, hero, rowA, rowB, dialog);

  // ---------- hero ----------
  function renderHero(k, history, business) {
    const m = business.metrics;
    const level = levelOf(k.oee);
    oeeCard.dataset.level = level;
    [k.availability, k.performance, k.quality].forEach((v, i) => {
      arcs[i].arc.setAttribute("stroke-dasharray", `${Math.max(0, Math.min(1, v)) * arcs[i].c} ${arcs[i].c}`);
      legendValues[i].textContent = `${Math.round(v * 100)}%`;
    });
    oeeValue.textContent = `${Math.round(k.oee * 100)}%`;
    oeeSpark.replaceChildren(sparkline(history.map((h) => h.oee), { width: 220, height: 34, level }));

    const set = (id, { value, level: lv = "info", series, ratio, title }) => {
      const t = tileRefs[id];
      t.node.dataset.level = lv;
      t.box.dataset.level = lv;
      t.value.textContent = value;
      t.node.title = title ?? "";
      t.spark.replaceChildren(series ? sparkline(series, { width: 150, height: 26, level: lv }) : "");
      t.bar.hidden = ratio === undefined;
      if (ratio !== undefined) t.bar.replaceChildren(meter(ratio, 1, { level: lv }));
    };
    set("output", { value: number(m.good_rate_tph, 1), level: levelOf(m.good_rate_tph / (m.nominal_rate_tph || 1), 0.8, 0.5), ratio: m.good_rate_tph / (m.nominal_rate_tph || 1), title: `Nominal ${m.nominal_rate_tph} t/h` });
    set("energy", { value: money(m.energy_cost_per_h), level: m.tariff_multiplier > 1.2 ? "warn" : "info", series: history.map((h) => h.energy_cost_per_h) });
    set("co2", { value: number(m.co2e_kg_per_h, 0), series: history.map((h) => h.co2e_kg_per_h) });
    set("specific", { value: number(m.specific_energy_gj_per_t, 2), title: "Fuel per good tonne" });
    set("risk", { value: `${k.orders_at_risk}/${k.open_orders}`, level: k.orders_at_risk ? "warn" : "ok" });
    set("downtime", { value: number(k.downtime_hours, 2), level: k.downtime_hours ? "warn" : "ok", title: "Repair downtime so far" });
    set("cost", { value: money(k.simulated_cost), title: "Energy, penalties and maintenance" });
    set("tariff", { value: number(m.tariff_multiplier, 2), level: m.tariff_multiplier > 1.2 ? "warn" : "ok", ratio: Math.min(1, m.tariff_multiplier / 2) });
  }

  // ---------- orders and stock ----------
  const tank = (ratio, level) => {
    const root = svg("svg", { viewBox: "0 0 70 90", class: "ix-tank", role: "img", "aria-label": "Raw material cover" });
    const clipId = `ix-tank-${Math.random().toString(36).slice(2, 7)}`;
    const clip = svg("clipPath", { id: clipId });
    clip.append(svg("rect", { x: 6, y: 6, width: 58, height: 78, rx: 10 }));
    const fillHeight = 78 * Math.max(0.04, Math.min(1, ratio));
    const water = svg("g", { "clip-path": `url(#${clipId})` });
    const body = svg("g", { class: "ix-tank-fill", transform: `translate(0 ${84 - fillHeight})` });
    body.append(svg("rect", { x: 0, y: 4, width: 70, height: 90, class: "ix-tank-water" }));
    body.append(svg("path", { d: "M-40 4 q10 -5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 V14 H-40Z", class: "ix-tank-wave" }));
    water.append(body);
    root.append(clip, water, svg("rect", { x: 6, y: 6, width: 58, height: 78, rx: 10, class: "ix-tank-shell" }));
    root.dataset.level = level;
    return root;
  };

  function renderOrders(business) {
    const { ledger: l, metrics: m } = business;
    gated(orders.body, JSON.stringify([l.orders, l.raw_material_t, l.spares, business.spares_available, m.raw_cover_hours, business.pending_spares]), () => {
      const list = el("ul", "ix-orders-list");
      const open = [...l.orders].filter((o) => o.status !== "fulfilled").sort((a, b) => a.due_sim_seconds - b.due_sim_seconds).slice(0, 5);
      for (const o of open) {
        const hours = (o.due_sim_seconds - business.sim_seconds) / 3600;
        const level = o.status === "late" ? "crit" : hours < 0.5 ? "warn" : "ok";
        const li = el("li", "ix-order");
        li.dataset.level = level;
        const head = el("div", "ix-order-head");
        head.append(el("strong", "", o.id), el("span", "cr-sub", `${number(o.filled_t, 0)} / ${number(o.quantity_t, 0)} t`), chip(o.status === "late" ? "late" : `${number(Math.max(hours, 0), 1)} h`, level, "Time until due"));
        if (o.source !== "baseline") head.append(chip(words(o.source), "info"));
        li.append(head, meter(o.filled_t, o.quantity_t, { level }));
        list.append(li);
      }
      if (!open.length) list.append(el("li", "cr-empty", "No open orders."));
      const cover = m.raw_cover_hours >= 9999 ? null : m.raw_cover_hours;
      const coverLevel = cover === null ? "ok" : cover < 1 ? "crit" : cover < 2 ? "warn" : "ok";
      const raw = el("div", "ix-raw");
      const stock = el("div", "ix-raw-text");
      stock.append(el("span", "ix-label", "Raw material"), el("strong", "ix-value", `${number(l.raw_material_t, 0)} t`), el("span", "cr-sub", cover === null ? "no consumption" : `${number(cover, 1)} h cover`));
      raw.append(tank(cover === null ? 1 : Math.min(cover, 4) / 4, coverLevel), stock);
      const pips = el("div", "ix-spares");
      for (const [part, qty] of Object.entries(l.spares)) {
        const usable = business.spares_available[part] ?? 0;
        const pending = business.pending_spares?.[part];
        const level = usable === 0 ? (pending ? "warn" : "crit") : "ok";
        const pip = el("div", "ix-spare");
        pip.dataset.level = level;
        pip.title = pending ? `In transit: arriving around tick ${pending}` : usable === 0 && qty > 0 ? "Held back by a spare-part shortage" : `Lead time ${business.spare_lead_hours[part]} h`;
        pip.append(iconBox("gear", level), el("span", "ix-spare-name", words(part)), el("strong", "cr-num", `${usable}/${qty}`));
        if (pending) pip.append(chip("ordered", "warn"));
        pips.append(pip);
      }
      return [list, raw, pips];
    });
  }

  // ---------- sustainability ----------
  function renderGreen(business) {
    const m = business.metrics;
    const l = business.ledger;
    gated(green.body, JSON.stringify([m, l.fuel_gj, l.co2e_kg, l.scrap_t]), () => {
      const cells = [
        ["flame", "Fuel", number(m.fuel_gj_per_h, 1), "GJ/h", `${number(l.fuel_gj, 0)} GJ total`],
        ["bolt", "Electricity", number(m.electricity_kw, 0), "kW", `${number(l.electricity_kwh, 0)} kWh total`],
        ["leaf", "CO2e", number(m.co2e_kg_per_h, 0), "kg/h", `${number(l.co2e_kg, 0)} kg total`],
        ["coin", "Energy cost", money(m.energy_cost_per_h), "/h", `${money(l.energy_cost)} total`],
      ];
      const grid = el("div", "ix-green-grid");
      for (const [icon, name, rate, unit, total] of cells) {
        const cell = el("article", "ix-green-cell");
        const line = el("div", "ix-value-line");
        line.append(el("strong", "ix-value", rate), el("span", "ix-unit", unit));
        const text = el("div");
        text.append(el("span", "ix-label", name), line, el("span", "cr-sub", total));
        cell.append(iconBox(icon), text);
        grid.append(cell);
      }
      const scrap = Math.min(1, m.scrap_fraction * 10);
      const gauge = el("div", "ix-scrap");
      const ring = svg("svg", { viewBox: "0 0 60 60", class: "ix-mini-ring", role: "img", "aria-label": "Scrap rate" });
      const circ = 2 * Math.PI * 22;
      ring.append(svg("circle", { cx: 30, cy: 30, r: 22, class: "ix-ring-track" }), svg("circle", { cx: 30, cy: 30, r: 22, class: "ix-ring-arc", "stroke-dasharray": `${scrap * circ} ${circ}`, transform: "rotate(-90 30 30)" }));
      ring.dataset.level = m.scrap_fraction > 0.05 ? "warn" : "ok";
      const text = el("div");
      text.append(el("span", "ix-label", "Scrap rate"), el("strong", "ix-value", `${number(m.scrap_fraction * 100, 1)}%`), el("span", "cr-sub", `${number(l.scrap_t, 1)} t scrapped`));
      const tariff = el("div", "cr-chips");
      tariff.append(chip(`tariff ×${m.tariff_multiplier}`, m.tariff_multiplier > 1.2 ? "warn" : "info"));
      gauge.append(ring, text, tariff);
      return [grid, gauge];
    });
  }

  // ---------- ledger ----------
  function renderLedger(data) {
    const s = data.summary;
    gated(ledger.body, JSON.stringify(data), () => {
      const summary = el("div", "ix-ledger-sum");
      for (const [icon, label, value, unit, level] of [
        ["coin", "Measured", money(s.value), "", s.value >= 0 ? "ok" : "warn"],
        ["sparkle", "Projected gain", money(s.projected_advantage), "", s.projected_advantage >= 0 ? "ok" : "warn"],
        ["clock", "Excursion avoided", String(s.excursion_ticks_avoided), "ticks", "info"],
        ["leaf", "CO2e change", number(s.co2e_kg_delta, 0), "kg", s.co2e_kg_delta <= 0 ? "ok" : "warn"],
      ]) {
        const tile = el("article", "ix-mini");
        tile.dataset.level = level;
        const line = el("div", "ix-value-line");
        line.append(el("strong", "ix-value", value), el("span", "ix-unit", unit));
        const text = el("div");
        text.append(el("span", "ix-label", label), line);
        tile.append(iconBox(icon, level), text);
        summary.append(tile);
      }
      const records = [...data.records].reverse().slice(0, 5);
      const scale = Math.max(1, ...records.flatMap((r) => [Math.abs(r.deltas.value ?? 0), Math.abs(r.projected?.advantage ?? 0)]));
      const list = el("ul", "ix-records");
      for (const r of records) {
        const li = el("li", "ix-record");
        const head = el("div", "ix-record-head");
        head.append(chip(r.outcome, r.outcome === "resolved" ? "ok" : "warn"), el("strong", "", words(r.control)), el("span", "cr-sub", `${r.elapsed_ticks} ticks`));
        const open = el("button", "ix-link", "Report");
        open.type = "button";
        open.addEventListener("click", () => openReport(r.id));
        head.append(open);
        const bars = el("div", "ix-pair");
        const bar = (label, value, cls) => {
          const row = el("div", "ix-pair-row");
          const track = el("span", "ix-pair-track");
          const fill = el("span", `ix-pair-fill ${cls}`);
          fill.dataset.negative = String(value < 0);
          fill.style.setProperty("--w", `${Math.min(100, Math.abs(value) / scale * 100)}%`);
          track.append(fill);
          row.append(el("span", "ix-pair-label", label), track, el("span", "cr-num", money(value)));
          return row;
        };
        if (r.deltas.value !== undefined) bars.append(bar("measured", r.deltas.value, "is-measured"));
        if (r.projected) bars.append(bar("projected", r.projected.advantage, "is-projected"));
        li.append(head, bars);
        list.append(li);
      }
      if (!records.length) list.append(el("li", "cr-empty", "No incident with an action has closed yet."));
      return [summary, list];
    });
  }

  // ---------- recommendations ----------
  function renderRecs() {
    gated(recsCard.body, JSON.stringify(recs.map((r) => [r.id, r.score, r.expected_value, r.blocked])), () => {
      if (!recs.length) {
        const empty = el("div", "ix-empty");
        empty.append(iconBox("check", "ok"), el("strong", "", "Nothing to recommend"), el("span", "cr-sub", "The plant is within band and no repair is indicated."));
        return [empty];
      }
      const grid = el("div", "ix-rec-grid");
      const maxValue = Math.max(...recs.map((x) => x.expected_value), 1);
      for (const r of recs) {
        const [label, level, icon] = KIND[r.kind] ?? [r.kind, "info", "sparkle"];
        const article = el("article", "ix-rec");
        article.dataset.level = level;
        const head = el("header", "ix-rec-head");
        head.append(iconBox(icon, level));
        const title = el("div", "ix-rec-title");
        title.append(el("strong", "", r.title), chip(label, level));
        const score = el("span", "ix-score", r.score.toFixed(2));
        score.title = "Score";
        head.append(title, score);
        const bars = el("div", "ix-rec-bars");
        const value = el("div", "ix-bar-line");
        value.append(el("span", "ix-label", "Value"), meter(Math.max(r.expected_value, 0), maxValue, { level: "ok" }), el("span", "cr-num", money(r.expected_value)));
        const urgency = el("div", "ix-bar-line");
        urgency.append(el("span", "ix-label", "Urgency"), meter(r.urgency, 1, { level: r.urgency > 0.7 ? "crit" : r.urgency > 0.4 ? "warn" : "info" }), el("span", "cr-num", `${Math.round(r.urgency * 100)}%`));
        bars.append(value, urgency);
        const foot = el("footer", "ix-rec-foot");
        const why = el("span", "ix-why", r.rationale);
        why.title = r.rationale;
        foot.append(why);
        const buttons = el("div", "ix-rec-actions");
        if (r.kind === "repair") {
          const accept = el("button", "cr-btn cr-btn--small", "Create work order");
          accept.type = "button";
          accept.addEventListener("click", () => decide(r.id, "accept"));
          buttons.append(accept);
        }
        const dismiss = el("button", "cr-btn cr-btn--small cr-btn--quiet", "Dismiss");
        dismiss.type = "button";
        dismiss.addEventListener("click", () => decide(r.id, "dismiss"));
        buttons.append(dismiss);
        article.append(head, bars);
        if (r.blocked) article.append(chip(r.blocked, "crit"));
        article.append(foot, buttons);
        grid.append(article);
      }
      return [grid];
    });
  }

  async function decide(id, verb) {
    try {
      await http("POST", `/api/recommendations/${encodeURIComponent(id)}/${verb}`);
      say(verb === "accept" ? "Work order created from the recommendation." : "Recommendation dismissed.");
    } catch (error) { say(error.message, true); }
    recAt = 0;
    poll(true);
  }

  // ---------- work orders and reports ----------
  function renderWork(items) {
    gated(work.body, JSON.stringify(items.map((w) => [w.id, w.status])), () => {
      const columns = el("div", "ix-kanban");
      for (const [status, title, icon] of [["open", "Open", "alert"], ["in_progress", "In progress", "gear"], ["completed", "Done", "check"]]) {
        const col = el("div", "ix-col");
        col.dataset.level = WO_LEVEL[status];
        const mine = items.filter((x) => x.status === status);
        const head = el("div", "ix-col-head");
        head.append(glyph(icon, "cr-glyph"), el("span", "", title), el("strong", "ix-count", String(mine.length)));
        col.append(head);
        for (const w of mine.slice(-4).reverse()) {
          const wo = el("article", "ix-wo");
          wo.append(el("strong", "", w.title), el("span", "cr-sub", `${w.part ? words(w.part) : "no part"} · ${w.est_hours} h · ${money(w.est_cost)}`));
          if (status === "open") {
            const cancel = el("button", "ix-link", "Cancel");
            cancel.type = "button";
            cancel.addEventListener("click", async () => {
              try { await http("POST", `/api/work-orders/${w.id}/cancel`); say("Work order cancelled."); } catch (error) { say(error.message, true); }
              poll(true);
            });
            wo.append(cancel);
          }
          col.append(wo);
        }
        if (!mine.length) col.append(el("span", "ix-none", "none"));
        columns.append(col);
      }
      return [columns];
    });
  }

  function renderIncidents(incidents) {
    gated(reportsCard.body, JSON.stringify(incidents.map((i) => [i.id, i.status])), () => {
      const list = el("ul", "ix-incidents");
      for (const i of incidents.slice(0, 5)) {
        const level = { resolved: "ok", escalated: "warn", failed: "crit" }[i.status] ?? "info";
        const li = el("li", "ix-incident");
        li.dataset.level = level;
        const button = el("button", "ix-incident-btn");
        button.type = "button";
        button.setAttribute("aria-label", `Open the ${i.status} incident report`);
        button.append(iconBox(level === "ok" ? "check" : level === "crit" ? "alert" : "report", level), el("span", "ix-incident-text", i.reason.slice(0, 70)), chip(i.status, level), el("time", "cr-time", ago(i.created_at)));
        button.addEventListener("click", () => openReport(i.id));
        li.append(button);
        list.append(li);
      }
      if (!incidents.length) list.append(el("li", "cr-empty", "No incidents for this plant yet."));
      return [list];
    });
  }

  async function openReport(id) {
    try {
      const r = await http("GET", `/api/incidents/${id}/report`);
      const title = el("h3", "", r.title);
      title.id = "im-dialog-title";
      const head = el("header", "im-dialog-head");
      const close = el("button", "cr-btn cr-btn--small", "Close");
      close.type = "button";
      close.addEventListener("click", () => dialog.close());
      const download = el("a", "cr-btn cr-btn--small cr-btn--quiet", "Markdown");
      download.href = `/api/incidents/${id}/report?format=markdown`;
      download.target = "_blank";
      download.rel = "noopener";
      head.append(title, chip(r.incident.status, r.incident.status === "resolved" ? "ok" : "warn"), download, close);
      const body = el("div", "im-dialog-body");
      if (r.decision) {
        body.append(el("h4", "cr-mini", "Decision"), el("p", "", r.decision.summary));
        const evidence = el("ul", "im-evidence");
        for (const line of r.evidence) evidence.append(el("li", "", line));
        body.append(evidence);
      }
      const story = el("ol", "cr-timeline im-story");
      for (const step of r.story) {
        const li = el("li", "cr-event");
        li.dataset.level = /refused|failed/.test(step.kind) ? "crit" : /cleared|completed|receipt|verified|recorded/.test(step.kind) ? "ok" : "info";
        li.append(lamp(li.dataset.level), el("time", "cr-time", clock(step.time)), el("span", "cr-event-text", step.text));
        story.append(li);
      }
      body.append(el("h4", "cr-mini", "Story"), story);
      const timings = Object.entries(r.timings).filter(([key, value]) => key.endsWith("_s") && value !== null);
      if (timings.length) {
        const chips = el("div", "cr-chips");
        for (const [key, value] of timings) chips.append(chip(`${words(key.replace(/_s$/, ""))}: ${value} s`, "info"));
        body.append(el("h4", "cr-mini", "Timings (simulated)"), chips);
      }
      body.append(el("p", "cr-note", r.basis));
      dialog.replaceChildren(head, body);
      dialog.showModal();
    } catch (error) { say(error.message, true); }
  }

  // ---------- polling ----------
  async function loadRecs(force) {
    if (!force && performance.now() - recAt < REC_MS) return;
    recAt = performance.now();
    recs = await http("GET", `${base()}/recommendations`);
  }

  async function poll(immediate = false) {
    clearTimeout(timer);
    if (document.hidden && !immediate) { timer = setTimeout(poll, POLL_MS); return; }
    if (busy) return;
    busy = true;
    const mine = ++token;
    try {
      if (!plants.length) {
        plants = await api("/api/plants");
        let stored = null;
        try { stored = localStorage.getItem("fabrix.plant"); } catch { /* storage unavailable */ }
        const known = (id) => plants.find((p) => p.spec.id === id)?.spec.id;
        plantId = known(plantId) ?? known(stored) ?? plants[0]?.spec.id ?? null;
      }
      if (!plantId) { say("No plants yet. Add one first."); return; }
      const [k, history, business, impact, workOrders, incidents, world] = await Promise.all([
        http("GET", `${base()}/kpis`), http("GET", `${base()}/kpis/history?limit=120`), http("GET", `${base()}/business`),
        http("GET", `${base()}/impact`), http("GET", `${base()}/work-orders`), api("/api/incidents"), http("GET", `${base()}/world`),
      ]);
      await loadRecs(false);
      if (mine !== token) return;
      banner.hidden = true;
      const name = plants.find((p) => p.spec.id === plantId)?.spec.name ?? plantId;
      const pill = el("span", "cr-pill", world.running ? `World running · tick ${world.tick}` : `World stopped · tick ${world.tick}`);
      pill.dataset.level = world.running ? "ok" : "off";
      top.replaceChildren(chip(name, "info"), pill, badge("SIM", "All values are simulated. Prices and emission factors are placeholders."));
      renderHero(k, history, business);
      renderOrders(business);
      renderGreen(business);
      renderLedger(impact);
      renderRecs();
      renderWork(workOrders);
      renderIncidents(incidents.filter((i) => i.plant_id === plantId).sort((a, b) => new Date(b.created_at) - new Date(a.created_at)));
      if (deepLink) { const id = deepLink; deepLink = null; openReport(id); }
    } catch {
      banner.hidden = false;
    } finally {
      busy = false;
      timer = setTimeout(poll, POLL_MS);
    }
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
  return poll(true);
}
