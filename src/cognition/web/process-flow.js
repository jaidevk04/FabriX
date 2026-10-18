// Process-flow diagram: equipment symbols, animated lines and instrument bubbles bound to live tags.
// Read-only. Selecting equipment or a bubble opens that equipment's HMI screen.

import { createSymbol, mount, unmount, svgEl } from "./symbols.js";

const BUBBLE = { w: 128, h: 52 };
const MEDIA = {
  solid: "Raw material and solids",
  fuel: "Fuel",
  flue: "Flue gas",
  heat: "Heat-transfer fluid",
  product: "Product",
};

export function ownerOf(model, tagId) {
  return (
    model.equipment.find((item) => item.primary === tagId) ?? model.equipment.find((item) => item.tags.includes(tagId))
  );
}
const truncate = (text, size) => (text.length > size ? `${text.slice(0, size - 1)}…` : text);
const html = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// Closest point of the bubble's edge to a target, so leader lines do not cross their own label.
function edgePoint(x, y, to) {
  return [Math.max(x, Math.min(x + BUBBLE.w, to[0])), Math.max(y, Math.min(y + BUBBLE.h, to[1]))];
}

export function createProcessFlow(host, model, { onOpen }) {
  const [width, height] = model.flow.size;
  host.replaceChildren();
  const legend = html("ul", "pf-legend");
  const used = new Set(model.flow.pipes.map((pipe) => pipe.medium));
  for (const medium of used) {
    const item = html("li");
    item.append(html("i", `pf-swatch pf-swatch--${medium}`), document.createTextNode(MEDIA[medium]));
    legend.append(item);
  }
  const note = html("li", "pf-legend-note", "Layout and tag IDs are illustrative display labels. Select equipment to open its HMI.");
  legend.append(note);

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "pf-svg", role: "group", "aria-label": `${model.title} process flow` });
  const defs = svgEl("defs", {}, svg);
  const arrow = svgEl("marker", { id: "pf-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerUnits: "userSpaceOnUse", markerWidth: 16, markerHeight: 16, orient: "auto" }, defs);
  svgEl("path", { d: "M0,0 L10,5 L0,10 Z", class: "pf-arrowhead" }, arrow);
  svgEl("rect", { x: 0, y: 0, width, height, class: "pf-floor" }, svg);

  const pipeLayer = svgEl("g", { class: "pf-pipes" }, svg);
  const nodeLayer = svgEl("g", { class: "pf-nodes" }, svg);
  const tagLayer = svgEl("g", { class: "pf-tags" }, svg);

  const pipes = model.flow.pipes.map((pipe) => {
    const points = pipe.points.map((p) => p.join(",")).join(" ");
    const group = svgEl("g", { class: `pf-pipe pf-pipe--${pipe.medium}`, "data-active": "false" }, pipeLayer);
    svgEl("polyline", { points, class: "pf-pipe-body", "marker-end": "url(#pf-arrow)" }, group);
    const flow = svgEl("polyline", { points, class: "pf-pipe-flow" }, group);
    if (pipe.label) {
      const [x, y] = pipe.at;
      svgEl("text", { x, y, "text-anchor": "middle", class: "pf-pipe-label" }, group).textContent = pipe.label;
    }
    if (pipe.eq) {
      group.classList.add("is-link");
      group.addEventListener("click", () => onOpen(pipe.eq));
    }
    return { pipe, group, flow, offset: 0, speed: 0 };
  });

  const nodes = model.flow.nodes.map((node) => {
    const symbol = createSymbol(node);
    const group = svgEl("g", { class: "pf-node", transform: `translate(${node.x} ${node.y})`, tabindex: 0, role: "button" }, nodeLayer);
    group.append(symbol.g);
    const [hx, hy, hw, hh] = node.hit ?? [-4, -4, node.w + 8, node.h + 8];
    svgEl("rect", { x: hx, y: hy, width: hw, height: hh, rx: 8, class: "pf-hit" }, group);
    const label = svgEl("text", { x: node.labelAt?.[0] ?? 0, y: node.labelAt?.[1] ?? -10, class: "pf-node-label" }, group);
    label.textContent = node.label;
    const equipment = model.equipment.find((item) => item.id === node.eq);
    const open = () => onOpen(node.eq);
    group.addEventListener("click", open);
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
    return { node, symbol, group, equipment };
  });

  const bubbles = model.flow.tags.map((placement) => {
    const def = model.tags[placement.tag];
    const [sx, sy] = edgePoint(placement.x, placement.y, placement.to);
    const group = svgEl("g", { class: "pf-tag", tabindex: 0, role: "button", "data-level": "info" }, tagLayer);
    svgEl("line", { x1: sx, y1: sy, x2: placement.to[0], y2: placement.to[1], class: "pf-leader" }, group);
    svgEl("circle", { cx: placement.to[0], cy: placement.to[1], r: 3, class: "pf-leader-dot" }, group);
    const box = svgEl("g", { transform: `translate(${placement.x} ${placement.y})` }, group);
    svgEl("rect", { width: BUBBLE.w, height: BUBBLE.h, rx: 7, class: "pf-bubble-box" }, box);
    svgEl("text", { x: 8, y: 14, class: "pf-bubble-code" }, box).textContent = def.code || def.label.slice(0, 8);
    const basis = svgEl("text", { x: BUBBLE.w - 8, y: 14, "text-anchor": "end", class: "pf-bubble-basis" }, box);
    const name = svgEl("text", { x: 8, y: 27, class: "pf-bubble-name" }, box);
    name.textContent = truncate(def.label, 23);
    const value = svgEl("text", { x: 8, y: 45, class: "pf-bubble-value" }, box);
    const number = svgEl("tspan", {}, value);
    const unit = svgEl("tspan", { class: "pf-bubble-unit", dx: 3 }, value);
    const owner = ownerOf(model, placement.tag);
    const open = () => owner && onOpen(owner.id);
    group.addEventListener("click", open);
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
    return { placement, group, number, unit, basis, def };
  });

  // Signal list beneath the diagram: the same values in a screen-reader friendly table.
  const table = html("table", "pf-signals");
  const caption = html("caption", "sr-only", "Live signals for this process");
  const head = html("thead");
  const headRow = html("tr");
  for (const label of ["Tag", "Signal", "Value", "Basis", "Condition"]) headRow.append(html("th", "", label));
  head.append(headRow);
  const body = html("tbody");
  const rows = Object.entries(model.tags).map(([id, def]) => {
    const row = html("tr");
    const cells = [html("td", "pf-code", def.code || "—"), html("td", "", def.label), html("td", "pf-num"), html("td"), html("td")];
    row.append(...cells);
    row.addEventListener("click", () => { const owner = ownerOf(model, id); if (owner) onOpen(owner.id); });
    body.append(row);
    return { id, cells, row };
  });
  table.append(caption, head, body);

  const canvas = html("div", "pf-canvas");
  canvas.append(svg);
  const tableWrap = html("div", "table-scroll");
  tableWrap.append(table);
  host.append(legend, canvas, tableWrap);

  // Line flow is the only continuous motion owned here; symbols register themselves.
  const flowMotion = {
    g: svg,
    tick(dt) {
      for (const item of pipes) {
        if (!item.speed) continue;
        item.offset = (item.offset - item.speed * dt) % 28;
        item.flow.setAttribute("stroke-dashoffset", item.offset.toFixed(1));
      }
    },
  };
  mount(flowMotion);
  for (const item of nodes) mount(item.symbol);

  const unavailable = (tag) => tag.level === "unavail";
  return {
    update(c, T) {
      for (const item of pipes) {
        const { pipe } = item;
        const driver = pipe.rate ? T.get(pipe.rate) : null;
        let rate = driver && !unavailable(driver) && driver.norm !== null ? (pipe.invert ? 1 - driver.norm : driver.norm) : null;
        if (pipe.static) rate = null;
        item.speed = rate === null ? 0 : 12 + rate * 88;
        item.group.dataset.active = String(rate !== null && rate > 0.01);
        item.group.dataset.static = String(Boolean(pipe.static));
        if (!item.speed) item.flow.removeAttribute("stroke-dashoffset");
      }
      for (const item of nodes) {
        if (item.node.drive) item.symbol.set(item.node.drive(c, T));
        const status = item.equipment?.status(c, T);
        if (status) {
          item.group.dataset.level = status.level;
          item.group.setAttribute("aria-label", `${item.node.label}: ${status.text}. Open HMI screen.`);
        }
      }
      for (const item of bubbles) {
        const tag = T.get(item.placement.tag);
        item.number.textContent = tag.text;
        item.unit.textContent = tag.value === null ? "" : tag.unit;
        item.basis.textContent = tag.basis.code;
        item.group.dataset.level = tag.level;
        item.group.setAttribute("aria-label", `${tag.label}: ${tag.value === null ? "unavailable" : `${tag.text} ${tag.unit}`}. ${tag.basis.name}. Open HMI screen.`);
      }
      for (const row of rows) {
        const tag = T.get(row.id);
        row.cells[2].textContent = tag.value === null ? "—" : `${tag.text} ${tag.unit}`;
        row.cells[3].textContent = tag.basis.code;
        row.cells[3].title = tag.basis.name;
        row.cells[4].textContent = { ok: "Normal", warn: "Attention", crit: "Alarm", unavail: "Unavailable", info: "—" }[tag.level];
        row.row.dataset.level = tag.level;
      }
    },
    destroy() {
      unmount(flowMotion);
      for (const item of nodes) unmount(item.symbol);
      host.replaceChildren();
    },
  };
}
