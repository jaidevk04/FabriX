// Learning core workspace: the live signal rack. Reads simulated channels and waveform windows, draws a
// scrolling trace, a spectrum and a spectrogram per waveform channel, and a learned-band gauge per channel.
// Read only. Waveform samples stay in the browser; agents only ever receive the extracted features.
import { ALERT_LEVEL, STATUS_LEVEL, badge, chip, el, http, lamp, number, sparkline } from "./cores-parts.js";

const WINDOW_N = 256;
const SHOWN = 240; // samples visible in the trace
const BINS = WINDOW_N / 2;
const HISTORY = 90;
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

// ---------- small signal helpers ----------
function fftMagnitudes(samples) {
  const n = WINDOW_N;
  const re = new Float64Array(n);
  const im = new Float64Array(n);
  const offset = Math.max(0, samples.length - n);
  for (let i = 0; i < n; i++) re[i] = (samples[offset + i] ?? 0) * (0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)));
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; }
  }
  for (let size = 2; size <= n; size <<= 1) {
    const angle = (-2 * Math.PI) / size;
    for (let start = 0; start < n; start += size) {
      for (let k = 0; k < size / 2; k++) {
        const wr = Math.cos(angle * k);
        const wi = Math.sin(angle * k);
        const a = start + k;
        const b = a + size / 2;
        const tr = re[b] * wr - im[b] * wi;
        const ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
      }
    }
  }
  const out = new Float32Array(BINS);
  for (let i = 1; i < BINS; i++) out[i] = Math.hypot(re[i], im[i]) / n;
  return out;
}

// Light-theme spectrogram ramp: pale steel, slate blue, amber, red.
const RAMP = [[0, [240, 244, 249]], [0.3, [190, 214, 232]], [0.55, [88, 143, 182]], [0.78, [226, 160, 62]], [1, [205, 70, 58]]];
function heat(v) {
  const t = Math.max(0, Math.min(1, v));
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const [t0, c0] = RAMP[i - 1];
      const [t1, c1] = RAMP[i];
      const f = (t - t0) / (t1 - t0 || 1);
      return c0.map((c, k) => Math.round(c + (c1[k] - c) * f));
    }
  }
  return RAMP.at(-1)[1];
}

// Learned band: safe up to 56 %, watch up to 78 %, anomaly above. Thresholds come from the channel definition.
function bandPosition(r) {
  const { high, low, nominal, value } = r;
  if (high === null && low === null) return null;
  // Distance from nominal towards the limit, mapped onto safe / watch / anomaly. Low-side limits are mirrored.
  const climb = (x, nom, edge) => {
    const gap = edge - nom || 1;
    const warn = nom + gap * 0.6;
    if (x <= nom) return 0.04 + 0.12 * Math.max(0, 1 - (nom - x) / Math.abs(gap));
    if (x <= warn) return 0.16 + 0.4 * ((x - nom) / (warn - nom));
    if (x <= edge) return 0.56 + 0.22 * ((x - warn) / (edge - warn));
    return Math.min(0.985, 0.78 + 0.22 * ((x - edge) / (Math.abs(gap) * 0.5)));
  };
  const upper = high !== null && (low === null || value >= nominal);
  return upper ? climb(value, nominal, high) : climb(-value, -nominal, -low);
}

function canvasFor(canvas) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return null;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.dataset.reset = "true";
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h, dpr };
}

const LEVEL_COLOR = { ok: "--ok", warn: "--warn", crit: "--bad", info: "--brand", off: "--text-3" };

export function createLearningView({ base, onSelect }) {
  const root = el("div", "lv");
  let channels = new Map(); // id -> row state
  let order = [];
  let selected = null;
  let running = false;
  let frame = 0;
  let last = 0;
  let fetching = false;
  let lastTick = -1;
  let flagged = new Map();
  let last_data = null;
  let evidence = [];
  let selectedFeatures = null;
  let generation = 0;
  let seeded = Promise.resolve();
  const history = new Map();

  // ---------- skeleton ----------
  const head = el("header", "lv-head");
  const headText = el("div", "lv-head-text");
  headText.append(el("h3", "", "Incoming signals"), el("p", "cr-sub", "Simulated channels generated from plant state and active events"));
  const headChips = el("div", "lv-head-chips");
  head.append(headText, headChips);
  const strip = el("div", "lv-strip");
  const rack = el("section", "lv-rack");
  rack.setAttribute("aria-label", "Signal rack");
  const headings = el("div", "lv-row lv-row--head");
  for (const text of ["Channel", "Time series · live", "Spectrum", "Spectrogram · newest at top", "Learned band"]) headings.append(el("span", "", text));
  const rows = el("div", "lv-rows");
  rack.append(headings, rows);
  const detail = el("div", "lv-detail");
  const featureCard = el("section", "lv-card");
  const evidenceCard = el("section", "lv-card");
  detail.append(featureCard, evidenceCard);
  root.append(head, strip, rack, detail);

  // ---------- rows ----------
  function buildRow(reading) {
    const row = el("article", "lv-row");
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `Select ${reading.name}`);
    const meta = el("div", "lv-meta");
    const top = el("div", "lv-meta-top");
    const pill = el("span", "lv-state");
    top.append(lamp("ok"), el("strong", "lv-id", reading.channel.replaceAll("_", " ")), pill);
    const chips = el("div", "cr-chips");
    chips.append(el("span", "lv-chip", reading.unit), el("span", "lv-chip", reading.modality));
    const rate = el("span", "lv-chip");
    rate.hidden = true;
    chips.append(rate);
    meta.append(top, el("div", "lv-name", reading.name), el("div", "cr-sub", reading.equipment), chips);
    const cell = (label) => {
      const wrap = el("div", "lv-cell");
      const canvas = el("canvas", "lv-canvas");
      wrap.append(canvas);
      return { wrap, canvas, label };
    };
    const trace = cell("time series");
    const spectrum = cell("spectrum");
    const wave = cell("spectrogram");
    const band = el("div", "lv-bandwrap");
    const track = el("div", "lv-band");
    track.append(el("i", "lv-z lv-z--ok"), el("i", "lv-z lv-z--w"), el("i", "lv-z lv-z--a"));
    const marker = el("i", "lv-mk");
    track.append(marker);
    const scale = el("div", "lv-scale");
    scale.append(el("span", "", "safe"), el("span", "", "watch"), el("span", "", "anomaly"));
    const valueLine = el("div", "lv-value");
    const value = el("strong", "lv-num");
    const unit = el("span", "", ` ${reading.unit}`);
    valueLine.append(value, unit);
    const mini = el("div", "lv-mini");
    band.append(valueLine, track, scale, mini);
    if (reading.modality === "waveform") row.append(meta, trace.wrap, spectrum.wrap, wave.wrap, band);
    else {
      const wide = el("div", "lv-cell lv-cell--wide");
      wide.append(trace.canvas);
      row.append(meta, wide, band);
      row.dataset.scalar = "true";
    }
    row.addEventListener("click", () => choose(reading.channel));
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(reading.channel); } });
    return {
      id: reading.channel, row, pill, rate, value, marker, mini, lampEl: top.firstChild,
      trace: trace.canvas, spectrum: spectrum.canvas, wave: wave.canvas,
      kind: reading.modality, reading, pendingRows: [],
      buf: [], pos: 0, spec: new Float32Array(BINS), specTarget: new Float32Array(BINS), specMax: 1e-6,
      scale: 1, lastWaveAt: 0, tick: -1, rateHz: null, level: "ok",
    };
  }

  function choose(id) {
    selected = id;
    for (const ch of channels.values()) ch.row.dataset.selected = String(ch.id === id);
    onSelect?.(id);
    fetchFeatures(id);
    renderDetail();
  }

  // ---------- data ----------
  function recordHistory(data) {
    if (data.tick === lastTick) return;
    lastTick = data.tick;
    for (const s of data.signals) {
      const list = history.get(s.channel) ?? [];
      list.push(s.value);
      if (list.length > HISTORY) list.shift();
      history.set(s.channel, list);
    }
  }

  function levelFor(reading) {
    return flagged.get(reading.channel) ?? STATUS_LEVEL[reading.status] ?? "ok";
  }

  async function fetchWindows() {
    if (fetching) return;
    fetching = true;
    const token = generation;
    try {
      await seeded;
      if (token !== generation) return;
      const waveforms = [...channels.values()].filter((c) => c.kind === "waveform");
      const results = await Promise.all(waveforms.map((c) => http("GET", `${base()}/signals/${c.id}/window?n=${WINDOW_N}`).catch(() => null)));
      if (token !== generation) return;
      results.forEach((data, index) => {
        const ch = waveforms[index];
        if (!data) return;
        if (ch.id === selected) { selectedFeatures = data.features; renderFeatures(); }
        if (data.features.tick === ch.tick) return;
        ch.tick = data.features.tick;
        ch.rateHz = data.rate_hz;
        ch.rate.textContent = `${number(data.rate_hz, 0)} Hz`;
        ch.rate.hidden = false;
        ch.buf.push(...data.samples);
        if (ch.buf.length > 1400) { const cut = ch.buf.length - 900; ch.buf.splice(0, cut); ch.pos = Math.max(0, ch.pos - cut); }
        ch.specTarget = fftMagnitudes(data.samples);
        if (!ch.buf.length || ch.pos === 0) ch.pos = Math.max(0, ch.buf.length - WINDOW_N);
      });
    } finally { fetching = false; }
  }

  // Replays what the server recorded while the world ran, so leaving and returning keeps the picture.
  async function loadHistory() {
    const token = generation;
    try {
      const data = await http("GET", `${base()}/signals/history`);
      if (token !== generation) return;
      history.clear();
      for (const entry of data.ticks) {
        for (const [channel, value] of Object.entries(entry.values)) {
          const list = history.get(channel) ?? [];
          list.push(value);
          history.set(channel, list);
        }
      }
      if (data.ticks.length) lastTick = data.ticks.at(-1).tick;
      for (const ch of channels.values()) {
        if (ch.kind !== "waveform") continue;
        const frames = data.windows.filter((w) => w.samples[ch.id]);
        if (!frames.length) continue;
        ch.buf = frames.flatMap((w) => w.samples[ch.id]);
        ch.pos = Math.max(0, ch.buf.length - WINDOW_N);
        ch.tick = frames.at(-1).tick;
        ch.rateHz = data.rates[ch.id] ?? null;
        if (ch.rateHz) { ch.rate.textContent = `${number(ch.rateHz, 0)} Hz`; ch.rate.hidden = false; }
        const spectra = frames.map((w) => fftMagnitudes(w.samples[ch.id]));
        ch.specMax = Math.max(1e-6, ...spectra.map((sp) => Math.max(...sp)));
        ch.specTarget = spectra.at(-1);
        ch.spec = Float32Array.from(spectra.at(-1));
        ch.pendingRows = spectra;
      }
      if (last_data) { paint(last_data); renderStrip(last_data); }
    } catch { /* live data still arrives; only the replay is missing */ }
  }

  async function fetchFeatures(id) {
    const ch = channels.get(id);
    if (!ch || ch.kind !== "waveform") { selectedFeatures = null; renderFeatures(); return; }
    try {
      const data = await http("GET", `${base()}/signals/${id}/window?n=${WINDOW_N}`);
      if (selected === id) { selectedFeatures = data.features; renderFeatures(); }
    } catch { /* the next poll retries */ }
  }

  // ---------- drawing ----------
  function drawTrace(ch, dt) {
    const g = canvasFor(ch.trace);
    if (!g) return;
    const { ctx, w, h } = g;
    ctx.clearRect(0, 0, w, h);
    const color = css(LEVEL_COLOR[ch.level], "#2d6a94");
    ctx.strokeStyle = css("--border", "#e4e8ee");
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(0, (h / 4) * i); ctx.lineTo(w, (h / 4) * i); ctx.stroke(); }
    ctx.font = "9px ui-monospace, monospace";
    ctx.fillStyle = css("--text-3", "#66768b");
    if (ch.kind === "waveform") {
      // Consume buffered samples at the pace they arrive, a little faster when the backlog grows.
      const ahead = ch.buf.length - ch.pos;
      const speed = WINDOW_N * (ahead > 2 * WINDOW_N ? 1.5 : ahead < 64 ? 0.4 : 1);
      if (ahead > 1) ch.pos = Math.min(ch.buf.length - 1, ch.pos + speed * dt);
      const end = Math.floor(ch.pos);
      const start = Math.max(0, end - SHOWN);
      const slice = ch.buf.slice(start, end);
      if (slice.length < 2) return;
      const peak = Math.max(...slice.map(Math.abs), 1e-6) * 1.15;
      ch.scale += (peak - ch.scale) * 0.06;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.3;
      ctx.lineJoin = "round";
      ctx.beginPath();
      slice.forEach((v, i) => {
        const x = (i / (SHOWN - 1)) * w;
        const y = h / 2 - (v / ch.scale) * (h / 2 - 4);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.fillText(`±${number(ch.scale, 2)} ${ch.reading.unit}`, w - 66, 11);
    } else {
      const series = history.get(ch.id) ?? [];
      const r = ch.reading;
      const marks = [r.nominal, r.high, r.low].filter((v) => v !== null && v !== undefined);
      const lo = Math.min(...series, ...marks);
      const hi = Math.max(...series, ...marks);
      const span = hi - lo || 1;
      const y = (v) => h - 6 - ((v - lo) / span) * (h - 14);
      ctx.setLineDash([4, 4]);
      for (const [v, name] of [[r.high, "limit"], [r.low, "limit"], [r.nominal, "nominal"]]) {
        if (v === null || v === undefined) continue;
        ctx.strokeStyle = name === "limit" ? css("--warn", "#a8610d") : css("--text-3", "#66768b");
        ctx.globalAlpha = 0.6;
        ctx.beginPath(); ctx.moveTo(0, y(v)); ctx.lineTo(w, y(v)); ctx.stroke();
        ctx.globalAlpha = 1;
      }
      ctx.setLineDash([]);
      if (series.length > 1) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.6;
        ctx.lineJoin = "round";
        ctx.beginPath();
        series.forEach((v, i) => {
          const x = (i / (HISTORY - 1)) * w + (w - (series.length / HISTORY) * w);
          if (i === 0) ctx.moveTo(x, y(v)); else ctx.lineTo(x, y(v));
        });
        ctx.stroke();
        ctx.fillStyle = color;
        ctx.beginPath(); ctx.arc(w - 1, y(series.at(-1)), 3, 0, Math.PI * 2); ctx.fill();
      }
    }
  }

  function drawSpectrum(ch) {
    const g = canvasFor(ch.spectrum);
    if (!g) return;
    const { ctx, w, h } = g;
    ctx.clearRect(0, 0, w, h);
    let peakBin = 0;
    for (let i = 0; i < BINS; i++) {
      ch.spec[i] += (ch.specTarget[i] - ch.spec[i]) * 0.22;
      if (ch.spec[i] > ch.spec[peakBin]) peakBin = i;
    }
    ch.specMax = Math.max(ch.specMax * 0.985, ch.spec[peakBin], 1e-6);
    const color = css(LEVEL_COLOR[ch.level], "#2d6a94");
    ctx.strokeStyle = css("--border", "#e4e8ee");
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i++) { ctx.beginPath(); ctx.moveTo((w / 5) * i, 0); ctx.lineTo((w / 5) * i, h - 12); ctx.stroke(); }
    const floor = h - 14;
    const pt = (i) => [(i / (BINS - 1)) * w, floor - Math.min(1, ch.spec[i] / ch.specMax) * (floor - 6)];
    const gradient = ctx.createLinearGradient(0, 0, 0, floor);
    gradient.addColorStop(0, `${color}66`);
    gradient.addColorStop(1, `${color}10`);
    ctx.beginPath();
    ctx.moveTo(0, floor);
    for (let i = 0; i < BINS; i++) ctx.lineTo(...pt(i));
    ctx.lineTo(w, floor);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.beginPath();
    for (let i = 0; i < BINS; i++) { const [x, y] = pt(i); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.font = "9px ui-monospace, monospace";
    ctx.fillStyle = css("--text-3", "#66768b");
    const nyquist = (ch.rateHz ?? 0) / 2;
    ctx.fillText("0", 2, h - 2);
    if (nyquist) {
      ctx.fillText(`${number(nyquist / 2, 0)} Hz`, w / 2 - 14, h - 2);
      ctx.fillText(`${number(nyquist, 0)}`, w - 26, h - 2);
      const [px, py] = pt(peakBin);
      ctx.fillStyle = color;
      ctx.fillRect(px - 1, py, 2, floor - py);
      ctx.fillText(`${number((peakBin / (BINS - 1)) * nyquist, 0)} Hz`, Math.min(w - 44, Math.max(2, px + 4)), Math.max(10, py - 2));
    }
  }

  function drawWaterfall(ch, now) {
    const g = canvasFor(ch.wave);
    if (!g) return;
    const { ctx, w, h, dpr } = g;
    if (ch.wave.dataset.reset === "true") {
      ctx.fillStyle = "#f0f4f9";
      ctx.fillRect(0, 0, w, h);
      ch.wave.dataset.reset = "false";
    }
    const rowH = Math.max(1, Math.round(dpr));
    // Replay recorded spectra first (oldest to newest), several rows each so the span looks continuous.
    while (ch.pendingRows.length) {
      const spec = ch.pendingRows.shift();
      for (let n = 0; n < 6; n++) paintWaveRow(ctx, ch, spec, rowH);
    }
    if (now - ch.lastWaveAt < 140) return;
    ch.lastWaveAt = now;
    paintWaveRow(ctx, ch, ch.spec, rowH);
  }

  function paintWaveRow(ctx, ch, spec, rowH) {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(ch.wave, 0, 0, ch.wave.width, ch.wave.height - rowH, 0, rowH, ch.wave.width, ch.wave.height - rowH);
    const line = ctx.createImageData(ch.wave.width, rowH);
    const floorValue = ch.specMax * 0.04;
    for (let x = 0; x < ch.wave.width; x++) {
      const bin = Math.min(BINS - 1, Math.floor((x / ch.wave.width) * BINS));
      const v = Math.pow(Math.max(0, (spec[bin] - floorValue) / (ch.specMax - floorValue || 1)), 0.6);
      const [r, gr, b] = heat(v);
      for (let y = 0; y < rowH; y++) {
        const i = (y * ch.wave.width + x) * 4;
        line.data[i] = r; line.data[i + 1] = gr; line.data[i + 2] = b; line.data[i + 3] = 255;
      }
    }
    ctx.putImageData(line, 0, 0);
    ctx.restore();
  }

  function drawAll(now, dt) {
    for (const ch of channels.values()) {
      drawTrace(ch, dt);
      if (ch.kind === "waveform") { drawSpectrum(ch); drawWaterfall(ch, now); }
    }
  }

  function loop(now) {
    if (!running) return;
    const dt = Math.min(0.1, (now - (last || now)) / 1000);
    last = now;
    if (!document.hidden) drawAll(now, dt);
    frame = requestAnimationFrame(loop);
  }

  // ---------- readouts ----------
  const LABEL = { ok: "Normal", warn: "Watch", crit: "Alarm", info: "Normal", off: "Off" };
  function paint(data) {
    for (const reading of data.signals.filter((s) => s.modality !== "event")) {
      const ch = channels.get(reading.channel);
      if (!ch) continue;
      ch.reading = reading;
      const level = levelFor(reading);
      ch.level = level;
      ch.row.dataset.level = level;
      ch.pill.textContent = LABEL[level] ?? "Normal";
      ch.value.textContent = number(reading.value, reading.value >= 100 ? 1 : 2);
      const position = bandPosition(reading);
      ch.row.querySelector(".lv-band").dataset.empty = String(position === null);
      ch.marker.style.left = `${(position ?? 0.04) * 100}%`;
      ch.marker.hidden = position === null;
      ch.mini.replaceChildren(sparkline(history.get(reading.channel) ?? [], { width: 160, height: 24, level }));
      ch.lampEl.dataset.level = level;
    }
  }

  function renderStrip(data) {
    const groups = new Map();
    for (const s of data.signals.filter((x) => x.modality !== "event")) {
      const list = groups.get(s.equipment) ?? [];
      list.push(s);
      groups.set(s.equipment, list);
    }
    const tiles = [...groups].map(([equipment, list]) => {
      const levels = list.map(levelFor);
      const level = levels.includes("crit") ? "crit" : levels.includes("warn") ? "warn" : "ok";
      const lead = list.find((s) => s.modality === "waveform") ?? list[0];
      const tile = el("button", "lv-tile");
      tile.type = "button";
      tile.dataset.level = level;
      const top = el("div", "lv-tile-top");
      top.append(lamp(level), el("span", "lv-tile-name", equipment), el("span", "lv-tile-state", LABEL[level]));
      const mid = el("div", "lv-tile-mid");
      const value = el("div", "lv-tile-value");
      value.append(el("strong", "", number(lead.value, 2)), el("span", "", ` ${lead.unit}`));
      mid.append(value, sparkline(history.get(lead.channel) ?? [], { width: 96, height: 28, level }));
      tile.append(top, mid, el("span", "lv-tile-foot", `${list.length} channel${list.length === 1 ? "" : "s"} · ${lead.name}`));
      tile.addEventListener("click", () => {
        choose(lead.channel);
        channels.get(lead.channel)?.row.scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
      });
      return tile;
    });
    const signature = JSON.stringify(tiles.map((t) => t.textContent + t.dataset.level));
    if (strip.dataset.sig !== signature) { strip.dataset.sig = signature; strip.replaceChildren(...tiles); }
  }

  function renderHeadChips(data) {
    const live = chip(`live · tick ${data.tick}`, "ok", "Updated once per second from the plant state");
    live.classList.add("lv-live");
    const counts = { warn: 0, crit: 0 };
    for (const s of data.signals) { const level = levelFor(s); if (level in counts) counts[level] += 1; }
    const all = data.signals.filter((s) => s.modality !== "event").length;
    const waves = data.signals.filter((s) => s.modality === "waveform").length;
    headChips.replaceChildren(
      live,
      chip(`${all} channels · ${waves} waveform`, "info"),
      counts.crit ? chip(`${counts.crit} alarm`, "crit") : counts.warn ? chip(`${counts.warn} watch`, "warn") : chip("all normal", "ok"),
      badge("SIM", "Simulated channels, not recorded sensor data"),
    );
    const interlock = data.signals.find((s) => s.modality === "event");
    if (interlock?.value) headChips.append(chip("Interlock active", "crit", "Reflexive layer holds the plant. Cognitive control is blocked."));
  }

  function renderFeatures() {
    const ch = selected ? channels.get(selected) : null;
    if (!ch) { featureCard.replaceChildren(el("h4", "cr-mini", "Selected channel"), el("p", "cr-empty", "Select a channel row or equipment tile to see its extracted features.")); return; }
    const r = ch.reading;
    const wrap = el("div", "lv-feat");
    const stat = (label, value, unit = "") => {
      const item = el("div", "lv-stat");
      item.append(el("span", "lv-stat-label", label), el("strong", "lv-stat-value", `${value}${unit ? ` ${unit}` : ""}`));
      return item;
    };
    wrap.append(stat("Value", number(r.value, 2), r.unit), stat("Nominal", number(r.nominal, 2), r.unit));
    if (r.high !== null) wrap.append(stat("High limit", number(r.high, 2), r.unit));
    if (r.low !== null) wrap.append(stat("Low limit", number(r.low, 2), r.unit));
    const f = selectedFeatures;
    if (ch.kind === "waveform" && f) {
      wrap.append(stat("RMS", number(f.rms, 3)), stat("Peak", number(f.peak, 3)), stat("Crest factor", number(f.crest, 2)), stat("Kurtosis", number(f.kurtosis, 2)), stat("Dominant", number(f.dominant_hz, 0), "Hz"), stat("Sample rate", number(f.rate_hz, 0), "Hz"));
    }
    const title = el("div", "lv-card-head");
    title.append(el("h4", "cr-mini", `Selected channel · ${r.name}`), badge("CALC", "Features computed from a simulated waveform window"));
    featureCard.replaceChildren(title, wrap, el("p", "cr-note", ch.kind === "waveform" ? "Agents only receive these features, never the raw samples." : "Scalar channel: agents receive the value and its history."));
  }

  function renderEvidence() {
    const title = el("div", "lv-card-head");
    title.append(el("h4", "cr-mini", "Why the core flagged this"));
    const list = el("ul", "cr-list lv-evidence");
    if (!evidence.length) list.append(el("li", "cr-empty", "No alerts. Every channel sits inside its learned band."));
    for (const item of evidence) {
      const li = el("li", "lv-ev");
      li.dataset.level = item.level;
      const head = el("div", "lv-ev-head");
      head.append(lamp(item.level), el("strong", "", item.title), chip(item.rawLevel, item.level));
      li.append(head, ...item.lines.map((line) => el("p", "cr-sub", line)));
      list.append(li);
    }
    evidenceCard.replaceChildren(title, list);
  }

  // ---------- public ----------
  function update(data, alerts) {
    flagged = new Map();
    evidence = [];
    for (const alert of alerts ?? []) {
      const level = ALERT_LEVEL[alert.level] ?? "info";
      evidence.push({ title: alert.title, rawLevel: alert.level, level, lines: alert.evidence ?? [] });
      for (const line of alert.evidence ?? []) flagged.set(line.split(":")[0], level);
    }
    last_data = data;
    recordHistory(data);
    const defs = data.signals.filter((s) => s.modality !== "event");
    const ids = defs.map((s) => s.channel).join("|");
    if (ids !== order.join("|")) {
      order = defs.map((s) => s.channel);
      channels = new Map(defs.map((s) => [s.channel, buildRow(s)]));
      rows.replaceChildren(...[...channels.values()].map((c) => c.row));
      strip.dataset.sig = "";
      seeded = loadHistory();
      if (!channels.has(selected)) selected = defs.find((s) => flagged.has(s.channel))?.channel ?? defs.find((s) => s.modality === "waveform")?.channel ?? defs[0]?.channel ?? null;
      if (selected) { channels.get(selected).row.dataset.selected = "true"; fetchFeatures(selected); }
    }
    paint(data);
    renderStrip(data);
    renderHeadChips(data);
    renderFeatures();
    renderEvidence();
    fetchWindows();
    if (reduceMotion()) drawAll(performance.now(), 0);
  }

  return {
    root,
    update,
    start() {
      if (running) return;
      running = true;
      last = 0;
      if (!reduceMotion()) frame = requestAnimationFrame(loop);
    },
    stop() { running = false; cancelAnimationFrame(frame); },
    reset() {
      generation += 1;
      channels = new Map(); order = []; selected = null; selectedFeatures = null; lastTick = -1; history.clear();
      rows.replaceChildren(); strip.replaceChildren(); strip.dataset.sig = "";
    },
    destroy() { running = false; cancelAnimationFrame(frame); generation += 1; },
  };
}
