// Robot core workspace: the zone graph with robot tokens that replay each mission as it completes
// (out along the route, a work pulse at the target, back to the dock), a fleet roster, and the mission feed.
// Read only. Missions finish instantly on the server; this view animates them so the movement is visible.
import { ALERT_LEVEL, GLYPHS, ago, badge, chip, el, glyph, layoutZones, meter, svg, words } from "./cores-parts.js";

const SPEED = 190; // map units per second
const WORK_SECONDS = 1.5;
const BATTERY_R = 12.5;
const BATTERY_C = 2 * Math.PI * BATTERY_R;
const KIND_GLYPH = { inspector: "search", maintainer: "wrench", carrier: "box" };
const ZONE_GLYPH = { dock: "bolt", process: "gear", hot: "flame", safe: "shield" };
const STATUS_TEXT = { docked: "Docked", idle: "Idle", moving: "Moving", working: "Working", charging: "Charging", fault: "Fault" };
const STATUS_LEVEL = { docked: "off", idle: "info", moving: "info", working: "warn", charging: "ok", fault: "crit" };
const RANK = { info: 0, watch: 1, notify: 2, escalate: 3 };
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const place = (node, x, y) => node.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);

// A glyph inside the map SVG, scaled from the 24-unit icon grid.
function mapIcon(name, size = 16, className = "rv-ico") {
  const g = svg("g", { class: className, transform: `scale(${size / 24})` });
  g.append(svg("path", { d: GLYPHS[name] }));
  return g;
}

export function createRobotView({ onReplay } = {}) {
  const root = el("div", "rv");
  let layout = null;
  let zonesKey = "";
  let fleet = null;
  let zoneNodes = new Map();
  let edgeNodes = new Map();
  let tokens = new Map();
  let mapRoot = null;
  let botLayer = null;
  let traceLayer = null;
  let seenMissions = null; // null until the first update so old missions are not replayed
  let anims = [];
  const pending = new Map(); // robot id -> missions waiting for the current replay to finish
  let frame = 0;
  let lastFrame = 0;
  let missions = [];
  let destroyed = false;
  const roster = new Map();

  // ---------- skeleton ----------
  const head = el("header", "rv-head");
  const headText = el("div");
  headText.append(el("h3", "", "Fleet and zones"), el("p", "cr-sub", "Simulated robots on the plant zone graph. Missions replay as they complete."));
  const headChips = el("div", "rv-head-chips");
  head.append(headText, headChips);
  const stats = el("div", "rv-stats");
  const main = el("div", "rv-main");
  const mapCard = el("section", "rv-card rv-mapcard");
  const mapHead = el("div", "rv-card-head");
  mapHead.append(el("h4", "cr-mini", "Plant map"), badge("SIM", "Simulated robots; no physical equipment"));
  const mapHost = el("div", "rv-map");
  const legend = el("div", "rv-legend");
  for (const [status, text] of Object.entries(STATUS_TEXT)) {
    const item = el("span", "rv-legend-item");
    const dot = el("i");
    dot.dataset.status = status;
    item.append(dot, text);
    legend.append(item);
  }
  mapCard.append(mapHead, mapHost, legend);
  const rosterCard = el("section", "rv-card rv-roster-card");
  const rosterHead = el("div", "rv-card-head");
  rosterHead.append(el("h4", "cr-mini", "Fleet"));
  const rosterList = el("div", "rv-roster");
  rosterCard.append(rosterHead, rosterList);
  main.append(mapCard, rosterCard);
  const missionCard = el("section", "rv-card");
  const missionHead = el("div", "rv-card-head");
  missionHead.append(el("h4", "cr-mini", "Recent missions"), el("span", "cr-sub", "Select one to replay it on the map"));
  const missionList = el("ol", "rv-missions");
  missionCard.append(missionHead, missionList);
  root.append(head, stats, main, missionCard);

  // ---------- map ----------
  function buildMap(data) {
    layout = layoutZones(data.fleet.zones);
    const pad = 14;
    mapRoot = svg("svg", { viewBox: `${-pad} ${-pad} ${layout.width + pad * 2} ${layout.height + pad * 2}`, class: "rv-svg", role: "img", "aria-label": "Plant zones with robots, routes and lock-outs" });
    const defs = svg("defs");
    const grid = svg("pattern", { id: "rv-grid", width: 22, height: 22, patternUnits: "userSpaceOnUse" });
    grid.append(svg("circle", { cx: 1, cy: 1, r: 1, class: "rv-grid-dot" }));
    defs.append(grid);
    mapRoot.append(defs, svg("rect", { x: -pad, y: -pad, width: layout.width + pad * 2, height: layout.height + pad * 2, fill: "url(#rv-grid)" }));
    zoneNodes = new Map(); edgeNodes = new Map(); tokens = new Map();
    const { cell } = layout;
    const centre = (id) => anchorOf(id);
    const edges = svg("g", { class: "rv-edges" });
    for (const z of data.fleet.zones) {
      for (const next of z.next_to) {
        const key = [z.id, next].sort().join("|");
        if (edgeNodes.has(key) || !layout.positions[next]) continue;
        const a = centre(z.id);
        const b = centre(next);
        const line = svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "rv-edge" });
        edgeNodes.set(key, line);
        edges.append(line);
      }
    }
    mapRoot.append(edges);
    for (const z of data.fleet.zones) {
      const p = layout.positions[z.id];
      const g = svg("g", { class: "rv-zone", "data-kind": z.kind, transform: `translate(${p.x} ${p.y})` });
      const ring = svg("rect", { width: cell.w, height: cell.h, rx: 12, class: "rv-zone-ring" });
      const body = svg("rect", { width: cell.w, height: cell.h, rx: 12, class: "rv-zone-body" });
      const icon = mapIcon(ZONE_GLYPH[z.kind] ?? "gear", 15);
      icon.setAttribute("transform", `translate(12 11) scale(${15 / 24})`);
      const name = svg("text", { x: 33, y: 23, class: "rv-zone-name" }, z.name);
      const eq = svg("text", { x: 12, y: 44, class: "rv-zone-eq" }, z.equipment.length ? z.equipment.join(" · ") : z.kind === "dock" ? "robot dock · charging" : z.kind);
      const lock = mapIcon("lock", 15, "rv-lock");
      lock.setAttribute("transform", `translate(${cell.w - 28} 10) scale(${15 / 24})`);
      lock.setAttribute("visibility", "hidden");
      g.append(ring, body, icon, name, eq, lock);
      zoneNodes.set(z.id, { g, lock, z });
      mapRoot.append(g);
    }
    traceLayer = svg("g", { class: "rv-traces" });
    botLayer = svg("g", { class: "rv-bots" });
    mapRoot.append(traceLayer, botLayer);
    for (const r of data.fleet.robots) {
      const g = svg("g", { class: "rv-bot", "data-status": r.status, "data-kind": r.kind });
      g.append(svg("title", {}));
      g.append(svg("circle", { r: 15, class: "rv-bot-halo" }));
      g.append(svg("circle", { r: 9.5, class: "rv-bot-body" }));
      g.append(svg("circle", { r: BATTERY_R, class: "rv-batt-track" }));
      const arc = svg("circle", { r: BATTERY_R, class: "rv-batt-arc", transform: "rotate(-90)" });
      g.append(arc);
      const icon = mapIcon(KIND_GLYPH[r.kind] ?? "search", 10, "rv-bot-ico");
      icon.setAttribute("transform", `translate(-5 -5) scale(${10 / 24})`);
      g.append(icon);
      g.append(svg("circle", { cx: 8, cy: -8, r: 2.8, class: "rv-bot-dot" }));
      botLayer.append(g);
      tokens.set(r.id, { g, arc, title: g.firstChild, pos: null, target: null });
    }
    mapHost.replaceChildren(mapRoot);
  }

  // Everything sits on the bottom row of a zone, below its title and equipment text.
  const rowY = (zoneId) => layout.positions[zoneId].y + layout.cell.h - 20;
  const homeSlot = (zoneId, index) => ({ x: layout.positions[zoneId].x + 24 + index * 30, y: rowY(zoneId) });
  const anchorOf = (zoneId, offset = 0) => ({ x: layout.positions[zoneId].x + layout.cell.w / 2 + offset, y: rowY(zoneId) });
  const centreOf = anchorOf;

  function syncTokens() {
    const byZone = new Map();
    for (const r of fleet.robots) {
      const index = byZone.get(r.zone) ?? 0;
      byZone.set(r.zone, index + 1);
      const t = tokens.get(r.id);
      if (!t) continue;
      const busy = anims.some((a) => a.robot === r.id);
      t.g.dataset.status = busy ? "moving" : r.status;
      t.g.dataset.low = String(r.battery < 20);
      t.arc.setAttribute("stroke-dasharray", `${(Math.max(0, Math.min(100, r.battery)) / 100) * BATTERY_C} ${BATTERY_C}`);
      t.title.textContent = `${r.name} · ${r.status} · battery ${Math.round(r.battery)}% · ${r.zone}`;
      if (!busy && layout.positions[r.zone]) {
        t.target = homeSlot(r.zone, index);
        if (!t.pos) { t.pos = { ...t.target }; place(t.g, t.pos.x, t.pos.y); } else wake();
      }
    }
  }

  function syncZones(data) {
    const level = new Map();
    for (const { report } of data.cores) {
      for (const a of report.alerts) {
        if (!a.equipment) continue;
        const prev = level.get(a.equipment);
        if (prev === undefined || RANK[a.level] > RANK[prev]) level.set(a.equipment, a.level);
      }
    }
    for (const { g, lock, z } of zoneNodes.values()) {
      const hot = z.equipment.map((e) => level.get(e)).filter(Boolean);
      const worst = ["escalate", "notify", "watch"].find((l) => hot.includes(l));
      if (worst) g.dataset.alert = ALERT_LEVEL[worst]; else delete g.dataset.alert;
      lock.setAttribute("visibility", z.equipment.some((e) => data.fleet.lockouts.includes(e)) ? "visible" : "hidden");
    }
  }

  // ---------- mission replay ----------
  function routeOf(m) {
    const step = (m.steps ?? []).find((s) => s.startsWith("move "));
    const route = step ? step.slice(5).split(" -> ").map((s) => s.trim()) : [m.zone];
    return route.filter((id) => layout.positions[id]);
  }

  // One replay per robot at a time. A follow-up mission to the same place (an inspect then a verify) extends the
  // time spent working there; anything else waits its turn and starts after the robot is back at the dock.
  function enqueue(m) {
    if (!layout || reduceMotion() || !tokens.has(m.robot_id)) return;
    const route = routeOf(m);
    if (route.length < 1) return;
    const active = anims.find((a) => a.robot === m.robot_id);
    if (active) {
      if (!active.back && !active.stays && m.kind !== "lockout" && route.at(-1) === active.route.at(-1)) active.workTotal += WORK_SECONDS;
      else pending.set(m.robot_id, [...(pending.get(m.robot_id) ?? []), m]);
      return;
    }
    start(m, route);
  }

  function start(m, route) {
    const offset = ((m.robot_id.charCodeAt(m.robot_id.length - 1) % 3) - 1) * 8;
    const pts = route.map((id) => centreOf(id, offset));
    const planned = svg("polyline", { class: "rv-route-line", points: pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") });
    const trace = svg("polyline", { class: "rv-trace", points: `${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}` });
    traceLayer.append(planned, trace);
    const a = { robot: m.robot_id, route, pts, stays: m.kind === "lockout", kind: m.kind, seg: 0, t: 0, phase: "out", workT: 0, workTotal: WORK_SECONDS, back: false, trace, planned };
    anims.push(a);
    const t = tokens.get(m.robot_id);
    t.pos = { ...pts[0] };
    place(t.g, pts[0].x, pts[0].y);
    syncTokens();
    highlight();
    wake();
  }

  function wake() {
    if (!frame && !destroyed) { lastFrame = performance.now(); frame = requestAnimationFrame(tick); }
  }

  function highlight() {
    const count = new Map();
    for (const a of anims) {
      const path = a.back ? [...a.route].reverse() : a.route;
      for (let i = 0; i < path.length - 1; i++) {
        const key = [path[i], path[i + 1]].sort().join("|");
        count.set(key, (count.get(key) ?? 0) + 1);
      }
    }
    for (const [key, line] of edgeNodes) line.dataset.active = String(count.has(key));
    for (const { g } of zoneNodes.values()) delete g.dataset.target;
    for (const a of anims) zoneNodes.get(a.route.at(-1))?.g.setAttribute("data-target", "true");
  }

  function tick(now) {
    frame = 0;
    if (destroyed) return;
    const dt = Math.min(0.08, (now - lastFrame) / 1000);
    lastFrame = now;
    for (const a of [...anims]) {
      const t = tokens.get(a.robot);
      if (a.phase === "work") {
        a.workT += dt;
        t.g.dataset.status = "working";
        t.g.dataset.phase = a.kind;
        if (a.workT >= a.workTotal) {
          t.g.removeAttribute("data-phase");
          if (a.stays || a.route.length < 2) { finish(a); continue; }
          a.phase = "back"; a.back = true; a.pts = [...a.pts].reverse(); a.seg = 0; a.t = 0;
          highlight();
        }
        continue;
      }
      t.g.dataset.status = "moving";
      const from = a.pts[a.seg];
      const to = a.pts[a.seg + 1];
      if (!to) {
        if (a.phase === "out") { a.phase = "work"; a.workT = 0; } else finish(a);
        continue;
      }
      const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
      a.t += (SPEED * dt) / length;
      if (a.t >= 1) { a.seg += 1; a.t = 0; }
      const f = Math.min(1, a.t);
      const x = from.x + (to.x - from.x) * f;
      const y = from.y + (to.y - from.y) * f;
      t.pos = { x, y };
      place(t.g, x, y);
      a.trace.setAttribute("points", `${a.trace.getAttribute("points")} ${x.toFixed(1)},${y.toFixed(1)}`);
    }
    // Idle robots glide to their slot instead of jumping when the state changes.
    let settling = false;
    for (const [id, t] of tokens) {
      if (!t.target || !t.pos || anims.some((a) => a.robot === id)) continue;
      const dx = t.target.x - t.pos.x;
      const dy = t.target.y - t.pos.y;
      if (Math.hypot(dx, dy) < 0.5) { t.pos = { ...t.target }; place(t.g, t.pos.x, t.pos.y); continue; }
      const k = 1 - Math.exp(-dt * 9);
      t.pos = { x: t.pos.x + dx * k, y: t.pos.y + dy * k };
      place(t.g, t.pos.x, t.pos.y);
      settling = true;
    }
    if (anims.length || settling) frame = requestAnimationFrame(tick);
  }

  function finish(a) {
    anims = anims.filter((x) => x !== a);
    const t = tokens.get(a.robot);
    t.g.removeAttribute("data-phase");
    for (const line of [a.trace, a.planned]) {
      line.classList.add("is-fading");
      setTimeout(() => line.remove(), 1500);
    }
    const next = pending.get(a.robot)?.shift();
    if (next) {
      if (!pending.get(a.robot).length) pending.delete(a.robot);
      start(next, routeOf(next));
      return;
    }
    syncTokens();
    highlight();
    wake();
  }

  // ---------- roster, stats, missions ----------
  function renderRoster() {
    for (const r of fleet.robots) {
      let card = roster.get(r.id);
      if (!card) {
        const node = el("article", "rv-robot");
        const avatar = el("div", "rv-avatar");
        avatar.append(glyph(KIND_GLYPH[r.kind] ?? "search", "cr-glyph"));
        const text = el("div", "rv-robot-text");
        const top = el("div", "rv-robot-top");
        const name = el("strong", "", r.name);
        const status = el("span", "rv-status");
        top.append(name, status);
        const where = el("span", "cr-sub");
        const battery = el("div", "rv-battery");
        const bar = el("span", "rv-battery-bar");
        const pct = el("span", "cr-num");
        battery.append(bar, pct);
        const tools = el("div", "cr-chips");
        for (const tool of r.tools) tools.append(el("span", "lv-chip", words(tool)));
        text.append(top, where, battery, tools);
        node.append(avatar, text);
        card = { node, status, where, bar, pct };
        roster.set(r.id, card);
        rosterList.append(node);
      }
      const busy = anims.some((a) => a.robot === r.id);
      const status = busy ? "moving" : r.status;
      card.node.dataset.status = status;
      card.node.dataset.low = String(r.battery < 20);
      card.status.dataset.level = STATUS_LEVEL[status] ?? "info";
      card.status.textContent = busy ? "On mission" : STATUS_TEXT[status] ?? words(status);
      const zone = fleet.zones.find((z) => z.id === r.zone);
      card.where.textContent = `${words(r.kind)} · ${zone?.name ?? r.zone}`;
      card.bar.style.setProperty("--w", `${Math.max(0, Math.min(100, r.battery))}%`);
      card.pct.textContent = `${Math.round(r.battery)}%`;
    }
  }

  function renderStats() {
    const robots = fleet.robots;
    const active = robots.filter((r) => anims.some((a) => a.robot === r.id) || ["working", "moving"].includes(r.status)).length;
    const avg = robots.length ? robots.reduce((s, r) => s + r.battery, 0) / robots.length : 0;
    const items = [
      ["Robots", String(robots.length), `${robots.filter((r) => r.status === "docked").length} docked`],
      ["On mission", String(active), active ? "moving or working" : "all waiting"],
      ["Average battery", `${Math.round(avg)}%`, robots.some((r) => r.battery < 20) ? "one is low" : "healthy"],
      ["Lock-outs", String(fleet.lockouts.length), fleet.lockouts.length ? fleet.lockouts.join(", ") : "none active"],
    ];
    const signature = JSON.stringify(items);
    if (stats.dataset.sig === signature) return;
    stats.dataset.sig = signature;
    stats.replaceChildren(...items.map(([label, value, hint]) => {
      const tile = el("div", "rv-stat");
      tile.append(el("span", "rv-stat-label", label), el("strong", "rv-stat-value", value), el("span", "rv-stat-hint", hint));
      return tile;
    }));
  }

  function renderMissions() {
    const signature = JSON.stringify(missions.map((m) => m.id));
    if (missionList.dataset.sig === signature) return;
    missionList.dataset.sig = signature;
    if (!missions.length) {
      missionList.replaceChildren(el("li", "cr-empty", "No missions yet. Robots wait at the dock."));
      return;
    }
    missionList.replaceChildren(...[...missions].reverse().map((m) => {
      const li = el("li", "rv-mission");
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.setAttribute("aria-label", `Replay ${words(m.kind)} ${m.target}`);
      const route = el("span", "rv-route");
      const path = routeOf(m);
      path.forEach((id, i) => {
        if (i) route.append(glyph("route", "cr-glyph rv-route-arrow"));
        route.append(el("span", "rv-route-zone", fleet?.zones.find((z) => z.id === id)?.name ?? id));
      });
      const robot = fleet?.robots.find((r) => r.id === m.robot_id)?.name ?? m.robot_id;
      li.append(
        chip(m.tier, m.tier === "T2-prep" ? "warn" : "info", "Authority tier"),
        el("strong", "rv-mission-title", `${words(m.kind)} · ${m.target}`),
        el("span", "cr-sub", `${robot}${m.tool ? ` · ${words(m.tool)}` : ""}`),
        route,
        el("span", "cr-num cr-sub", `-${m.battery_used}% battery`),
        el("time", "cr-time", ago(m.created_at)),
      );
      const replay = () => { enqueue(m); onReplay?.(m); };
      li.addEventListener("click", replay);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); replay(); } });
      return li;
    }));
  }

  function renderHead() {
    const live = chip(`${fleet.robots.length} robots · ${fleet.zones.length} zones`, "info");
    headChips.replaceChildren(live, fleet.lockouts.length ? chip(`${fleet.lockouts.length} lock-out${fleet.lockouts.length === 1 ? "" : "s"}`, "warn") : chip("no lock-outs", "ok"), badge("SIM", "Simulated fleet on a zone graph; no physical robots"));
  }

  return {
    root,
    update(data) {
      fleet = data.fleet;
      missions = data.missions;
      const key = JSON.stringify(fleet.zones.map((z) => [z.id, z.next_to]).concat(fleet.robots.map((r) => [r.id, r.kind])));
      if (key !== zonesKey || !mapRoot) {
        zonesKey = key;
        anims = []; pending.clear();
        buildMap(data);
        roster.clear(); rosterList.replaceChildren();
      }
      const fresh = missions.filter((m) => seenMissions && !seenMissions.has(m.id));
      seenMissions = new Set([...(seenMissions ?? []), ...missions.map((m) => m.id)]);
      fresh.forEach(enqueue);
      syncTokens();
      syncZones(data);
      renderHead();
      renderStats();
      renderRoster();
      renderMissions();
    },
    reset() {
      anims = []; pending.clear(); seenMissions = null; zonesKey = ""; mapRoot = null; fleet = null;
      mapHost.replaceChildren(); rosterList.replaceChildren(); roster.clear(); missionList.dataset.sig = ""; stats.dataset.sig = "";
    },
    destroy() { destroyed = true; cancelAnimationFrame(frame); },
  };
}
