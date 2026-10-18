// Optimization core workspace: twin-search results as a recommendation card, diverging change charts against
// "do nothing", the trade-offs, and the repair-window plan. Forecasts only; nothing here writes to a plant.
import { badge, chip, el, glyph, http, number, svg, words } from "./cores-parts.js";

const REFRESH_MS = 4500;
const GOALS = [
  ["recovery", "Recovery"], ["energy", "Energy"], ["co2e", "CO2e"],
  ["scrap", "Scrap"], ["due_date", "Due dates"], ["balanced", "Balanced"],
];
const GOAL_NAME = Object.fromEntries(GOALS);
const METRICS = [
  { key: "fuel_gj_per_h", label: "Fuel", unit: "GJ/h", digits: 2 },
  { key: "co2e_kg_per_h", label: "CO2e", unit: "kg/h", digits: 0 },
  { key: "scrap_fraction", label: "Scrap", unit: "", digits: 3 },
];

export function createOptimizationView({ base }) {
  const root = el("div", "ox");
  let goal = "balanced";
  let loadedAt = 0;
  let loading = false;
  let generation = 0;
  let lastData = null;
  let lastPlan = null;

  // ---------- skeleton ----------
  const head = el("header", "ox-head");
  const headText = el("div");
  headText.append(el("h3", "", "Optimization"), el("p", "cr-sub", "Candidate duty values searched on a copy of the plant. Forecasts only."));
  const headChips = el("div", "ox-head-chips");
  head.append(headText, headChips);
  const goalBar = el("div", "cr-segment ox-goals");
  goalBar.setAttribute("role", "radiogroup");
  goalBar.setAttribute("aria-label", "Optimization goal");
  for (const [id, label] of GOALS) {
    const button = el("button", "", label);
    button.type = "button";
    button.setAttribute("role", "radio");
    button.dataset.goal = id;
    button.addEventListener("click", () => { goal = id; syncGoals(); load(true); });
    goalBar.append(button);
  }
  const syncGoals = () => goalBar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.goal === goal)));
  syncGoals();
  const main = el("div", "ox-main");
  const heroCard = el("section", "ox-card ox-hero");
  const chartCard = el("section", "ox-card ox-charts");
  main.append(heroCard, chartCard);
  const tradeHost = el("div", "ox-trades");
  const planCard = el("section", "ox-card");
  root.append(head, goalBar, main, tradeHost, planCard);

  // ---------- pieces ----------
  const cardHead = (title, extra) => {
    const row = el("div", "ox-card-head");
    row.append(el("h4", "cr-mini", title));
    if (extra) row.append(extra);
    return row;
  };
  const empty = (iconName, title, text) => {
    const box = el("div", "ox-empty");
    box.append(glyph(iconName, "cr-glyph ox-empty-icon"), el("strong", "", title), el("span", "cr-sub", text));
    return box;
  };

  function delta(value, ref, digits, unit) {
    const d = value - ref;
    const text = Math.abs(d) < 10 ** -digits / 2 ? "no change" : `${d > 0 ? "+" : "−"}${number(Math.abs(d), digits)}${unit ? ` ${unit}` : ""}`;
    return { d, text, level: Math.abs(d) < 10 ** -digits / 2 ? "off" : d < 0 ? "ok" : "warn" };
  }

  function renderHero(data) {
    const best = data.best;
    const title = cardHead("Recommended", chip(GOAL_NAME[data.goal] ?? words(data.goal), "info"));
    if (!best) {
      heroCard.replaceChildren(title, empty("target", "No safe candidate", "Nothing in range recovers safely. The plant stays as it is."));
      return;
    }
    const value = el("div", "ox-hero-value");
    value.append(el("strong", "", number(best.value, 1)), el("span", "", "% duty"));
    const now = el("div", "ox-hero-now");
    now.append(glyph("bolt", "cr-glyph"), document.createTextNode(`Now ${number(data.reference.value, 1)}% · change ${best.value - data.reference.value >= 0 ? "+" : "−"}${number(Math.abs(best.value - data.reference.value), 1)} points`));
    const rows = el("div", "ox-hero-rows");
    for (const m of METRICS) {
      const d = delta(best[m.key], data.reference[m.key], m.digits, m.unit);
      const row = el("div", "ox-hero-row");
      row.dataset.level = d.level;
      row.append(el("span", "ox-hero-label", m.label), el("strong", "cr-num", number(best[m.key], m.digits)), el("span", "ox-delta", d.text));
      rows.append(row);
    }
    const foot = el("div", "cr-chips");
    foot.append(
      chip(best.executable ? "Gateway would accept" : "Not executable", best.executable ? "ok" : "warn", best.executable ? "Recovers safely and beats doing nothing" : "Does not recover safely or does not beat doing nothing"),
      chip(best.recovery_ticks === null ? "no recovery" : `recovers in ${best.recovery_ticks} ticks`, best.recovery_ticks === null ? "warn" : "info"),
    );
    heroCard.replaceChildren(title, value, now, rows, foot, el("p", "cr-note", "Advisory. Any action goes through the main proposal flow and the Gateway."));
  }

  // One diverging bar chart: the centre line is the value with no change, bars show each candidate's difference.
  function chart(metric, rows, ref, bestValue) {
    const W = 230; const H = 132; const left = 8; const right = 8; const top = 22; const bottom = 24;
    const zero = top + (H - top - bottom) / 2;
    const deltas = rows.map((r) => r[metric.key] - ref[metric.key]);
    const span = Math.max(...deltas.map(Math.abs), 10 ** -metric.digits) * 1.15;
    const half = (H - top - bottom) / 2 - 2;
    const root_ = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "ox-chart", role: "img", "aria-label": `${metric.label} change by candidate duty against no change` });
    root_.append(svg("line", { x1: left, x2: W - right, y1: zero, y2: zero, class: "ox-zero" }));
    const step = (W - left - right) / Math.max(rows.length, 1);
    const bw = Math.min(26, step * 0.55);
    rows.forEach((r, i) => {
      const d = deltas[i];
      const h = Math.max(1.5, (Math.abs(d) / span) * half);
      const x = left + step * i + (step - bw) / 2;
      const y = d <= 0 ? zero : zero - h;
      const g = svg("g", { class: "ox-bar-group", "data-best": String(r.value === bestValue), "data-executable": String(r.executable) });
      g.append(svg("title", {}, `${number(r.value, 1)}% duty: ${d <= 0 ? "" : "+"}${number(d, metric.digits)} ${metric.unit}`.trim()));
      const rect = svg("rect", { x, y: d <= 0 ? zero : zero - h, width: bw, height: h, rx: 3, class: `ox-bar ${d <= 0 ? "is-good" : "is-bad"}` });
      rect.style.transformOrigin = `${x + bw / 2}px ${zero}px`;
      rect.style.animationDelay = `${i * 60}ms`;
      g.append(rect);
      g.append(svg("text", { x: x + bw / 2, y: d <= 0 ? y + h + 10 : y - 3, class: "ox-bar-val", "text-anchor": "middle" }, `${d > 0 ? "+" : d < 0 ? "−" : ""}${number(Math.abs(d), metric.digits)}`));
      g.append(svg("text", { x: x + bw / 2, y: H - 8, class: `ox-bar-x${r.value === bestValue ? " is-best" : ""}`, "text-anchor": "middle" }, `${number(r.value, 0)}`));
      root_.append(g);
    });
    root_.append(svg("text", { x: left, y: 12, class: "ox-chart-title" }, `${metric.label}${metric.unit ? ` (${metric.unit})` : ""}`), svg("text", { x: W - right, y: 12, class: "ox-chart-note", "text-anchor": "end" }, "vs now"));
    root_.append(svg("text", { x: W / 2, y: H - 0.5, class: "ox-chart-axis", "text-anchor": "middle" }, "candidate duty %"));
    return root_;
  }

  function renderCharts(data) {
    const rows = [...data.candidates].sort((a, b) => a.value - b.value);
    const title = cardHead("Candidates against doing nothing", badge("CALC", "Forecasts on a twin copy; placeholder business factors"));
    if (!rows.length) {
      chartCard.replaceChildren(title, empty("chart", "No candidates in range", "The search found no safe duty values to compare."));
      return;
    }
    const grid = el("div", "ox-chart-grid");
    for (const m of METRICS) grid.append(chart(m, rows, data.reference, data.best?.value));
    const legend = el("div", "ox-legend");
    legend.append(
      el("span", "ox-legend-item is-good", "Lower than now"),
      el("span", "ox-legend-item is-bad", "Higher than now"),
      el("span", "ox-legend-item is-dim", "Faded: not executable"),
    );
    const list = el("div", "cr-chips ox-cands");
    for (const r of [...data.candidates]) list.append(chip(`${number(r.value, 1)}%${r.value === data.best?.value ? " · best" : ""}`, r.executable ? (r.value === data.best?.value ? "ok" : "info") : "warn", r.executable ? "The Gateway would accept this value" : "Does not recover safely or does not beat doing nothing"));
    chartCard.replaceChildren(title, grid, legend, list);
  }

  function renderTrades(data) {
    const trades = data.tradeoffs ?? [];
    tradeHost.replaceChildren(...trades.map((t) => {
      const note = el("div", "ox-trade");
      note.append(glyph("scale", "cr-glyph ox-trade-icon"), el("span", "", t.summary));
      return note;
    }));
    tradeHost.hidden = trades.length === 0;
  }

  function renderPlan(plan) {
    const title = cardHead(plan ? `Repair window · best: ${words(plan.best)}` : "Repair window", badge("CALC", "Placeholder prices"));
    if (!plan) {
      planCard.replaceChildren(title, empty("wrench", "Waiting for a diagnosis", "Inject a fault or let the learning core raise an alert, and the plan appears here."));
      return;
    }
    const top = Math.max(...plan.plans.map((p) => Math.abs(p.net_value)), 1);
    const rows = plan.plans.map((p, i) => {
      const row = el("div", "ox-plan-row");
      row.dataset.best = String(p.plan === plan.best);
      const name = el("div", "ox-plan-name");
      name.append(el("strong", "", words(p.plan).replace(/^\w/, (c) => c.toUpperCase())));
      if (p.plan === plan.best) name.append(chip("best", "ok"));
      if (p.breakdown_at_hours !== null) name.append(chip(`breakdown in ${p.breakdown_at_hours} h`, "crit", "Simulated remaining life runs out before the repair"));
      const bar = el("div", "ox-plan-bar");
      const fill = el("span", "ox-plan-fill");
      fill.style.setProperty("--w", `${Math.max(0, p.net_value) / top * 100}%`);
      fill.style.animationDelay = `${i * 70}ms`;
      bar.append(fill);
      row.append(name, bar, el("span", "cr-num ox-plan-value", Math.round(p.net_value).toLocaleString()), chip(`${p.late_orders} late`, p.late_orders ? "warn" : "ok"));
      return row;
    });
    planCard.replaceChildren(title, ...rows, el("p", "cr-note", "Net value over the planning horizon against open orders. Placeholder prices."));
  }

  function renderHead(data) {
    headChips.replaceChildren(
      chip(`goal · ${GOAL_NAME[data.goal] ?? words(data.goal)}`, "info"),
      chip(`${data.candidates.length} candidate${data.candidates.length === 1 ? "" : "s"}`, data.candidates.length ? "ok" : "warn"),
      badge("CALC", "Forecasts on a twin copy"),
    );
  }

  // ---------- data ----------
  async function load(force = false) {
    if (loading || (!force && performance.now() - loadedAt < REFRESH_MS)) return;
    loading = true;
    loadedAt = performance.now();
    const token = generation;
    try {
      const data = await http("GET", `${base()}/cores/optimization/candidates?goal=${goal}`);
      if (token !== generation) return;
      const key = JSON.stringify(data);
      if (!lastData || lastData.key !== key) {
        lastData = { key };
        renderHead(data); renderHero(data); renderCharts(data); renderTrades(data);
      }
    } catch { /* keep the previous result */ }
    try {
      const plan = await http("GET", `${base()}/cores/optimization/plan?problem=maintenance_window`);
      if (token !== generation) return;
      const key = JSON.stringify(plan);
      if (lastPlan !== key) { lastPlan = key; renderPlan(plan); }
    } catch {
      if (token === generation && lastPlan !== "none") { lastPlan = "none"; renderPlan(null); }
    } finally { loading = false; }
  }

  renderPlan(null);
  lastPlan = "none";

  return {
    root,
    update() { load(); },
    reset() {
      generation += 1; loadedAt = 0; lastData = null; lastPlan = null; loading = false;
      heroCard.replaceChildren(); chartCard.replaceChildren(); tradeHost.replaceChildren();
      renderPlan(null); lastPlan = "none";
    },
    destroy() { generation += 1; },
  };
}
