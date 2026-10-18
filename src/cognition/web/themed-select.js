// Themed dropdown: wraps a native <select>, which stays in the DOM as the source of truth.
// Code that fills the select, sets `select.value`, disables it or listens for "change" keeps working.
// The list is drawn by this module so it matches the theme. Keyboard: arrows, Home, End, Enter, Escape, type-ahead.

const GAP = 6;
const MAX_LIST = 300;
let open = null; // the one open dropdown, so opening another closes it

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const valueSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");

// "Name (equipment)" and "Name · note" show the second part muted.
function split(text) {
  const bar = text.split(" · ");
  if (bar.length === 2) return [bar[0], bar[1]];
  const paren = /^(.*?)\s*\(([^)]+)\)$/.exec(text);
  return paren ? [paren[1], paren[2]] : [text, ""];
}

export function themeSelect(select) {
  if (!select || select.dataset.themed) return null;
  select.dataset.themed = "true";
  const wrap = el("div", "ts");
  const button = el("button", "ts-btn");
  button.type = "button";
  button.setAttribute("role", "combobox");
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  const label = el("span", "ts-label");
  const meta = el("span", "ts-meta");
  const chevron = el("span", "ts-chevron");
  chevron.setAttribute("aria-hidden", "true");
  button.append(label, meta, chevron);
  const list = el("div", "ts-list");
  list.setAttribute("role", "listbox");
  list.tabIndex = -1;
  list.hidden = true;
  const id = select.id || `ts-${Math.random().toString(36).slice(2, 8)}`;
  list.id = `${id}-list`;
  button.setAttribute("aria-controls", list.id);
  select.parentNode.insertBefore(wrap, select);
  wrap.append(select, button);
  document.body.append(list);
  select.classList.add("ts-native");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");
  // A <label for=id> should focus the visible control.
  const labelFor = select.id ? document.querySelector(`label[for="${select.id}"]`) : null;
  if (labelFor) {
    labelFor.addEventListener("click", (event) => { event.preventDefault(); button.focus(); });
    button.setAttribute("aria-labelledby", labelFor.id || (labelFor.id = `${id}-label`));
  } else if (select.getAttribute("aria-label")) button.setAttribute("aria-label", select.getAttribute("aria-label"));

  let items = []; // { option, node }
  let active = -1;
  let typed = "";
  let typedAt = 0;

  function rebuild() {
    items = [];
    list.replaceChildren();
    const addOption = (option, parent) => {
      const [name, note] = split(option.textContent.trim());
      const node = el("div", "ts-opt");
      node.setAttribute("role", "option");
      node.dataset.value = option.value;
      if (option.disabled) node.setAttribute("aria-disabled", "true");
      node.append(el("span", "ts-opt-name", name));
      if (note) node.append(el("span", "ts-opt-note", note));
      if (option.dataset.badge) node.append(el("span", "ts-opt-badge", option.dataset.badge));
      node.addEventListener("pointermove", () => { if (!option.disabled) highlight(items.findIndex((x) => x.node === node)); });
      node.addEventListener("click", () => { if (!option.disabled) choose(option.value); });
      items.push({ option, node });
      parent.append(node);
    };
    for (const child of select.children) {
      if (child.tagName === "OPTGROUP") {
        const group = el("div", "ts-group");
        group.setAttribute("role", "group");
        group.setAttribute("aria-label", child.label);
        group.append(el("div", "ts-group-label", child.label));
        for (const option of child.children) addOption(option, group);
        list.append(group);
      } else addOption(child, list);
    }
    sync();
  }

  function sync() {
    const selected = select.selectedOptions[0];
    const [name, note] = selected ? split(selected.textContent.trim()) : ["", ""];
    label.textContent = name || "Select";
    meta.textContent = note;
    meta.hidden = !note;
    button.disabled = select.disabled || !items.length;
    wrap.dataset.disabled = String(button.disabled);
    for (const { option, node } of items) {
      const on = option === selected;
      node.setAttribute("aria-selected", String(on));
      node.dataset.selected = String(on);
    }
  }

  function highlight(index, scroll = false) {
    active = index;
    items.forEach(({ node }, i) => { node.dataset.active = String(i === index); });
    const node = items[index]?.node;
    if (node) {
      button.setAttribute("aria-activedescendant", node.id || (node.id = `${list.id}-${index}`));
      if (scroll) node.scrollIntoView({ block: "nearest" });
    }
  }

  const enabled = () => items.map((x, i) => (x.option.disabled ? -1 : i)).filter((i) => i >= 0);
  function step(delta) {
    const ok = enabled();
    if (!ok.length) return;
    const at = ok.indexOf(active);
    highlight(ok[Math.max(0, Math.min(ok.length - 1, (at < 0 ? ok.indexOf(items.findIndex((x) => x.option.selected)) : at) + delta))], true);
  }

  function place() {
    const box = button.getBoundingClientRect();
    const below = window.innerHeight - box.bottom - GAP - 8;
    const above = box.top - GAP - 8;
    const flip = below < 180 && above > below;
    const room = Math.max(120, Math.min(MAX_LIST, flip ? above : below));
    Object.assign(list.style, {
      left: `${box.left}px`,
      width: `${box.width}px`,
      maxHeight: `${room}px`,
      top: flip ? "auto" : `${box.bottom + GAP}px`,
      bottom: flip ? `${window.innerHeight - box.top + GAP}px` : "auto",
    });
    list.dataset.flip = String(flip);
  }

  function show() {
    if (button.disabled || !list.hidden) return;
    if (open && open !== api) open.hide();
    open = api;
    rebuild();
    list.hidden = false;
    place();
    button.setAttribute("aria-expanded", "true");
    wrap.dataset.open = "true";
    highlight(Math.max(0, items.findIndex((x) => x.option.selected)), true);
    document.addEventListener("pointerdown", onOutside, true);
    window.addEventListener("resize", hide);
    window.addEventListener("scroll", onScroll, true);
  }
  function hide() {
    if (list.hidden) return;
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    button.removeAttribute("aria-activedescendant");
    delete wrap.dataset.open;
    document.removeEventListener("pointerdown", onOutside, true);
    window.removeEventListener("resize", hide);
    window.removeEventListener("scroll", onScroll, true);
    if (open === api) open = null;
  }
  const onOutside = (event) => { if (!list.contains(event.target) && !wrap.contains(event.target)) hide(); };
  const onScroll = (event) => { if (!list.contains(event.target)) hide(); };

  function choose(value) {
    const changed = select.value !== value;
    valueSetter.set.call(select, value);
    sync();
    hide();
    button.focus();
    if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  button.addEventListener("click", () => (list.hidden ? show() : hide()));
  button.addEventListener("keydown", (event) => {
    const isOpen = !list.hidden;
    switch (event.key) {
      case "ArrowDown": event.preventDefault(); if (!isOpen) show(); else step(1); break;
      case "ArrowUp": event.preventDefault(); if (!isOpen) show(); else step(-1); break;
      case "Home": if (isOpen) { event.preventDefault(); highlight(enabled()[0], true); } break;
      case "End": if (isOpen) { event.preventDefault(); highlight(enabled().at(-1), true); } break;
      case "Enter":
      case " ":
        if (isOpen && event.key === " " && typed) break;
        event.preventDefault();
        if (!isOpen) show();
        else if (active >= 0) choose(items[active].option.value);
        break;
      case "Escape": if (isOpen) { event.preventDefault(); hide(); } break;
      case "Tab": hide(); break;
      default:
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
          const nowMs = Date.now();
          typed = nowMs - typedAt > 700 ? event.key.toLowerCase() : typed + event.key.toLowerCase();
          typedAt = nowMs;
          const hit = items.findIndex((x) => !x.option.disabled && x.option.textContent.trim().toLowerCase().startsWith(typed));
          if (hit >= 0) { if (list.hidden) show(); highlight(hit, true); }
        }
    }
  });

  // Keep in step with whatever fills or changes the native select.
  const observer = new MutationObserver(() => { if (list.hidden) rebuild(); else { rebuild(); highlight(Math.max(0, active)); } });
  observer.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "label", "data-badge"] });
  select.addEventListener("change", sync);
  // Assigning `select.value = x` from code does not fire an event, so the setter refreshes the display too.
  Object.defineProperty(select, "value", {
    configurable: true,
    get() { return valueSetter.get.call(this); },
    set(next) { valueSetter.set.call(this, next); sync(); },
  });

  const api = { rebuild, hide, destroy() { hide(); observer.disconnect(); list.remove(); } };
  rebuild();
  return api;
}
