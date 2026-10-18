// Shared building blocks for the HMI screens: DOM helpers, status lamp, basis chip and the trend chart.
// Display only. Nothing here writes to the plant.

import { convert } from "./plant-signals.js";
import { svgEl } from "./symbols.js";

export const html = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export const LEVEL_TEXT = { ok: "Normal", warn: "Attention", crit: "Alarm", unavail: "Unavailable", info: "Info" };

export function lamp(level) {
  const node = html("i", "hmi-lamp");
  node.dataset.level = level;
  return node;
}

export function chip(basis) {
  const node = html("span", "hmi-basis", basis.code);
  node.title = basis.name;
  return node;
}

// Multi-series trend with the recovery band, optional setpoint, and gaps where a signal was invalid.
// With `fit`, the drawing follows the width it is given so text keeps its size on any screen.
// With `fit: "fill"` it also follows the height of its plot area, so a layout can size the chart.
export function trendChart({ series, band, marker, unit, title, height = 210, fit = false }) {
  let W = 640;
  let H = height;
  const fill = fit === "fill";
  const L = 54;
  const R = 14;
  const T = 12;
  const B = 28;
  const svg = svgEl("svg", { class: "hmi-trend-svg", role: "img", "aria-label": title });
  const bandRect = svgEl("rect", { class: "hmi-trend-band", x: L }, svg);
  const grid = svgEl("g", { class: "hmi-trend-grid" }, svg);
  const markerLine = svgEl("line", { class: "hmi-trend-marker", x1: L }, svg);
  const lines = series.map((s) => svgEl("path", { class: `hmi-trend-line ${s.cls ?? ""}`, fill: "none" }, svg));
  const dots = series.map((s) => svgEl("circle", { class: `hmi-trend-dot ${s.cls ?? ""}`, r: 3.5 }, svg));
  const left = svgEl("text", { x: L, class: "hmi-trend-axis" }, svg);
  const right = svgEl("text", { "text-anchor": "end", class: "hmi-trend-axis" }, svg);
  const empty = svgEl("text", { "text-anchor": "middle", class: "hmi-trend-empty" }, svg);
  const legend = html("ul", "hmi-trend-legend");
  for (const s of series) {
    const item = html("li");
    item.append(html("i", `hmi-swatch ${s.cls ?? ""}`), document.createTextNode(s.name));
    legend.append(item);
  }
  const wrap = html("div", fill ? "hmi-trend is-fill" : "hmi-trend");
  const plot = html("div", "hmi-trend-plot");
  plot.append(svg);
  wrap.append(plot, legend);

  const place = () => {
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    bandRect.setAttribute("width", W - L - R);
    markerLine.setAttribute("x2", W - R);
    right.setAttribute("x", W - R);
    left.setAttribute("y", H - 8);
    right.setAttribute("y", H - 8);
    empty.setAttribute("x", (L + W - R) / 2);
    empty.setAttribute("y", H / 2);
  };
  place();

  let lastArgs = null;
  function draw({ values, clocks, T: tags, preference }) {
    lastArgs = { values, clocks, T: tags, preference };
    const all = [];
    series.forEach((s) => all.push(...values(s.tag).filter((v) => v !== null)));
    const bandTag = band ? tags.get(band) : null;
    const markTag = marker ? tags.get(marker) : null;
    const extra = [];
    if (bandTag?.band) extra.push(...bandTag.band);
    if (markTag?.value != null) extra.push(markTag.value);
    const pool = [...all, ...extra];
    empty.textContent = all.length ? "" : "Waiting for samples. Start the live simulation to build a trend.";
    if (!pool.length) {
      lines.forEach((p) => p.setAttribute("d", ""));
      dots.forEach((d) => d.setAttribute("r", 0));
      bandRect.setAttribute("height", 0);
      return;
    }
    let lo = Math.min(...pool);
    let hi = Math.max(...pool);
    const pad = (hi - lo || Math.abs(hi) * 0.02 || 1) * 0.15;
    lo -= pad; hi += pad;
    const x = (i, n) => L + (n <= 1 ? (W - L - R) : (i / (n - 1)) * (W - L - R));
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    if (bandTag?.band) {
      const top = y(bandTag.band[1]);
      bandRect.setAttribute("y", top.toFixed(1));
      bandRect.setAttribute("height", Math.max(0, y(bandTag.band[0]) - top).toFixed(1));
    } else bandRect.setAttribute("height", 0);
    if (markTag?.value != null) {
      markerLine.setAttribute("y1", y(markTag.value).toFixed(1));
      markerLine.setAttribute("y2", y(markTag.value).toFixed(1));
      markerLine.style.display = "";
    } else markerLine.style.display = "none";
    grid.replaceChildren();
    for (let i = 0; i <= 3; i++) {
      const v = lo + ((hi - lo) * i) / 3;
      const shown = convert(v, unit, preference);
      const ty = y(v);
      svgEl("line", { x1: L, x2: W - R, y1: ty.toFixed(1), y2: ty.toFixed(1) }, grid);
      svgEl("text", { x: L - 6, y: (ty + 3).toFixed(1), "text-anchor": "end" }, grid).textContent = shown.value.toLocaleString(undefined, { maximumFractionDigits: Math.abs(hi - lo) < 10 ? 2 : 0 });
    }
    series.forEach((s, index) => {
      const data = values(s.tag);
      let path = "";
      let pen = false;
      let lastPoint = null;
      data.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        const px = x(i, data.length);
        path += `${pen ? "L" : "M"}${px.toFixed(1)},${y(v).toFixed(1)} `;
        pen = true;
        lastPoint = [px, y(v)];
      });
      lines[index].setAttribute("d", path.trim());
      if (lastPoint) { dots[index].setAttribute("cx", lastPoint[0].toFixed(1)); dots[index].setAttribute("cy", lastPoint[1].toFixed(1)); dots[index].setAttribute("r", 3.5); }
      else dots[index].setAttribute("r", 0);
    });
    const times = clocks();
    left.textContent = times.length > 1 ? `${times[0]} sim` : "";
    right.textContent = times.length ? `${times.at(-1)} sim` : "";
  }

  let observer = null;
  if (fit && typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width);
      const tall = fill ? Math.round(entry.contentRect.height) : H;
      if (width < 240 || tall < 70) return;
      if (Math.abs(width - W) < 2 && Math.abs(tall - H) < 2) return;
      W = width;
      H = tall;
      place();
      if (lastArgs) draw(lastArgs);
    });
    observer.observe(plot);
  }

  return { el: wrap, update: draw, destroy: () => observer?.disconnect() };
}
