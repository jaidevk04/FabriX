// Declarative plant models for the process-flow and HMI views.
// A model names tags (bound to simulator state or process estimates), equipment (one HMI each),
// and flow geometry. Tag codes and layout are illustrative; no real plant tags exist.
// To add an industry: add one entry here and, if it needs a new shape, one symbol in symbols.js.

import { worst } from "./plant-signals.js";

const lvl = (T, ...ids) => worst(ids.map((id) => T.get(id)?.level ?? "ok"));
const norm = (T, id) => T.get(id)?.norm ?? 0;

// Tags shared by every thermal surrogate (the only controlled loop in the simulator).
const loop = (what, code, sp) => ({
  temp: { label: `${what} temperature`, code, src: "temp", unit: "°C", basis: "sim" },
  sp: { label: "Setpoint", code: sp, src: "sp", unit: "°C", digits: 0, basis: "sim" },
  dev: { label: "Deviation from setpoint", code: "TDEV", src: "dev", unit: "Δ°C", basis: "calc" },
  duty: { label: "Commanded duty", code: "HIC-301", src: "duty", unit: "%", basis: "sim" },
  act: { label: "Actuator position", code: "ZT-302", src: "act", unit: "%", basis: "sim" },
  gap: { label: "Command minus position", code: "HGAP", src: "gap", unit: "%", basis: "calc" },
  fb: { label: "Reflexive correction", code: "HFB", src: "fb", unit: "%", digits: 2, basis: "reflex" },
  dist: { label: "Heat-load disturbance", code: "DIST", src: "dist", unit: "°C eq", basis: "sim", warnAbove: 0 },
});

// Equipment states shared by drives and burners: the simulator halts motion on a stuck actuator.
function actuatorStatus(c, T, what) {
  if (c.state.stuck) return { level: "crit", text: `${what} not tracking command` };
  if (c.state.interlock || c.reflexive.interlock) return { level: "crit", text: "Cutoff holds output low" };
  if (c.state.mode !== "automatic") return { level: "warn", text: "Manual mode" };
  return { level: lvl(T, "act"), text: "Regulating" };
}
function drivenStatus(c, T, id) {
  if (c.state.stuck) return { level: "crit", text: "Halted by actuator fault" };
  if (T.get(id).level === "unavail") return { level: "unavail", text: "Signal unavailable" };
  if (c.state.interlock || c.reflexive.interlock) return { level: "warn", text: "Running at reduced output" };
  return { level: T.get(id).level === "warn" ? "warn" : "ok", text: "Running" };
}
function estimateStatus(c, T, id, running = "Running") {
  const tag = T.get(id);
  if (tag.level === "unavail") return { level: "unavail", text: "Signal unavailable" };
  if (tag.level === "warn") return { level: "warn", text: "Outside display band" };
  return { level: "ok", text: running };
}
function processStatus(c, T) {
  const tag = T.get("temp");
  if (tag.level === "unavail") return { level: "unavail", text: "Temperature signal invalid" };
  if (tag.level === "crit") return { level: "crit", text: c.state.interlock ? "Cutoff active" : "Near cutoff envelope" };
  if (tag.level === "warn") return { level: "warn", text: "Outside recovery band" };
  return { level: "ok", text: "Within recovery band" };
}

const NOT_MODELLED_THERMAL = "Calibrated heat and mass balance";

const cement = {
  title: "Kiln process",
  tags: {
    ...loop("Kiln", "TI-201", "TIC-201"),
    draft: { label: "Kiln draft", code: "PI-102", src: "ind:draft", unit: "Pa", digits: 0, basis: "est" },
    oxygen: { label: "Flue oxygen", code: "AI-103", src: "ind:oxygen", unit: "%", digits: 2, basis: "est" },
    feed: { label: "Raw-meal feed", code: "FIC-101", src: "ind:feed", unit: "t/h", digits: 0, basis: "est" },
    speed: { label: "Kiln rotation", code: "SI-401", src: "ind:speed", unit: "rpm", digits: 2, basis: "est" },
    cooler: { label: "Cooler outlet", code: "TI-501", src: "ind:cooler", unit: "°C", digits: 0, basis: "est" },
  },
  equipment: [
    {
      id: "kiln", name: "Rotary kiln", code: "TIC-201",
      role: "Holds the burning-zone temperature at setpoint. The only simulated process variable.",
      primary: "temp", tags: ["temp", "sp", "dev", "draft", "oxygen", "cooler"],
      status: processStatus,
      notModelled: ["Clinker mineralogy and free lime", "Coating and ring formation", NOT_MODELLED_THERMAL],
    },
    {
      id: "burner", name: "Main burner", code: "HIC-301",
      role: "Thermal duty is the one controllable input. The reflexive layer trims it and a cutoff can override it.",
      primary: "act", tags: ["duty", "act", "gap", "fb", "oxygen", "dist"],
      status: (c, T) => actuatorStatus(c, T, "Burner"),
      notModelled: ["Fuel calorific value and primary-air split", "Flame shape and kiln hood pressure"],
    },
    {
      id: "drive", name: "Kiln drive", code: "SIC-401",
      role: "Rotates the shell. Speed is an illustrative estimate and is not an independent control.",
      primary: "speed", tags: ["speed", "act", "temp"],
      status: (c, T) => drivenStatus(c, T, "speed"),
      notModelled: ["Motor current and torque", "Shell skew and girth-gear wear"],
    },
    {
      id: "feed", name: "Raw-meal feed", code: "FIC-101",
      role: "Feeds raw meal to the kiln inlet. Rate falls as the disturbance grows (illustrative).",
      primary: "feed", tags: ["feed", "dist", "temp"],
      status: (c, T) => estimateStatus(c, T, "feed"),
      notModelled: ["Raw-meal chemistry", "Hopper level and feeder speed"],
    },
  ],
  flow: {
    size: [1000, 520],
    card: ["feed", "kiln", "drive", "burner"],
    pipes: [
      { id: "raw-in", points: [[40, 160], [170, 160]], medium: "solid", rate: "feed", label: "Raw meal", at: [105, 148] },
      { id: "feed", eq: "feed", points: [[225, 210], [225, 262], [300, 262]], medium: "solid", rate: "feed" },
      { id: "flue", eq: "kiln", points: [[300, 235], [300, 60], [60, 60]], medium: "flue", rate: "draft", invert: true, label: "Flue gas to filter and stack", at: [180, 48] },
      { id: "fuel", eq: "burner", points: [[950, 263], [870, 263]], medium: "fuel", rate: "act", label: "Fuel", at: [910, 250] },
      { id: "clinker", eq: "kiln", points: [[730, 305], [730, 345]], medium: "solid", rate: "feed" },
      { id: "out", points: [[870, 380], [950, 380]], medium: "product", rate: "feed", label: "Clinker", at: [910, 368] },
    ],
    nodes: [
      { id: "feed", eq: "feed", kind: "hopper", x: 170, y: 110, w: 110, h: 100, label: "Raw-meal feed" },
      { id: "kiln", eq: "kiln", kind: "kiln", x: 300, y: 235, w: 400, h: 70, label: "Rotary kiln",
        drive: (c, T) => ({ heat: T.get("temp").norm ?? 0.5, spin: norm(T, "speed") * 1.6, halted: c.state.stuck }) },
      { id: "drive", eq: "drive", kind: "motor", x: 470, y: 305, w: 80, h: 120, label: "Kiln drive", labelAt: [-8, 142],
        drive: (c, T) => ({ spin: norm(T, "speed") * 1.6, halted: c.state.stuck }) },
      { id: "burner", eq: "burner", kind: "burner", x: 715, y: 245, w: 155, h: 36, label: "Main burner",
        drive: (c) => ({ flame: c.state.actuator / 100, faulted: c.state.stuck }) },
      { id: "cooler", eq: "kiln", kind: "cooler", x: 700, y: 345, w: 170, h: 70, label: "Cooler (indicator only)",
        drive: (c, T) => ({ heat: norm(T, "cooler") }) },
    ],
    tags: [
      { tag: "feed", x: 30, y: 215, to: [172, 190] },
      { tag: "draft", x: 330, y: 76, to: [300, 101] },
      { tag: "oxygen", x: 330, y: 136, to: [300, 161] },
      { tag: "temp", x: 470, y: 150, to: [520, 236] },
      { tag: "dev", x: 606, y: 150, to: [650, 236] },
      { tag: "speed", x: 580, y: 365, to: [542, 392] },
      { tag: "duty", x: 750, y: 150, to: [800, 246] },
      { tag: "act", x: 868, y: 290, to: [850, 281] },
      { tag: "cooler", x: 850, y: 420, to: [800, 416] },
    ],
  },
};

const steel = {
  title: "Reheating furnace line",
  tags: {
    ...loop("Furnace", "TI-201", "TIC-201"),
    pressure: { label: "Furnace pressure", code: "PI-102", src: "ind:pressure", unit: "Pa", digits: 1, basis: "est" },
    oxygen: { label: "Flue oxygen", code: "AI-103", src: "ind:oxygen", unit: "%", digits: 2, basis: "est" },
    core: { label: "Billet core temperature", code: "TI-501", src: "ind:core", unit: "°C", digits: 0, basis: "est" },
    fuel: { label: "Fuel-gas flow", code: "FI-302", src: "ind:fuel", unit: "Nm³/h", digits: 0, basis: "est" },
    throughput: { label: "Line throughput", code: "FIC-401", src: "ind:throughput", unit: "t/h", digits: 0, basis: "est" },
    demand: { label: "Roller drive demand", code: "SIC-402", src: "act", unit: "%", basis: "calc" },
  },
  equipment: [
    {
      id: "furnace", name: "Reheating furnace", code: "TIC-201",
      role: "Holds furnace temperature at setpoint. The only simulated process variable.",
      primary: "temp", tags: ["temp", "sp", "dev", "pressure", "oxygen", "core"],
      status: processStatus,
      notModelled: ["Zone-by-zone temperature profile", "Scale formation and refractory state", NOT_MODELLED_THERMAL],
    },
    {
      id: "burner", name: "Burner bank", code: "HIC-301",
      role: "Thermal duty sets the heating input, within gateway limits. A cutoff can override it.",
      primary: "act", tags: ["duty", "act", "gap", "fb", "fuel", "oxygen", "dist"],
      status: (c, T) => actuatorStatus(c, T, "Burner bank"),
      notModelled: ["Per-burner air-fuel ratio", "Flame supervision"],
    },
    {
      id: "rollers", name: "Roller conveyor", code: "SIC-402",
      role: "Carries billets through the furnace. Speed follows the actuator position and halts on an actuator fault (illustrative).",
      primary: "throughput", tags: ["throughput", "demand", "temp"],
      status: (c, T) => drivenStatus(c, T, "throughput"),
      notModelled: ["Roller motor current", "Billet tracking and pacing logic"],
    },
    {
      id: "billets", name: "Steel billets", code: "TI-501",
      role: "Workpieces riding the conveyor. Core temperature is offset from furnace temperature (illustrative).",
      primary: "core", tags: ["core", "temp", "throughput"],
      status: (c, T) => estimateStatus(c, T, "core", "Heating"),
      notModelled: ["Heat penetration and residence time", "Individual billet temperatures", "Metallurgy"],
    },
  ],
  flow: {
    size: [1000, 520],
    card: ["furnace", "burner", "rollers", "billets"],
    cardView: [190, 104, 620, 290],
    pipes: [
      { id: "fuel", eq: "burner", points: [[60, 150], [300, 150]], medium: "fuel", rate: "fuel", label: "Fuel gas", at: [130, 138] },
      { id: "flue", eq: "furnace", points: [[720, 190], [720, 80], [940, 80]], medium: "flue", rate: "fuel", label: "Flue gas to stack", at: [830, 68] },
    ],
    nodes: [
      { id: "furnace", eq: "furnace", kind: "furnace", x: 250, y: 190, w: 500, h: 150, label: "Reheating furnace", labelAt: [512, 30],
        drive: (c, T) => ({ heat: T.get("temp").norm ?? 0.5 }) },
      { id: "burner", eq: "burner", kind: "burnerbank", x: 300, y: 130, w: 400, h: 60, label: "Burner bank",
        drive: (c) => ({ flame: c.state.actuator / 100, faulted: c.state.stuck }) },
      { id: "rollers", eq: "rollers", kind: "rollers", x: 40, y: 340, w: 920, h: 26, label: "Roller conveyor", labelAt: [0, 48],
        drive: (c, T) => ({ spin: norm(T, "throughput") * 1.6, halted: c.state.stuck }) },
      { id: "billets", eq: "billets", kind: "billets", x: 40, y: 316, w: 920, h: 24, label: "Billets",
        drive: (c, T) => ({ speed: norm(T, "throughput"), halted: c.state.stuck, heat: norm(T, "core") }) },
    ],
    tags: [
      { tag: "temp", x: 282, y: 238, to: [338, 236] },
      { tag: "pressure", x: 410, y: 238, to: [466, 236] },
      { tag: "oxygen", x: 538, y: 238, to: [594, 236] },
      { tag: "fuel", x: 100, y: 70, to: [180, 150] },
      { tag: "duty", x: 300, y: 40, to: [350, 130] },
      { tag: "act", x: 450, y: 40, to: [500, 130] },
      { tag: "throughput", x: 330, y: 420, to: [386, 367] },
      { tag: "demand", x: 470, y: 420, to: [530, 367] },
      { tag: "core", x: 790, y: 262, to: [748, 328] },
    ],
  },
};

const chemical = {
  title: "Jacketed reactor",
  tags: {
    ...loop("Reactor", "TI-201", "TIC-201"),
    pressure: { label: "Reactor pressure", code: "PI-102", src: "ind:pressure", unit: "bar", digits: 2, basis: "est" },
    level: { label: "Vessel fill", code: "LI-103", src: "ind:level", unit: "%", digits: 0, basis: "est" },
    agitation: { label: "Agitator speed", code: "SI-401", src: "ind:agitation", unit: "rpm", digits: 0, basis: "est" },
    conversion: { label: "Batch conversion", code: "AI-104", src: "ind:conversion", unit: "%", digits: 0, basis: "est" },
    coolant: { label: "Jacket circulation", code: "FI-302", src: "ind:coolant", unit: "m³/h", digits: 1, basis: "est" },
  },
  equipment: [
    {
      id: "reactor", name: "Jacketed reactor", code: "TIC-201",
      role: "Holds bulk temperature at setpoint. The only simulated process variable.",
      primary: "temp", tags: ["temp", "sp", "dev", "pressure", "level", "conversion"],
      status: processStatus,
      notModelled: ["Reaction kinetics and heat of reaction", "Thermodynamic equation of state", "Mass balance"],
    },
    {
      id: "jacket", name: "Heating jacket", code: "HIC-301",
      role: "Thermal duty controls the heating input. A cutoff can override it.",
      primary: "act", tags: ["duty", "act", "gap", "fb", "coolant", "dist"],
      status: (c, T) => actuatorStatus(c, T, "Jacket duty"),
      notModelled: ["Jacket inlet and outlet temperatures", "Heat-transfer coefficient"],
    },
    {
      id: "agitator", name: "Agitator drive", code: "SIC-401",
      role: "Mixes the batch. Speed responds to the actuator position and halts on a fault (illustrative).",
      primary: "agitation", tags: ["agitation", "act", "temp"],
      status: (c, T) => drivenStatus(c, T, "agitation"),
      notModelled: ["Motor power draw", "Mixing quality and shaft vibration"],
    },
    {
      id: "pipes", node: "reactor", name: "Process piping", code: "LI-103",
      role: "Inlet and outlet connections. Flow and composition are not measured; vessel state is shown instead.",
      primary: "level", tags: ["level", "pressure", "coolant"],
      status: (c, T) => estimateStatus(c, T, "level", "Connected"),
      notModelled: ["Inlet and outlet flow", "Composition and valve positions"],
    },
  ],
  flow: {
    size: [1000, 520],
    card: ["reactor", "agitator", "jacket"],
    pipes: [
      { id: "inlet", eq: "pipes", points: [[60, 170], [384, 170]], medium: "solid", static: true, label: "Feed in", at: [110, 158] },
      { id: "outlet", eq: "pipes", points: [[500, 408], [500, 460], [940, 460]], medium: "product", static: true, label: "Product out", at: [880, 448] },
      { id: "jin", eq: "jacket", points: [[820, 268], [632, 268]], medium: "heat", rate: "coolant", label: "Jacket supply", at: [726, 256] },
      { id: "jout", eq: "jacket", points: [[632, 352], [820, 352]], medium: "heat", rate: "coolant", label: "Jacket return", at: [726, 372] },
    ],
    nodes: [
      { id: "reactor", eq: "reactor", kind: "vessel", x: 380, y: 110, w: 240, h: 300, label: "Jacketed reactor", labelAt: [-12, 326],
        drive: (c, T) => ({ level: T.get("level").norm ?? 0, heat: T.get("temp").norm ?? 0.5, flow: norm(T, "coolant"), spin: norm(T, "agitation") * 1.6, halted: c.state.stuck }) },
      { id: "agitator", eq: "agitator", kind: "agitator", x: 440, y: 40, w: 120, h: 230, label: "Agitator drive", hit: [26, -4, 68, 44],
        drive: (c, T) => ({ spin: norm(T, "agitation") * 1.6, halted: c.state.stuck }) },
      { id: "pipes", eq: "pipes", kind: "valve", x: 200, y: 150, w: 40, h: 40, label: "Inlet valve" },
      { id: "pump", eq: "pipes", kind: "pump", x: 760, y: 440, w: 40, h: 40, label: "Outlet pump", labelAt: [-8, 58] },
      { id: "jacket", eq: "jacket", kind: "heater", x: 820, y: 240, w: 90, h: 140, label: "Heat source",
        drive: (c) => ({ flame: c.state.actuator / 100, faulted: c.state.stuck }) },
    ],
    tags: [
      { tag: "temp", x: 140, y: 225, to: [388, 250] },
      { tag: "pressure", x: 140, y: 290, to: [388, 300] },
      { tag: "level", x: 140, y: 355, to: [388, 350] },
      { tag: "conversion", x: 640, y: 60, to: [590, 150] },
      { tag: "agitation", x: 290, y: 52, to: [440, 78] },
      { tag: "coolant", x: 650, y: 175, to: [726, 262] },
      { tag: "duty", x: 800, y: 100, to: [860, 241] },
      { tag: "act", x: 650, y: 385, to: [826, 372] },
    ],
  },
};

export const MODELS = { cement, steel, chemical };
export const modelFor = (industry) => MODELS[industry];
