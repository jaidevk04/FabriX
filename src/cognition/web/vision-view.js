// Vision core workspace: a clean camera viewer (nothing is drawn over the footage), a camera rail of thumbnails, a detection log and the
// clip lookup (which recorded clips exist for which camera state). Read only. Frames are generated placeholders
// unless a clip file is present under web/media/vision/<industry>/ (see the footage library card).
import { badge, chip, el, glyph, http, lamp, meter, number, svg } from "./cores-parts.js";

const PLAN_REFRESH_MS = 15000;
const slug = (label) => label.trim().toLowerCase().replaceAll(" ", "-");
const severityLevel = (s) => (s >= 0.6 ? "crit" : s > 0 ? "warn" : "ok");
const STATUS = { ok: "Clear", warn: "Detection", crit: "Alert" };

export function createVisionView({ base }) {
  const root = el("div", "vv");
  let selected = null;
  let cameras = [];
  let plan = null;
  let planAt = 0;
  let planning = false;
  let tick = -1;
  let generation = 0;
  let clipKey = null;
  const thumbs = new Map(); // camera id -> img element

  // ---------- skeleton ----------
  const head = el("header", "vv-head");
  const headText = el("div");
  headText.append(el("h3", "", "Camera feeds"), el("p", "cr-sub", "Simulated detector on generated frames, or recorded clips when present"));
  const headChips = el("div", "vv-head-chips");
  head.append(headText, headChips);

  const viewer = el("section", "vv-viewer");
  const viewerHead = el("div", "vv-viewer-head");
  const stage = el("div", "vv-stage");
  const media = el("div", "vv-media");
  const frame = el("img", "vv-frame");
  frame.alt = "";
  frame.decoding = "async";
  const video = el("video", "vv-video");
  video.muted = true; video.loop = true; video.playsInline = true; video.autoplay = true;
  video.setAttribute("aria-hidden", "true");
  video.hidden = true;
  media.append(frame, video);
  stage.append(media);
  const strip = el("div", "vv-strip");
  viewer.append(viewerHead, stage, strip);

  const rail = el("aside", "vv-rail");
  rail.setAttribute("aria-label", "Cameras");
  const lower = el("div", "vv-lower");
  const logCard = el("section", "vv-card");
  lower.append(logCard);
  const top = el("div", "vv-top");
  top.append(viewer, rail);
  root.append(head, top, lower);

  // ---------- helpers ----------
  const camLevel = (c) => (c.detections.length ? severityLevel(Math.max(...c.detections.map((d) => d.severity))) : "ok");
  const worst = (c) => [...c.detections].sort((a, b) => b.severity - a.severity)[0] ?? null;

  async function loadPlan(force = false) {
    if (planning || (!force && plan && performance.now() - planAt < PLAN_REFRESH_MS)) return;
    planning = true;
    const token = generation;
    try {
      const next = await http("GET", `${base()}/cameras/clips`);
      if (token !== generation) return;
      plan = next;
      planAt = performance.now();
      showSelected(true);
      renderRail();
    } catch { /* the next refresh retries */ } finally { planning = false; }
  }

  const clipFor = (camera, detection) => {
    if (!plan) return null;
    const wanted = detection ? slug(detection.label) : "normal";
    const find = (key) => plan.clips.find((c) => c.camera === camera.id && c.file.split("__")[1]?.startsWith(`${key}.`) && c.available);
    return find(wanted) ?? find("normal") ?? null;
  };

  // Preload then swap, so a refreshed frame never flashes blank.
  function setFrame(img, url) {
    const next = new Image();
    next.onload = () => { img.src = url; };
    next.src = url;
  }
  const frameUrl = (id) => `${base()}/cameras/${id}/frame.svg?overlay=false&t=${Date.now()}`;

  // ---------- viewer ----------
  function showSelected(forceClip = false) {
    const camera = cameras.find((c) => c.id === selected);
    if (!camera) return;
    const level = camLevel(camera);
    const top_ = worst(camera);
    stage.dataset.level = level;
    viewer.dataset.level = level;
    const clip = clipFor(camera, top_);
    const key = clip ? clip.url : "frame";
    if (key !== clipKey || forceClip) {
      clipKey = key;
      if (clip) {
        if (video.getAttribute("src") !== clip.url) { video.src = clip.url; video.play().catch(() => {}); }
        video.hidden = false; frame.hidden = true;
        video.onerror = () => { video.hidden = true; frame.hidden = false; clipKey = "frame"; };
      } else {
        video.hidden = true; frame.hidden = false;
        video.removeAttribute("src"); video.load();
      }
    }
    // Viewer header
    const title = el("div", "vv-viewer-title");
    title.append(glyph("camera", "cr-glyph vv-title-icon"), el("strong", "", camera.name), el("span", "cr-sub", `${camera.zone} · ${camera.equipment}`));
    const state = chip(STATUS[level], level);
    state.classList.add("vv-state");
    viewerHead.replaceChildren(title, state);
    // Strip under the stage: what the camera can detect and what it sees now
    const chips = el("div", "cr-chips");
    if (!camera.detects.length) chips.append(chip("no detection capability configured", "off", "This camera has no detector labels in the simulation yet"));
    for (const label of camera.detects) {
      const active = camera.detections.some((d) => d.label === label);
      chips.append(chip(label, active ? severityLevel(camera.detections.find((d) => d.label === label).severity) : "info", active ? "Detected now" : "Can detect"));
    }
    strip.replaceChildren(el("span", "vv-strip-label", "Can detect"), chips);
  }

  function refreshFrames() {
    const camera = cameras.find((c) => c.id === selected);
    if (camera && frame.hidden === false) setFrame(frame, frameUrl(camera.id));
    for (const [id, img] of thumbs) setFrame(img, frameUrl(id));
  }

  // ---------- rail ----------
  // Selection only flips attributes, so the thumbnails are never rebuilt or reloaded on a click.
  function applySelection() {
    cameras.forEach((c, i) => {
      const button = rail.children[i];
      if (!button) return;
      button.dataset.selected = String(c.id === selected);
      button.setAttribute("aria-pressed", String(c.id === selected));
    });
  }
  function select(id) {
    if (id === selected) return;
    selected = id;
    clipKey = null;
    applySelection();
    showSelected(true);
    setFrame(frame, frameUrl(id));
  }

  function renderRail() {
    const signature = JSON.stringify(cameras.map((c) => [c.id, camLevel(c), c.detections.length, clipFor(c, worst(c))?.url ?? null]));
    if (rail.dataset.sig === signature) return;
    rail.dataset.sig = signature;
    thumbs.clear();
    rail.replaceChildren(...cameras.map((c) => {
      const level = camLevel(c);
      const button = el("button", "vv-cam");
      button.type = "button";
      button.dataset.level = level;
      const thumb = el("div", "vv-thumb");
      const img = el("img");
      img.alt = "";
      img.src = frameUrl(c.id);
      thumbs.set(c.id, img);
      thumb.append(img);
      // Thumbnail of the recorded clip when one exists; the generated frame stays as the fallback.
      const clip = clipFor(c, worst(c));
      if (clip) {
        const mini = el("video", "vv-thumb-video");
        mini.muted = true; mini.loop = true; mini.playsInline = true; mini.autoplay = true;
        mini.setAttribute("aria-hidden", "true");
        mini.src = clip.url;
        mini.addEventListener("loadeddata", () => { img.hidden = true; mini.play().catch(() => {}); });
        mini.addEventListener("error", () => mini.remove());
        thumb.append(mini);
      }
      const text = el("div", "vv-cam-text");
      const line = el("div", "vv-cam-line");
      line.append(el("strong", "", c.name), lamp(level));
      text.append(line, el("span", "cr-sub", `${c.zone} · ${c.equipment}`));
      const note = c.detections.length
        ? chip(`${c.detections.length} detection${c.detections.length === 1 ? "" : "s"}`, level)
        : c.detects.length ? chip("clear", "ok") : chip("idle", "off", "No detector labels configured");
      text.append(note);
      button.append(thumb, text);
      button.addEventListener("click", () => select(c.id));
      return button;
    }));
    applySelection();
  }

  // ---------- log and library ----------
  function renderLog() {
    const rows = cameras.flatMap((c) => c.detections.map((d) => ({ c, d }))).sort((a, b) => b.d.severity - a.d.severity);
    const signature = JSON.stringify(rows.map(({ c, d }) => [c.id, d.label, Math.round(d.severity * 100), Math.round(d.confidence * 100)]));
    if (logCard.dataset.sig === signature) return;
    logCard.dataset.sig = signature;
    const title = el("div", "vv-card-head");
    title.append(el("h4", "cr-mini", "Detections now"), badge("SIM", "Simulated detector, not a trained model"));
    if (!rows.length) {
      const empty = el("div", "vv-empty");
      empty.append(glyph("check", "cr-glyph vv-empty-icon"), el("strong", "", "All cameras clear"), el("span", "cr-sub", "The detector sees no defects or baseline deviations."));
      logCard.replaceChildren(title, empty);
      return;
    }
    const table = el("div", "vv-table");
    const header = el("div", "vv-row vv-row--head");
    for (const t of ["Camera", "Detection", "Confidence", "Severity"]) header.append(el("span", "", t));
    table.append(header);
    for (const { c, d } of rows) {
      const level = severityLevel(d.severity);
      const row = el("div", "vv-row");
      row.dataset.level = level;
      const conf = el("span", "vv-meter");
      conf.append(meter(d.confidence, 1, { level: "info" }), el("span", "cr-num", `${Math.round(d.confidence * 100)}%`));
      const sev = el("span", "vv-meter");
      sev.append(meter(d.severity, 1, { level }), el("span", "cr-num", number(d.severity, 2)));
      row.append(el("span", "vv-cell-strong", c.name), chip(d.label, level), conf, sev);
      row.addEventListener("click", () => select(c.id));
      table.append(row);
    }
    logCard.replaceChildren(title, table);
  }

  function renderHead(data) {
    const count = cameras.reduce((n, c) => n + c.detections.length, 0);
    const live = chip(`live · tick ${data.tick}`, "ok", "Updated once per second");
    live.classList.add("lv-live");
    headChips.replaceChildren(
      live,
      chip(`${cameras.length} cameras`, "info"),
      count ? chip(`${count} detection${count === 1 ? "" : "s"}`, cameras.some((c) => camLevel(c) === "crit") ? "crit" : "warn") : chip("all clear", "ok"),
      badge("SIM", "Generated frames with a simulated detector"),
    );
  }

  // ---------- public ----------
  return {
    root,
    update(data) {
      cameras = data.cameras;
      const changed = data.tick !== tick;
      tick = data.tick;
      if (!cameras.some((c) => c.id === selected)) {
        selected = [...cameras].sort((a, b) => (worst(b)?.severity ?? 0) - (worst(a)?.severity ?? 0))[0]?.id ?? null;
        clipKey = null;
        rail.dataset.sig = "";
      }
      renderHead(data);
      renderRail();
      applySelection();
      showSelected();
      renderLog();
      loadPlan();
      if (changed) refreshFrames();
    },
    reset() {
      generation += 1;
      plan = null; planAt = 0; selected = null; clipKey = null; cameras = []; thumbs.clear();
      for (const node of [rail, logCard]) delete node.dataset.sig;
      rail.replaceChildren(); logCard.replaceChildren();
    },
    destroy() { generation += 1; video.pause(); },
  };
}
