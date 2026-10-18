// Specialist Faculties page: the cognitive cores for the plant selected in the studio. The tabs in the top
// bar pick the view: Overview (core tiles, activity, orders and runs) or one core's own workspace.
// The cores module does the polling and drawing; this file owns the tabs and the URL (/faculties?plant=<id>&tab=<view>). Nothing here writes to a plant.

import { CORE_VIEWS, createCores } from "./cores.js";
import { el, icon } from "./cores-parts.js";

export async function facultiesPage({ api }) {
  const host = document.getElementById("faculties-host");
  const tabs = [...document.querySelectorAll("#faculties-tabs [data-tab]")];
  const params = new URLSearchParams(location.search);
  let tab = CORE_VIEWS.includes(params.get("tab")) ? params.get("tab") : "overview";

  let plants;
  try {
    plants = await api("/api/plants");
  } catch (error) {
    host.replaceChildren(el("p", "cr-banner", `Unable to load plants: ${error.message}`));
    return;
  }
  if (!plants.length) {
    host.replaceChildren(el("p", "cr-empty", "No plants yet. Add a plant to see its cores."));
    return;
  }
  // The plant is whichever one the studio last showed (remembered by the browser), unless the URL names one.
  let stored = null;
  try { stored = localStorage.getItem("avenor.plant"); } catch { /* storage unavailable */ }
  const known = (id) => plants.find((p) => p.spec.id === id)?.spec.id;
  const plantId = known(params.get("plant")) ?? known(stored) ?? plants[0].spec.id;
  const stage = el("div", "hn-stage");
  host.replaceChildren(stage);

  // ---------- tabs ----------
  for (const button of tabs) button.prepend(icon(button.dataset.tab));
  function syncUrl() {
    const url = new URL(location.href);
    url.searchParams.set("plant", plantId);
    if (tab === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", url);
  }
  function showTabs() {
    for (const button of tabs) {
      const active = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
    host.setAttribute("aria-labelledby", `faculties-tab-${tab}`);
  }
  const cores = createCores(stage, {
    getPlant: () => plantId,
    view: tab,
    onOpen: (name) => setTab(name),
  });
  function setTab(next) {
    if (!CORE_VIEWS.includes(next)) return;
    tab = next;
    showTabs();
    syncUrl();
    cores.setView(next);
  }
  for (const button of tabs) button.addEventListener("click", () => setTab(button.dataset.tab));
  document.getElementById("faculties-tabs").addEventListener("keydown", (event) => {
    const forward = event.key === "ArrowRight";
    const back = event.key === "ArrowLeft";
    const edge = event.key === "Home" || event.key === "End";
    if (!forward && !back && !edge) return;
    event.preventDefault();
    const next = edge
      ? CORE_VIEWS[event.key === "Home" ? 0 : CORE_VIEWS.length - 1]
      : CORE_VIEWS[(CORE_VIEWS.indexOf(tab) + (forward ? 1 : CORE_VIEWS.length - 1)) % CORE_VIEWS.length];
    setTab(next);
    document.getElementById(`faculties-tab-${next}`).focus();
  });
  showTabs();
  syncUrl();
  window.addEventListener("pagehide", () => cores.destroy());
}
