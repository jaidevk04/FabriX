const svgNS = "http://www.w3.org/2000/svg";
const node = (tag, attrs, text) => {
  const e = document.createElementNS(svgNS, tag);
  Object.entries(attrs).forEach(([key, value]) =>
    e.setAttribute(key, String(value)),
  );
  if (text !== undefined) e.textContent = text;
  return e;
};
export function temperatureInstrument(p, value, unit, source) {
  const gauge = document.getElementById("temperature-gauge");
  const envelope = { cement: 250, steel: 220, chemical: 35 }[p.spec.industry];
  const band = { cement: 20, steel: 18, chemical: 3 }[p.spec.industry];
  const min = p.target - envelope,
    max = p.target + envelope;
  const convert = (v) => (unit === "F" ? (v * 9) / 5 + 32 : v);
  const y = (v) =>
    180 - Math.max(0, Math.min(1, (v - min) / (max - min))) * 158;
  const valid = p.quality === "good";
  const within = Math.abs(value - p.target) <= band;
  const color = valid ? (within ? "#267c9b" : "#bf792c") : "#8899a8";
  gauge.replaceChildren();
  gauge.append(
    node("rect", {
      x: 73,
      y: 22,
      width: 14,
      height: 158,
      rx: 7,
      fill: "#e7eef3",
    }),
  );
  gauge.append(
    node("rect", {
      x: 65,
      y: y(p.target + band),
      width: 30,
      height: y(p.target - band) - y(p.target + band),
      rx: 2,
      fill: "#b7dccc",
    }),
  );
  if (valid)
    gauge.append(
      node("rect", {
        x: 77,
        y: y(value),
        width: 6,
        height: Math.max(0, 180 - y(value)),
        rx: 3,
        fill: color,
      }),
    );
  for (let i = 0; i <= 8; i++) {
    const v = min + ((max - min) * i) / 8,
      major = i % 2 === 0;
    gauge.append(
      node("line", {
        x1: major ? 53 : 59,
        x2: 65,
        y1: y(v),
        y2: y(v),
        stroke: "#7e96a8",
        "stroke-width": 1,
      }),
    );
    if (major)
      gauge.append(
        node(
          "text",
          {
            x: 46,
            y: y(v) + 3,
            "text-anchor": "end",
            fill: "#60798f",
            "font-size": 10,
          },
          convert(v).toFixed(0),
        ),
      );
  }
  gauge.append(
    node("line", {
      x1: 67,
      x2: 94,
      y1: y(p.target),
      y2: y(p.target),
      stroke: "#29765c",
      "stroke-width": 1.5,
    }),
  );
  if (valid)
    gauge.append(
      node("path", {
        d: `M 101 ${y(value) - 5} L 91 ${y(value)} L 101 ${y(value) + 5} Z`,
        fill: color,
      }),
    );
  gauge.append(node("circle", { cx: 80, cy: 188, r: 8, fill: color }));
  const reading = gauge;
  reading.removeAttribute("aria-hidden");
  reading.setAttribute("role", valid ? "meter" : "img");
  reading.setAttribute(
    "aria-label",
    valid
      ? `Process temperature ${convert(value).toFixed(1)} degrees ${unit === "F" ? "Fahrenheit" : "Celsius"}, setpoint ${convert(p.target).toFixed(1)}, ${source}`
      : "Process temperature unavailable: invalid sensor signal",
  );
  if (valid) {
    reading.setAttribute("aria-valuemin", convert(min));
    reading.setAttribute("aria-valuemax", convert(max));
    reading.setAttribute("aria-valuenow", convert(value));
  } else
    ["aria-valuemin", "aria-valuemax", "aria-valuenow"].forEach((a) =>
      reading.removeAttribute(a),
    );
  document.getElementById("temperature").textContent = valid
    ? convert(value).toFixed(1)
    : "—";
  document.getElementById("temperature-unit-label").textContent = `°${unit}`;
  document.getElementById("gauge-target").textContent =
    `${convert(p.target).toFixed(0)} °${unit}`;
  const deviation = (value - p.target) * (unit === "F" ? 9 / 5 : 1);
  document.getElementById("gauge-deviation").textContent = valid
    ? `${deviation >= 0 ? "+" : ""}${deviation.toFixed(1)} °${unit}`
    : "Unavailable";
  const condition = document.getElementById("gauge-condition");
  condition.textContent = valid
    ? within
      ? "Within recovery band"
      : "Outside recovery band"
    : "Invalid signal";
  condition.className = `status ${valid && within ? "healthy" : "fault"}`;
  document.getElementById("reading-source").textContent = source;
  document.getElementById("live-snapshot").hidden = source === "Snapshot";
  document.getElementById("gauge-range").textContent =
    `Instrument window ${convert(min).toFixed(0)}–${convert(max).toFixed(0)} °${unit}. Green zone: recovery band ±${(band * (unit === "F" ? 9 / 5 : 1)).toFixed(1)} °${unit}. This is the model window, not a certified operating limit.`;
}
export function dutyInstruments(p) {
  const host = document.getElementById("duty-instruments");
  if(host.children.length === 2) {
    [p.duty,p.actuator].forEach((value,index) => {
      host.children[index].querySelector("strong").textContent=`${value.toFixed(1)}%`;
      host.children[index].querySelector("meter").value=value;
    });
    return;
  }
  for (const [label, value] of [
    ["Commanded duty", p.duty],
    ["Actuator position", p.actuator],
  ]) {
    const row = document.createElement("div");
    row.className = "duty-instrument";
    const head = document.createElement("div"),
      name = document.createElement("span"),
      val = document.createElement("strong");
    name.textContent = label;
    val.textContent = `${value.toFixed(1)}%`;
    head.append(name, val);
    const meter = document.createElement("meter");
    meter.min = 0;
    meter.max = 100;
    meter.value = value;
    meter.setAttribute("aria-label", label);
    row.append(head, meter);
    host.append(row);
  }
}
