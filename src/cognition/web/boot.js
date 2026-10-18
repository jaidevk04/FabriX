// Runs before first paint: picks the active page and restores sidebar state.
(() => {
  const root = document.documentElement;
  const known = ["fleet", "studio", "faculties", "agents", "investigations", "impact", "assets", "system"];
  const first = location.pathname.split("/")[1] || "fleet";
  root.dataset.workspace = known.includes(first) ? first : "fleet";
  // Collapsed unless the user has expanded it before (that choice is remembered).
  let collapsed = true;
  try {
    collapsed = localStorage.getItem("fabrix.sidebar") !== "expanded";
  } catch {
    /* storage unavailable: keep default */
  }
  root.dataset.sidebar = collapsed ? "collapsed" : "expanded";
  setTimeout(() => root.classList.add("ready"), 3000);
  addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("sidebar-toggle");
    if (!button) return;
    const sync = () => {
      const closed = root.dataset.sidebar === "collapsed";
      const label = closed ? "Expand sidebar" : "Collapse sidebar";
      button.setAttribute("aria-expanded", String(!closed));
      button.setAttribute("aria-label", label);
      button.title = label;
    };
    sync();
    button.addEventListener("click", () => {
      const closed = root.dataset.sidebar !== "collapsed";
      root.dataset.sidebar = closed ? "collapsed" : "expanded";
      try {
        localStorage.setItem("fabrix.sidebar", root.dataset.sidebar);
      } catch {
        /* storage unavailable: state is per-page only */
      }
      sync();
      setTimeout(() => dispatchEvent(new Event("resize")), 260);
    });
  });
})();
