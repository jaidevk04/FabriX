// Add plant: onboard a new plant from an industry pack, or import a typed manifest.
// Uses POST /api/plants and POST /api/manifests; new plants map onto the existing simulator packs.

import { MODELS } from "./plant-models.js";

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const PACKS = [
  { id: "cement", name: "Cement", process: "Rotary kiln and cooler", asset: "Kiln thermal surrogate", target: "1450 °C setpoint" },
  { id: "steel", name: "Steel", process: "Reheating furnace and line", asset: "Reheating furnace surrogate", target: "1200 °C setpoint" },
  { id: "chemical", name: "Chemical", process: "Jacketed batch reactor", asset: "Jacketed reactor thermal surrogate", target: "180 °C setpoint" },
];
const ID_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
const slug = (text) =>
  text.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^[^a-z]+/, "").replace(/-+$/g, "").slice(0, 64);

export function addPlantPage({ api }) {
  const form = $("onboard");
  const message = $("ap-message");
  const packsHost = $("ap-packs");
  const idInput = form.elements.id;
  const nameInput = form.elements.name;
  let industry = PACKS[0].id;
  let idEdited = false;

  const say = (text, kind = "") => {
    message.textContent = text;
    message.dataset.kind = kind;
  };

  // ---- step 1: industry packs ----
  for (const pack of PACKS) {
    const label = el("label", "ap-pack");
    const input = el("input");
    input.type = "radio";
    input.name = "industry";
    input.value = pack.id;
    input.checked = pack.id === industry;
    const body = el("span", "ap-pack-body");
    body.append(el("strong", "", pack.name), el("span", "", pack.process), el("small", "", `${pack.asset} · ${pack.target}`));
    label.append(input, body);
    input.addEventListener("change", () => {
      industry = pack.id;
      preview();
    });
    packsHost.append(label);
  }

  // ---- step 2: names ----
  nameInput.addEventListener("input", () => {
    if (!idEdited) idInput.value = slug(nameInput.value);
    say("");
    preview();
  });
  idInput.addEventListener("input", () => {
    idEdited = idInput.value !== "";
    say("");
    preview();
  });

  // ---- preview ----
  function preview() {
    const model = MODELS[industry];
    const pack = PACKS.find((p) => p.id === industry);
    const host = $("ap-preview");
    host.replaceChildren();
    const head = el("div", "ap-preview-head");
    head.append(el("span", "fl-badge", pack.id), el("strong", "", nameInput.value.trim() || `${pack.name} plant`));
    host.append(head, el("p", "ap-preview-id", idInput.value || "plant-id"));
    const list = el("ul", "ap-preview-list");
    const items = [
      [`${model.equipment.length} equipment HMI screens`, model.equipment.map((e) => e.name).join(", ")],
      ["Process flow", `${model.flow.nodes.length} symbols, ${model.flow.pipes.length} lines`],
      ["Digital twin", "Interactive 3D equipment scene"],
      ["Agent layers", "Reflexive, perceptual and cognitive, with the independent gateway"],
    ];
    for (const [title, detail] of items) {
      const item = el("li");
      item.append(el("strong", "", title), el("span", "", detail));
      list.append(item);
    }
    host.append(list, el("p", "ap-preview-note", "Educational thermal surrogate. No real plant connection is made."));
  }

  // ---- submit ----
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    const id = idInput.value.trim();
    if (!name) { say("Give the plant a name.", "error"); nameInput.focus(); return; }
    if (!ID_PATTERN.test(id)) {
      say("Plant ID must start with a letter and use lowercase letters, numbers, hyphen or underscore.", "error");
      idInput.focus();
      return;
    }
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    say("Creating plant…");
    try {
      const created = await api("/api/plants", { id, name, industry });
      done(message, created.spec.id, created.spec.name);
    } catch (error) {
      say(/already exists/i.test(error.message) ? "That plant ID is already registered. Choose another." : error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  // ---- manifest import ----
  $("manifest-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const out = $("manifest-message");
    let body;
    try {
      body = JSON.parse($("manifest-json").value);
    } catch {
      out.textContent = "The manifest is not valid JSON.";
      out.dataset.kind = "error";
      return;
    }
    out.textContent = "Importing…";
    out.dataset.kind = "";
    try {
      const imported = await api("/api/manifests", body);
      done(out, imported.plant.id, imported.plant.name);
    } catch (error) {
      out.textContent = /already exists/i.test(error.message) ? "That plant ID is already registered." : error.message;
      out.dataset.kind = "error";
    }
  });

  function done(target, id, name) {
    target.dataset.kind = "ok";
    target.replaceChildren(
      document.createTextNode(`${name} is ready. `),
      Object.assign(el("a", "ap-link", "Open in studio"), { href: `/studio?plant=${encodeURIComponent(id)}` }),
      document.createTextNode(" · "),
      Object.assign(el("a", "ap-link", "See all plants"), { href: "/fleet" }),
    );
  }

  preview();
  return Promise.resolve();
}
