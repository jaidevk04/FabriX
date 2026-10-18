const NS = "http://www.w3.org/2000/svg";
const svgNode = (tag, attrs, text) => {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (text !== undefined) node.textContent = text;
  return node;
};
const el = (tag, className, text) => {
  const node = document.createElement(tag); node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const point = (angle, radius = 43) => [70 + Math.cos(angle * Math.PI / 180) * radius, 57 + Math.sin(angle * Math.PI / 180) * radius];
const arc = (start, end, radius = 43) => {
  const a = point(start, radius), b = point(end, radius);
  return `M ${a.join(" ")} A ${radius} ${radius} 0 ${end-start > 180 ? 1 : 0} 1 ${b.join(" ")}`;
};
function drawing(metric) {
  const {minimum, maximum, value, kind, band, condition} = metric;
  const ratio = v => Math.max(0, Math.min(1, (v - minimum) / (maximum - minimum)));
  const p = value === null ? 0 : ratio(value);
  const color = condition === "unavailable" ? "#93a3af" : condition === "outside_band" ? "#b77a28" : "#287e9b";
  const svg = svgNode("svg", {viewBox:"0 0 140 110", class:"process-gauge", "aria-hidden":"true"});
  if (kind === "dial" || kind === "rotor") {
    svg.append(svgNode("path", {d:arc(150,390), fill:"none", stroke:"#e4edf2", "stroke-width":8, "stroke-linecap":"round"}),
      svgNode("path", {d:arc(150 + ratio(band[0])*240,150 + ratio(band[1])*240), fill:"none", stroke:"#a7cbbd", "stroke-width":8}));
    for (let i = 0; i <= 8; i++) {
      const a = point(150 + i * 30, 34), b = point(150 + i * 30, 38);
      svg.append(svgNode("line", {x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:"#7891a2", "stroke-width":1}));
    }
    if (value !== null) {
      const needle = point(150 + p*240,32);
      svg.append(svgNode("line",{x1:70,y1:57,x2:needle[0],y2:needle[1],stroke:color,"stroke-width":2.5,"stroke-linecap":"round"}),svgNode("circle",{cx:70,cy:57,r:4,fill:color}));
    }
    if (kind === "rotor") svg.append(svgNode("path",{d:"M67 18 l3 -5 3 5 M103 54 l5 3 -5 3 M70 96 l-3 -5 6 0",fill:color}));
    svg.append(svgNode("text",{x:22,y:104,"text-anchor":"middle",class:"gauge-scale"},minimum),svgNode("text",{x:118,y:104,"text-anchor":"middle",class:"gauge-scale"},maximum));
  } else if (kind === "ring") {
    const circumference = 2*Math.PI*35;
    svg.append(svgNode("circle",{cx:70,cy:53,r:35,fill:"none",stroke:"#e4edf2","stroke-width":8}),
      svgNode("circle",{cx:70,cy:53,r:35,fill:"none",stroke:color,"stroke-width":8,"stroke-linecap":"round", "stroke-dasharray":`${p*circumference} ${circumference}`,transform:"rotate(-90 70 53)"}),
      svgNode("text",{x:70,y:59,"text-anchor":"middle",class:"gauge-center"},metric.id === "oxygen" ? "O₂" : "%"));
  } else if (kind === "tank") {
    const y = 88-p*66;
    svg.append(svgNode("rect",{x:43,y:17,width:54,height:76,rx:11,fill:"#f3f7fa",stroke:"#a3b6c5","stroke-width":2}),
      svgNode("rect",{x:47,y,width:46,height:Math.max(0,88-y),rx:5,fill:color,opacity:0.7}));
    for (const limit of band) svg.append(svgNode("line",{x1:38,y1:88-ratio(limit)*66,x2:102,y2:88-ratio(limit)*66,stroke:"#739d8d","stroke-dasharray":"3 3"}));
    svg.append(svgNode("path",{d:"M61 12 v-6 h18 v6 M69 94 v9",fill:"none",stroke:"#617d91","stroke-width":3}));
  } else if (kind === "thermometer") {
    svg.append(svgNode("rect",{x:61,y:12,width:18,height:73,rx:9,fill:"#e4edf2"}),
      svgNode("rect",{x:54,y:80-ratio(band[1])*61,width:32,height:(ratio(band[1])-ratio(band[0]))*61,fill:"#b8d7c8",opacity:0.8}),
      svgNode("rect",{x:67,y:80-p*61,width:6,height:p*61+5,rx:3,fill:color}),
      svgNode("circle",{cx:70,cy:89,r:11,fill:color}));
    for(let i=0;i<5;i++) svg.append(svgNode("line",{x1:45,y1:18+i*15,x2:54,y2:18+i*15,stroke:"#8198a9"}));
  } else {
    svg.append(svgNode("path",{d:"M15 35 v19 h110 v-19 M15 76 v-10 h110 v10",fill:"none",stroke:"#a5bbc9","stroke-width":3}),
      svgNode("rect",{x:16,y:56,width:108,height:8,rx:4,fill:"#e4edf2"}),
      svgNode("rect",{x:16,y:56,width:p*108,height:8,rx:4,fill:color}));
    const flow = svgNode("g", {class:"gauge-flow"});
    for(let i=-1;i<3;i++) flow.append(svgNode("path",{d:`M${40+i*26} 41 l7 4 -7 4`,fill:"none",stroke:color,"stroke-width":2}));
    svg.append(flow);
    svg.append(svgNode("text",{x:16,y:96,class:"gauge-scale"},minimum),svgNode("text",{x:124,y:96,"text-anchor":"end",class:"gauge-scale"},maximum));
  }
  return svg;
}
let lastData;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const cards = new Map();
let plantKey = null;
let loop = 0;
const HISTORY = 30;
const fmt = metric => Number(metric.value).toLocaleString(undefined,{maximumFractionDigits:metric.unit === "rpm" || metric.unit === "bar" || metric.id === "oxygen" ? 2 : 1});
const ratioOf = (metric, value) => Math.max(0, Math.min(1, (value - metric.minimum) / (metric.maximum - metric.minimum)));
function sparkline(card) {
  const {metric, history} = card;
  const svg = svgNode("svg", {viewBox:"0 0 100 18", class:"process-trend", "aria-hidden":"true", preserveAspectRatio:"none"});
  if (history.length > 1) {
    const step = 100 / (HISTORY - 1), offset = (HISTORY - history.length) * step;
    const pts = history.map((v, i) => `${(offset + i * step).toFixed(1)},${(16 - ratioOf(metric, v) * 14).toFixed(1)}`);
    svg.append(svgNode("polyline", {points:pts.join(" "), fill:"none", stroke:"#588fb6", "stroke-width":1.4, "vector-effect":"non-scaling-stroke"}));
  }
  card.trend.replaceWith(svg); card.trend = svg;
}
function paint(card) {
  const shown = card.metric.value === null ? null : card.shown;
  const view = {...card.metric, value: shown};
  const next = drawing(view);
  card.gauge.replaceWith(next); card.gauge = next;
  card.text.nodeValue = shown === null ? "—" : fmt(view);
}
function frame(time) {
  loop = 0;
  const dt = Math.min((time - (frame.last ?? time)) / 1000, 0.1);
  frame.last = time;
  let busy = false;
  for (const card of cards.values()) {
    const {metric} = card;
    if (metric.value === null) continue;
    const diff = metric.value - card.shown;
    if (Math.abs(diff) > (metric.maximum - metric.minimum) * 0.001) {
      card.shown += diff * Math.min(1, dt * 5);
      paint(card);
    } else if (card.shown !== metric.value) {
      card.shown = metric.value; paint(card);
    }
    const p = ratioOf(metric, card.shown);
    const flow = card.gauge.querySelector(".gauge-flow");
    if (flow) {
      card.flow = (card.flow + dt * (6 + p * 70)) % 26;
      flow.setAttribute("transform", `translate(${card.flow.toFixed(1)} 0)`);
      busy = true;
    }
    if (card.shown !== metric.value) busy = true;
  }
  if (busy && !document.hidden) loop = requestAnimationFrame(frame);
}
function wake() {
  if (!loop && !reduced) { frame.last = undefined; loop = requestAnimationFrame(frame); }
}
export function industryInstruments(data) {
  const host = document.getElementById("process-instrument-grid");
  const fingerprint = JSON.stringify(data);
  if (fingerprint === lastData) return;
  lastData = fingerprint;
  if (!data) {
    document.getElementById("process-instruments-source").textContent = "Updating…";
    return;
  }
  const clock = Number.isFinite(data.sim_seconds) ? ` · sim ${Math.floor(data.sim_seconds / 60)}m ${Math.floor(data.sim_seconds % 60)}s` : "";
  document.getElementById("process-instruments-source").textContent = `Snapshot r${data.revision}${clock} · simulated estimates`;
  const signature = data.plant_id + ":" + data.indicators.map(m => m.id).join(",");
  if (signature !== plantKey) {
    plantKey = signature; cards.clear(); host.replaceChildren();
    for (const metric of data.indicators) {
      const button = el("div", "process-instrument"); button.setAttribute("role", "group"); button.dataset.metric = metric.id;
      const reading = el("span", "process-value"); const text = document.createTextNode("");
      reading.append(text, el("small", "process-unit", metric.unit));
      const card = {metric, text, button, shown: metric.value ?? 0, flow: 0, history: [], reading,
        gauge: drawing(metric), trend: svgNode("svg", {}), condition: el("span", "process-condition", "")};
      button.append(el("span", "process-name", metric.name), card.gauge, reading, card.trend, card.condition);
      cards.set(metric.id, card); host.append(button);
    }
  }
  const advanced = data.sim_seconds !== undefined && data.sim_seconds !== host.dataset.sim;
  host.dataset.sim = String(data.sim_seconds);
  for (const metric of data.indicators) {
    const card = cards.get(metric.id);
    card.metric = metric;
    card.button.className = `process-instrument ${metric.condition}`;
    card.button.setAttribute("aria-label",`${metric.name}: ${metric.value === null ? "unavailable" : metric.value + " " + metric.unit}. ${metric.condition.replaceAll("_"," ")}.`);
    card.button.title = `${metric.name}: ${metric.explanation} Band ${metric.band[0]}–${metric.band[1]} ${metric.unit}.`;
    card.condition.textContent = metric.condition === "unavailable" ? "Signal unavailable" : metric.condition === "outside_band" ? "Outside band" : "Within band";
    if (metric.value === null) { card.history = []; paint(card); sparkline(card); continue; }
    if (reduced) card.shown = metric.value;
    if (advanced || !card.history.length) card.history = [...card.history, metric.value].slice(-HISTORY);
    paint(card); sparkline(card);
  }
  wake();
}
