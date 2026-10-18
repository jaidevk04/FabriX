// SVG equipment symbols for the process-flow and HMI views.
// Each symbol takes live parameters from the plant model and animates between samples.
// Motion is illustrative; it never implies a measurement the simulator does not publish.

const NS = "http://www.w3.org/2000/svg";
export const svgEl = (tag, attrs = {}, parent) => {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  parent?.append(node);
  return node;
};
const clamp01 = (v) => Math.max(0, Math.min(1, v));

// One animation loop for every mounted symbol. It sleeps when nothing is visible.
const mounted = new Set();
let frameId = 0;
let last = 0;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

function frame(now) {
  frameId = 0;
  const dt = Math.min((now - (last || now)) / 1000, 0.1);
  last = now;
  if (!document.hidden) for (const item of mounted) if (item.g.isConnected && !item.paused) item.tick(dt, now / 1000);
  if (mounted.size && !document.hidden) frameId = requestAnimationFrame(frame);
  else last = 0;
}
export function mount(item) {
  mounted.add(item);
  item.tick(0, 0);
  if (!frameId && !reduced) frameId = requestAnimationFrame(frame);
}
export function unmount(item) {
  mounted.delete(item);
}
// A paused symbol holds a still pose (used when the simulator is stopped).
export function setPaused(item, paused) {
  if (item.paused === paused) return;
  item.paused = paused;
  if (paused) item.tick(0, 0);
  else wake();
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && mounted.size && !frameId && !reduced) frameId = requestAnimationFrame(frame);
});

// Wake the loop after a data change (cheap when already running).
export function wake() {
  if (mounted.size && !frameId && !reduced && !document.hidden) frameId = requestAnimationFrame(frame);
}

function spokes(parent, radius, count) {
  const group = svgEl("g", { class: "pf-spin" }, parent);
  for (let i = 0; i < count; i++) {
    const a = (i / count) * Math.PI * 2;
    svgEl("line", { x1: 0, y1: 0, x2: Math.cos(a) * radius, y2: Math.sin(a) * radius, class: "pf-spoke" }, group);
  }
  return group;
}

function flameShape(parent, direction) {
  const flame = svgEl("path", { class: "pf-flame" }, parent);
  const core = svgEl("path", { class: "pf-flame pf-flame--core" }, parent);
  const draw = (length, flicker) => {
    const l = length * flicker;
    const path = (len, half) =>
      direction === "left"
        ? `M0,${-half} Q${-len * 0.55},${-half * 1.3} ${-len},0 Q${-len * 0.55},${half * 1.3} 0,${half} Z`
        : `M${-half},0 Q${-half * 1.3},${len * 0.55} 0,${len} Q${half * 1.3},${len * 0.55} ${half},0 Z`;
    flame.setAttribute("d", path(l, 7));
    core.setAttribute("d", path(l * 0.55, 3.5));
    const visible = length > 4;
    flame.style.display = core.style.display = visible ? "" : "none";
  };
  return { flame, core, draw };
}

const factories = {
  hopper(n) {
    const g = svgEl("g");
    svgEl("path", { d: `M0,0 H${n.w} L${n.w * 0.62},${n.h * 0.8} H${n.w * 0.38} Z`, class: "pf-body" }, g);
    svgEl("path", { d: `M8,10 H${n.w - 8} L${n.w * 0.6},${n.h * 0.75} H${n.w * 0.4} Z`, class: "pf-solid" }, g);
    svgEl("rect", { x: n.w * 0.38, y: n.h * 0.8, width: n.w * 0.24, height: n.h * 0.2, class: "pf-body" }, g);
    return { g, set() {}, tick() {} };
  },

  kiln(n) {
    const g = svgEl("g");
    const id = `clip-${Math.random().toString(36).slice(2, 8)}`;
    const clip = svgEl("clipPath", { id }, g);
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, rx: 14 }, clip);
    svgEl("rect", { x: -12, y: 12, width: 14, height: n.h - 24, class: "pf-body" }, g);
    svgEl("rect", { x: n.w - 2, y: 12, width: 16, height: n.h - 24, class: "pf-body" }, g);
    const shell = svgEl("g", { "clip-path": `url(#${id})` }, g);
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, class: "pf-shell" }, shell);
    const heat = svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, class: "pf-heat" }, shell);
    const bands = [];
    const gap = n.h / 6;
    for (let i = 0; i < 7; i++) bands.push(svgEl("rect", { x: 0, width: n.w, height: 5, class: "pf-band" }, shell));
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, rx: 14, class: "pf-outline" }, g);
    for (const x of [n.w * 0.2, n.w * 0.5, n.w * 0.8]) {
      svgEl("rect", { x: x - 6, y: -5, width: 12, height: n.h + 10, rx: 3, class: "pf-ring" }, g);
    }
    let phase = 0;
    let p = { heat: 0.5, spin: 0, halted: false };
    return {
      g,
      set(next) { p = { ...p, ...next }; heat.style.opacity = (0.1 + 0.7 * clamp01(p.heat)).toFixed(2); g.classList.toggle("is-halted", Boolean(p.halted)); },
      tick(dt) {
        phase = (phase + (p.halted ? 0 : p.spin) * dt * 26) % gap;
        bands.forEach((band, i) => band.setAttribute("y", (i * gap + phase - gap).toFixed(1)));
      },
    };
  },

  motor(n) {
    const g = svgEl("g");
    const cx = n.w / 2;
    svgEl("line", { x1: cx, y1: 0, x2: cx, y2: 62, class: "pf-shaft" }, g);
    svgEl("circle", { cx, cy: 8, r: 8, class: "pf-body" }, g);
    svgEl("circle", { cx, cy: 90, r: 30, class: "pf-body" }, g);
    const wheel = svgEl("g", { transform: `translate(${cx} 90)` }, g);
    const rotor = spokes(wheel, 24, 6);
    svgEl("circle", { cx, cy: 90, r: 6, class: "pf-hub" }, g);
    svgEl("text", { x: cx, y: 118, "text-anchor": "middle", class: "pf-glyph" }, g).textContent = "M";
    let angle = 0;
    let p = { spin: 0, halted: false };
    return {
      g,
      set(next) { p = { ...p, ...next }; g.classList.toggle("is-halted", Boolean(p.halted)); },
      tick(dt) {
        angle = (angle + (p.halted ? 0 : p.spin) * dt * 180) % 360;
        rotor.setAttribute("transform", `rotate(${angle.toFixed(1)})`);
      },
    };
  },

  burner(n) {
    const g = svgEl("g");
    const body = svgEl("path", { d: `M0,13 L22,8 H${n.w} V28 H22 L0,23 Z`, class: "pf-body" }, g);
    svgEl("line", { x1: 40, y1: 18, x2: n.w - 8, y2: 18, class: "pf-inner" }, g);
    const flame = svgEl("g", { transform: "translate(0 18)" }, g);
    const shape = flameShape(flame, "left");
    let level = 0;
    return {
      g,
      set(p) { level = clamp01(p.flame ?? 0); body.classList.toggle("is-faulted", Boolean(p.faulted)); },
      tick(dt, t) { shape.draw(level > 0.02 ? 16 + 78 * level : 0, 1 + 0.09 * Math.sin(t * 13)); },
    };
  },

  cooler(n) {
    const g = svgEl("g");
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, rx: 6, class: "pf-ghost" }, g);
    const heat = svgEl("rect", { x: 3, y: 3, width: n.w - 6, height: n.h - 6, rx: 4, class: "pf-heat" }, g);
    for (const x of [n.w * 0.3, n.w * 0.7]) svgEl("circle", { cx: x, cy: n.h / 2, r: 14, class: "pf-fan" }, g);
    return { g, set(p) { heat.style.opacity = (0.05 + 0.5 * clamp01(p.heat ?? 0)).toFixed(2); }, tick() {} };
  },

  furnace(n) {
    const g = svgEl("g");
    svgEl("rect", { x: 0, y: 0, width: n.w, height: 12, class: "pf-refractory" }, g);
    svgEl("rect", { x: 0, y: 0, width: 14, height: n.h - 32, class: "pf-refractory" }, g);
    svgEl("rect", { x: n.w - 14, y: 0, width: 14, height: n.h - 32, class: "pf-refractory" }, g);
    svgEl("rect", { x: 14, y: 12, width: n.w - 28, height: n.h - 18, class: "pf-furnace-in" }, g);
    const heat = svgEl("rect", { x: 14, y: 12, width: n.w - 28, height: n.h - 18, class: "pf-heat" }, g);
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, class: "pf-outline", fill: "none" }, g);
    return { g, set(p) { heat.style.opacity = (0.08 + 0.55 * clamp01(p.heat ?? 0.5)).toFixed(2); }, tick() {} };
  },

  burnerbank(n) {
    const g = svgEl("g");
    svgEl("rect", { x: 0, y: 15, width: n.w, height: 10, rx: 3, class: "pf-header" }, g);
    const flames = [];
    const nozzles = 5;
    for (let i = 0; i < nozzles; i++) {
      const x = 40 + i * ((n.w - 80) / (nozzles - 1));
      const nozzle = svgEl("path", { d: `M${x - 9},25 H${x + 9} L${x + 5},56 H${x - 5} Z`, class: "pf-body" }, g);
      const holder = svgEl("g", { transform: `translate(${x} 56)` }, g);
      flames.push({ nozzle, shape: flameShape(holder, "down") });
    }
    let level = 0;
    return {
      g,
      set(p) { level = clamp01(p.flame ?? 0); flames.forEach((f) => f.nozzle.classList.toggle("is-faulted", Boolean(p.faulted))); },
      tick(dt, t) {
        flames.forEach((f, i) => f.shape.draw(level > 0.02 ? 8 + 42 * level : 0, 1 + 0.1 * Math.sin(t * 12 + i * 1.7)));
      },
    };
  },

  rollers(n) {
    const g = svgEl("g");
    const wheels = [];
    const pitch = 46;
    for (let cx = 23; cx < n.w; cx += pitch) {
      const holder = svgEl("g", { transform: `translate(${cx} 13)` }, g);
      svgEl("circle", { r: 11, class: "pf-body" }, holder);
      wheels.push(spokes(holder, 9, 4));
    }
    let angle = 0;
    let p = { spin: 0, halted: false };
    return {
      g,
      set(next) { p = { ...p, ...next }; g.classList.toggle("is-halted", Boolean(p.halted)); },
      tick(dt) {
        angle = (angle + (p.halted ? 0 : p.spin) * dt * 160) % 360;
        for (const wheel of wheels) wheel.setAttribute("transform", `rotate(${angle.toFixed(1)})`);
      },
    };
  },

  billets(n) {
    const g = svgEl("g");
    const id = `clip-${Math.random().toString(36).slice(2, 8)}`;
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h }, svgEl("clipPath", { id }, g));
    const lane = svgEl("g", { "clip-path": `url(#${id})` }, g);
    const length = 110;
    const spacing = 184;
    const items = [];
    for (let i = 0; i < 6; i++) {
      const holder = svgEl("g", {}, lane);
      svgEl("rect", { x: 0, y: 2, width: length, height: n.h - 6, rx: 3, class: "pf-billet" }, holder);
      const glow = svgEl("rect", { x: 0, y: 2, width: length, height: n.h - 6, rx: 3, class: "pf-heat" }, holder);
      items.push({ holder, glow, offset: i * spacing });
    }
    const hot = [210, 670];
    const total = 6 * spacing;
    let travel = 0;
    let p = { speed: 0, halted: false, heat: 0.5 };
    const warmth = (x) => {
      const ramp = (x - hot[0] + 60) / 120;
      return clamp01(p.heat) * (x < hot[0] - 60 ? 0.08 : x < hot[0] + 60 ? 0.08 + 0.92 * clamp01(ramp) : 1);
    };
    return {
      g,
      set(next) { p = { ...p, ...next }; },
      tick(dt) {
        travel = (travel + (p.halted ? 0 : p.speed) * dt * 70) % total;
        for (const item of items) {
          const x = ((item.offset + travel) % total) - length;
          item.holder.setAttribute("transform", `translate(${x.toFixed(1)} 0)`);
          item.glow.style.opacity = warmth(x + length / 2).toFixed(2);
        }
      },
    };
  },

  vessel(n) {
    const g = svgEl("g");
    const id = `clip-${Math.random().toString(36).slice(2, 8)}`;
    const cx = n.w / 2;
    const body = `M20,52 A100,22 0 0 1 220,52 V238 A100,24 0 0 1 20,238 Z`;
    // Jacket sits behind the vessel; stubs connect the supply and return pipes.
    svgEl("rect", { x: 8, y: 96, width: 224, height: 150, rx: 12, class: "pf-jacket" }, g);
    svgEl("rect", { x: 232, y: 154, width: 20, height: 8, class: "pf-jacket" }, g);
    svgEl("rect", { x: 232, y: 238, width: 20, height: 8, class: "pf-jacket" }, g);
    const stream = svgEl("g", { class: "pf-jacket-flow" }, g);
    for (let i = 0; i < 6; i++) svgEl("path", { d: `M12,${104 + i * 24} h4 M224,${104 + i * 24} h4`, class: "pf-jacket-tick" }, stream);
    svgEl("path", { d: body, class: "pf-vessel" }, g);
    svgEl("clipPath", { id }, g).append(svgEl("path", { d: body }));
    const inner = svgEl("g", { "clip-path": `url(#${id})` }, g);
    const liquid = svgEl("rect", { x: 20, width: 200, class: "pf-liquid" }, inner);
    const glow = svgEl("rect", { x: 20, width: 200, class: "pf-heat" }, inner);
    const surface = svgEl("line", { x1: 20, x2: 220, class: "pf-surface" }, inner);
    const bubbles = [];
    for (let i = 0; i < 6; i++) bubbles.push({ node: svgEl("circle", { r: 2.4, class: "pf-bubble" }, inner), x: 50 + i * 28, seed: i * 0.37 });
    svgEl("path", { d: body, class: "pf-outline", fill: "none" }, g);
    svgEl("rect", { x: 4, y: 52, width: 18, height: 12, class: "pf-body" }, g);
    svgEl("rect", { x: cx - 6, y: 262, width: 12, height: 38, class: "pf-body" }, g);
    let p = { level: 0.6, heat: 0.5, flow: 0, spin: 0, halted: false };
    let rise = 0;
    let dash = 0;
    const place = () => {
      const top = 262 - 218 * clamp01(p.level);
      liquid.setAttribute("y", top.toFixed(1)); liquid.setAttribute("height", (270 - top).toFixed(1));
      glow.setAttribute("y", top.toFixed(1)); glow.setAttribute("height", (270 - top).toFixed(1));
      glow.style.opacity = (0.02 + 0.22 * clamp01(p.heat)).toFixed(2);
      surface.setAttribute("y1", top.toFixed(1)); surface.setAttribute("y2", top.toFixed(1));
    };
    return {
      g,
      set(next) { p = { ...p, ...next }; place(); },
      tick(dt) {
        const top = 262 - 218 * clamp01(p.level);
        rise += (p.halted ? 0.05 : 0.15 + p.spin) * dt * 60;
        for (const b of bubbles) {
          const span = Math.max(20, 262 - top - 12);
          b.node.setAttribute("cx", (b.x + Math.sin(rise * 0.08 + b.seed * 9) * 4).toFixed(1));
          b.node.setAttribute("cy", (258 - ((rise * 0.9 + b.seed * 140) % span)).toFixed(1));
        }
        dash = (dash + clamp01(p.flow) * dt * 40) % 24;
        stream.setAttribute("transform", `translate(0 ${dash.toFixed(1)})`);
      },
    };
  },

  agitator(n) {
    const g = svgEl("g");
    const cx = n.w / 2;
    svgEl("rect", { x: cx - 30, y: 0, width: 60, height: 34, rx: 6, class: "pf-body" }, g);
    svgEl("text", { x: cx, y: 23, "text-anchor": "middle", class: "pf-glyph" }, g).textContent = "M";
    svgEl("line", { x1: cx, y1: 34, x2: cx, y2: 204, class: "pf-shaft" }, g);
    const blade = svgEl("rect", { y: 200, height: 8, rx: 2, class: "pf-blade" }, g);
    const cross = svgEl("rect", { y: 200, height: 8, rx: 2, class: "pf-blade pf-blade--cross" }, g);
    let angle = 0;
    let p = { spin: 0, halted: false };
    return {
      g,
      set(next) { p = { ...p, ...next }; g.classList.toggle("is-halted", Boolean(p.halted)); },
      tick(dt) {
        angle = (angle + (p.halted ? 0 : p.spin) * dt * 5) % (Math.PI * 2);
        const a = Math.max(6, 74 * Math.abs(Math.cos(angle)));
        const b = Math.max(6, 74 * Math.abs(Math.sin(angle)));
        blade.setAttribute("x", (cx - a / 2).toFixed(1)); blade.setAttribute("width", a.toFixed(1));
        cross.setAttribute("x", (cx - b / 2).toFixed(1)); cross.setAttribute("width", b.toFixed(1));
      },
    };
  },

  valve(n) {
    const g = svgEl("g");
    svgEl("path", { d: `M0,${n.h * 0.25} L${n.w / 2},${n.h / 2} L0,${n.h * 0.75} Z M${n.w},${n.h * 0.25} L${n.w / 2},${n.h / 2} L${n.w},${n.h * 0.75} Z`, class: "pf-body" }, g);
    svgEl("line", { x1: n.w / 2, y1: n.h / 2, x2: n.w / 2, y2: 2, class: "pf-shaft" }, g);
    svgEl("rect", { x: n.w / 2 - 7, y: 0, width: 14, height: 5, class: "pf-body" }, g);
    return { g, set() {}, tick() {} };
  },

  pump(n) {
    const g = svgEl("g");
    svgEl("circle", { cx: n.w / 2, cy: n.h / 2, r: n.w * 0.42, class: "pf-body" }, g);
    svgEl("path", { d: `M${n.w * 0.38},${n.h * 0.3} L${n.w * 0.7},${n.h / 2} L${n.w * 0.38},${n.h * 0.7} Z`, class: "pf-hub" }, g);
    return { g, set() {}, tick() {} };
  },

  heater(n) {
    const g = svgEl("g");
    svgEl("rect", { x: 0, y: 0, width: n.w, height: n.h, rx: 10, class: "pf-body" }, g);
    svgEl("rect", { x: 10, y: 10, width: n.w - 20, height: n.h - 20, rx: 6, class: "pf-furnace-in" }, g);
    const holder = svgEl("g", { transform: `translate(${n.w / 2} ${n.h - 22})` }, g);
    const shape = flameShape(holder, "down");
    // The shared flame shape points downward; flip it so it burns upward inside the box.
    holder.setAttribute("transform", `translate(${n.w / 2} ${n.h - 22}) scale(1 -1)`);
    svgEl("text", { x: n.w / 2, y: 20, "text-anchor": "middle", class: "pf-glyph pf-glyph--small" }, g).textContent = "HEAT";
    let level = 0;
    return {
      g,
      set(p) { level = clamp01(p.flame ?? 0); g.classList.toggle("is-faulted", Boolean(p.faulted)); },
      tick(dt, t) { shape.draw(level > 0.02 ? 10 + 62 * level : 0, 1 + 0.09 * Math.sin(t * 11)); },
    };
  },
};

export function createSymbol(node) {
  const make = factories[node.kind];
  if (!make) throw new Error(`Unknown symbol: ${node.kind}`);
  return make(node);
}
