// Small DOM and SVG builders shared by the Specialist Faculties page and the Impact page. Vanilla, no dependencies.

const SVG = "http://www.w3.org/2000/svg";

export const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export const svg = (tag, attrs = {}, text) => {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
};

// Request helper for verbs the shared api() does not cover (DELETE) and for error text.
export async function http(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    throw new Error(detail);
  }
  return data;
}

export const STATUS_LEVEL = { normal: "ok", watch: "warn", alert: "crit", high: "warn", low: "warn" };
export const ALERT_LEVEL = { info: "info", watch: "warn", notify: "warn", escalate: "crit" };

export function lamp(level, label) {
  const node = el("span", "cr-lamp");
  node.dataset.level = level;
  if (label) {
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", label);
  } else node.setAttribute("aria-hidden", "true");
  return node;
}

// Basis badge: SIM / EST / CALC, as everywhere else in the product.
export function badge(text, title, className = "hmi-basis") {
  const node = el("span", className, text);
  if (title) node.title = title;
  return node;
}

export function chip(text, level = "info", title) {
  const node = el("span", "cr-chip", text);
  node.dataset.level = level;
  if (title) node.title = title;
  return node;
}

export function sparkline(values, { width = 120, height = 28, level = "info", band } = {}) {
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "cr-spark", "aria-hidden": "true" });
  root.dataset.level = level;
  if (values.length < 2) return root;
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (band) {
    low = Math.min(low, band[0]);
    high = Math.max(high, band[1]);
  }
  const span = high - low || 1;
  const x = (i) => (i / (values.length - 1)) * (width - 4) + 2;
  const y = (v) => height - 3 - ((v - low) / span) * (height - 6);
  if (band) {
    root.append(svg("rect", { x: 0, y: y(band[1]), width, height: Math.max(1, y(band[0]) - y(band[1])), class: "cr-spark-band" }));
  }
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  root.append(svg("polyline", { points, class: "cr-spark-line" }));
  root.append(svg("circle", { cx: x(values.length - 1), cy: y(values.at(-1)), r: 2.4, class: "cr-spark-dot" }));
  return root;
}

// Waveform scope: grid, zero line and a polyline. Samples are simulated, never recorded.
export function scope(samples, { width = 420, height = 120, level = "info" } = {}) {
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "cr-scope", role: "img", "aria-label": "Simulated waveform" });
  root.dataset.level = level;
  for (let i = 1; i < 4; i++) root.append(svg("line", { x1: 0, x2: width, y1: (height / 4) * i, y2: (height / 4) * i, class: "cr-scope-grid" }));
  for (let i = 1; i < 8; i++) root.append(svg("line", { y1: 0, y2: height, x1: (width / 8) * i, x2: (width / 8) * i, class: "cr-scope-grid" }));
  if (samples.length < 2) return root;
  const peak = Math.max(...samples.map(Math.abs), 1e-6);
  const points = samples
    .map((v, i) => `${((i / (samples.length - 1)) * width).toFixed(1)},${(height / 2 - (v / peak) * (height / 2 - 6)).toFixed(1)}`)
    .join(" ");
  root.append(svg("polyline", { points, class: "cr-scope-line" }));
  return root;
}

export function meter(value, max, { level = "info", reference } = {}) {
  const track = el("span", "cr-meter");
  track.dataset.level = level;
  const fill = el("span", "cr-meter-fill");
  fill.style.width = `${Math.max(0, Math.min(1, max ? value / max : 0)) * 100}%`;
  track.append(fill);
  if (reference !== undefined && max) {
    const mark = el("span", "cr-meter-ref");
    mark.style.left = `${Math.max(0, Math.min(1, reference / max)) * 100}%`;
    mark.title = "Value with no change";
    track.append(mark);
  }
  return track;
}

export function donut(value, { size = 96, level = "info", label = "" } = {}) {
  const radius = size / 2 - 8;
  const circumference = 2 * Math.PI * radius;
  const root = svg("svg", { viewBox: `0 0 ${size} ${size}`, class: "cr-donut", role: "img", "aria-label": `${label} ${Math.round(value * 100)}%` });
  root.dataset.level = level;
  root.append(svg("circle", { cx: size / 2, cy: size / 2, r: radius, class: "cr-donut-track" }));
  const arc = svg("circle", {
    cx: size / 2, cy: size / 2, r: radius, class: "cr-donut-arc",
    "stroke-dasharray": `${Math.max(0, Math.min(1, value)) * circumference} ${circumference}`,
    transform: `rotate(-90 ${size / 2} ${size / 2})`,
  });
  root.append(arc, svg("text", { x: size / 2, y: size / 2 + 5, class: "cr-donut-text", "text-anchor": "middle" }, `${Math.round(value * 100)}%`));
  return root;
}

export const number = (value, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });

export const money = (value) => (value === null || value === undefined ? "—" : `${value < 0 ? "-" : ""}${Math.abs(Math.round(value)).toLocaleString()}`);

export function ago(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

export const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour12: false });

export const words = (text) => String(text).replaceAll("_", " ");

// Zone graph layout: breadth-first order from the dock, laid out as a snake of at most three
// columns so neighbours stay adjacent and the text stays readable.
export function layoutZones(zones, cell = { w: 168, h: 84, gx: 30, gy: 26 }, columns = 3) {
  const byId = new Map(zones.map((z) => [z.id, z]));
  const start = zones.find((z) => z.kind === "dock") ?? zones[0];
  const order = [start.id];
  const seen = new Set(order);
  for (let i = 0; i < order.length; i++) {
    for (const next of byId.get(order[i])?.next_to ?? []) {
      if (!seen.has(next) && byId.has(next)) { seen.add(next); order.push(next); }
    }
  }
  for (const z of zones) if (!seen.has(z.id)) order.push(z.id);
  const positions = {};
  order.forEach((id, index) => {
    const row = Math.floor(index / columns);
    const col = row % 2 === 0 ? index % columns : columns - 1 - (index % columns);
    positions[id] = { x: col * (cell.w + cell.gx) + 8, y: row * (cell.h + cell.gy) + 8 };
  });
  const rows = Math.ceil(order.length / columns);
  return {
    positions,
    width: Math.min(columns, order.length) * (cell.w + cell.gx) - cell.gx + 16,
    height: rows * (cell.h + cell.gy) - cell.gy + 16,
    cell,
  };
}

export const ICONS = {
  overview: "M4 4h7v7H4ZM13 4h7v7h-7ZM4 13h7v7H4ZM13 13h7v7h-7Z",
  learning: "M3 12h3l2-6 4 12 3-9 2 3h4",
  vision: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  robot: "M12 3v3M7 8h10a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2ZM9.5 13h.01M14.5 13h.01M9 17h6",
  optimization: "M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M8 14v6",
};

export function icon(name) {
  const root = svg("svg", { viewBox: "0 0 24 24", class: "cr-icon", "aria-hidden": "true" });
  root.append(svg("path", { d: ICONS[name] }));
  return root;
}

// Small outline glyphs for fact rows and alert items (24x24, stroke only).
export const GLYPHS = {
  alert: "M12 4 3 20h18L12 4ZM12 10v4M12 17h.01",
  bell: "M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7ZM10 20a2 2 0 0 0 4 0",
  chip: "M9 9h6v6H9ZM4 9h2M4 15h2M18 9h2M18 15h2M9 4v2M15 4v2M9 18v2M15 18v2",
  bolt: "M13 3 5 14h6l-1 7 8-11h-6l1-7Z",
  camera: "M3 8a2 2 0 0 1 2-2h2l1.5-2h7L17 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2ZM12 9.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z",
  check: "M5 12.5 10 17.5 19 7",
  film: "M4 5h16v14H4ZM8 5v14M16 5v14M4 9h4M4 15h4M16 9h4M16 15h4",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM16 16l4 4",
  wrench: "M14 4a5 5 0 0 0-4 7l-6 6 3 3 6-6a5 5 0 0 0 7-4l-3 3-3-1-1-3 3-3a5 5 0 0 0-2-2Z",
  box: "M4 8l8-4 8 4v8l-8 4-8-4ZM4 8l8 4 8-4M12 12v8",
  gear: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1",
  flame: "M12 3c1 3 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9Z",
  shield: "M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6Z",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6Z",
  route: "M9 6l6 6-6 6",
  target: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  chart: "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3",
  leaf: "M5 19c0-8 5-13 14-14 0 9-5 14-14 14ZM5 19l7-7",
  coin: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 8v8M9.5 10h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3H14",
  clock: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 8v4l3 2",
  report: "M7 3h8l4 4v14H7ZM15 3v4h4M10 12h6M10 16h6",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8ZM18 16l.8 2.2L21 19l-2.2.8L18 22l-.8-2.2L15 19l2.2-.8Z",
  list: "M4 6h16M4 12h16M4 18h10",
  scale: "M12 4v16M6 20h12M5 8h14M5 8l-3 7a3 3 0 0 0 6 0ZM19 8l-3 7a3 3 0 0 0 6 0Z",
};

export function glyph(name, className = "cr-glyph") {
  const root = svg("svg", { viewBox: "0 0 24 24", class: className, "aria-hidden": "true" });
  root.append(svg("path", { d: GLYPHS[name] }));
  return root;
}
