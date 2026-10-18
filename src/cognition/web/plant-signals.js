// Signal binding for the process-flow and HMI views: pure functions, no DOM, no network.
// Every value comes from the /operations read model; nothing here controls the plant.

export const BASIS = {
  sim: { code: "SIM", name: "Simulated plant state" },
  est: { code: "EST", name: "Derived estimate, not a sensor" },
  calc: { code: "CALC", name: "Calculated from simulated state" },
  reflex: { code: "REFLEX", name: "Reflexive-layer output" },
};

// Share of the demo envelope at which the simulator's cutoff resets (see layers/reflexive).
const NEAR_CUTOFF = 0.85;
const clamp01 = (value) => Math.max(0, Math.min(1, value));

export function buildContext(op) {
  const indicators = op.perceptual?.indicators ?? [];
  return {
    state: op.snapshot,
    ind: Object.fromEntries(indicators.map((item) => [item.id, item])),
    reflexive: op.reflexive,
    perceptual: op.perceptual,
    cognitive: op.cognitive,
    time: op.time,
    limits: op.limits,
    industry: op.snapshot.spec.industry,
    incident: op.incident,
  };
}

const SOURCES = {
  temp: (c) => (c.state.quality === "good" ? c.state.temperature : null),
  sp: (c) => c.state.target,
  dev: (c) => (c.state.quality === "good" ? c.state.temperature - c.state.target : null),
  duty: (c) => c.state.duty,
  act: (c) => c.state.actuator,
  gap: (c) => c.state.duty - c.state.actuator,
  dist: (c) => c.state.disturbance,
  fb: (c) => c.reflexive.feedback,
};

function scale(source, c) {
  const { envelope, band, gain } = c.limits;
  const target = c.state.target;
  switch (source) {
    case "temp":
      return {
        min: target - envelope,
        max: target + envelope,
        band: [target - band, target + band],
        crit: [target - NEAR_CUTOFF * envelope, target + NEAR_CUTOFF * envelope],
      };
    case "sp":
      return { min: target - envelope, max: target + envelope };
    case "dev":
      return {
        min: -envelope,
        max: envelope,
        band: [-band, band],
        crit: [-NEAR_CUTOFF * envelope, NEAR_CUTOFF * envelope],
      };
    case "duty":
    case "act":
      return { min: 0, max: 100, band: [10, 90] };
    case "gap":
      return { min: -50, max: 50 };
    case "dist":
      return { min: 0, max: gain * 20 };
    case "fb":
      return { min: -2, max: 2 };
    default:
      return { min: 0, max: 1 };
  }
}

function resolve(def, c) {
  if (def.src.startsWith("ind:")) {
    const item = c.ind[def.src.slice(4)];
    if (!item) return { value: null, min: 0, max: 1, band: null, level: "unavail" };
    const level = item.condition === "unavailable" ? "unavail" : item.condition === "outside_band" ? "warn" : "ok";
    return { value: item.value, min: item.minimum, max: item.maximum, band: item.band, level };
  }
  const value = SOURCES[def.src](c);
  const range = scale(def.src, c);
  let level = "info";
  if (value === null) level = "unavail";
  else if (range.crit && (value < range.crit[0] || value > range.crit[1])) level = "crit";
  else if (range.band && (value < range.band[0] || value > range.band[1])) level = "warn";
  else if (def.warnAbove !== undefined && value > def.warnAbove) level = "warn";
  else if (range.band || def.warnAbove !== undefined) level = "ok";
  if (def.src === "act" && c.state.stuck) level = "crit";
  if (def.src === "temp" && value !== null && (c.state.interlock || c.reflexive.interlock)) level = "crit";
  return { value, min: range.min, max: range.max, band: range.band ?? null, level };
}

// Temperature unit is presentation only. Absolute readings are offset; deltas are not.
export function convert(value, unit, preference) {
  if (value === null || preference !== "F") return { value, unit };
  if (unit === "°C") return { value: (value * 9) / 5 + 32, unit: "°F" };
  if (unit === "Δ°C") return { value: (value * 9) / 5, unit: "Δ°F" };
  return { value, unit };
}

export function format(value, unit, digits, preference) {
  const shown = convert(value, unit, preference);
  if (shown.value === null) return { text: "—", unit: shown.unit };
  const text = shown.value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return { text, unit: shown.unit };
}

// One result per declared tag. `base` values stay in model units; `text` honours the unit toggle.
export function evaluate(model, c, preference = "C") {
  const results = new Map();
  for (const [id, def] of Object.entries(model.tags)) {
    const raw = resolve(def, c);
    const digits = def.digits ?? 1;
    const shown = format(raw.value, def.unit, digits, preference);
    const span = raw.max - raw.min || 1;
    const bandText = raw.band
      ? `${format(raw.band[0], def.unit, digits, preference).text} to ${format(raw.band[1], def.unit, digits, preference).text} ${shown.unit}`
      : null;
    results.set(id, {
      id,
      def,
      label: def.label,
      code: def.code ?? "",
      basis: BASIS[def.basis],
      value: raw.value,
      text: shown.text,
      unit: shown.unit,
      level: raw.level,
      min: raw.min,
      max: raw.max,
      band: raw.band,
      bandText,
      norm: raw.value === null ? null : clamp01((raw.value - raw.min) / span),
      bandNorm: raw.band ? [clamp01((raw.band[0] - raw.min) / span), clamp01((raw.band[1] - raw.min) / span)] : null,
    });
  }
  return results;
}

// Presentation of conditions the platform already reports. These alarms do not gate any control.
export function plantAlarms(c) {
  const alarms = [];
  const { state, reflexive, perceptual, limits } = c;
  if (state.quality !== "good") {
    alarms.push({ id: "signal", level: "crit", text: "Process signal invalid", tags: ["temp", "dev"] });
  }
  if (state.stuck) {
    alarms.push({ id: "stuck", level: "crit", text: "Actuator not tracking its command", tags: ["act", "duty", "gap"] });
  }
  if (state.interlock || reflexive.interlock) {
    alarms.push({ id: "interlock", level: "crit", text: "High-temperature cutoff active", tags: ["temp", "dev", "act"] });
  }
  if (state.mode !== "automatic") {
    alarms.push({ id: "mode", level: "warn", text: "Manual mode: reflexive correction suspended", tags: ["duty", "act", "fb"] });
  }
  if (state.quality === "good") {
    const deviation = Math.abs(state.temperature - state.target);
    if (!state.interlock && deviation >= NEAR_CUTOFF * limits.envelope) {
      alarms.push({ id: "near-cutoff", level: "crit", text: "Deviation near the cutoff envelope", tags: ["temp", "dev"] });
    } else if (deviation > limits.band) {
      alarms.push({ id: "band", level: "warn", text: "Temperature outside the recovery band", tags: ["temp", "dev"] });
    }
    for (const [id, item] of Object.entries(c.ind)) {
      if (item.condition === "outside_band") {
        alarms.push({ id: `ind-${id}`, level: "warn", text: `${item.name} outside its display band`, tags: [id] });
      }
    }
  }
  for (const [index, conflict] of (perceptual?.conflicts ?? []).entries()) {
    alarms.push({ id: `conflict-${index}`, level: "warn", text: conflict, tags: [] });
  }
  return alarms;
}

export const LEVEL_RANK = { crit: 3, warn: 2, unavail: 1, ok: 0, info: 0 };
export const worst = (levels) => levels.reduce((a, b) => (LEVEL_RANK[b] > LEVEL_RANK[a] ? b : a), "ok");

export function plantCondition(state) {
  if (state.quality === "bad") return { label: "Sensor fault", level: "crit" };
  if (state.stuck) return { label: "Actuator fault", level: "crit" };
  if (state.interlock) return { label: "Cutoff active", level: "crit" };
  if (state.mode !== "automatic") return { label: "Manual mode", level: "warn" };
  if (state.disturbance) return { label: "Disturbed", level: "warn" };
  return { label: "Nominal", level: "ok" };
}
