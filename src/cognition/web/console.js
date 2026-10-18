// POST + SSE avoids putting investigation execution behind a reconnecting GET.
export async function readSSE(response, onEvent) {
  if (!response.ok) throw new Error(`Investigation could not start (${response.status}).`);
  if (!response.body) throw new Error("Response streaming is unavailable in this browser.");
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let pending = "", result;
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
      let end;
      while ((end = pending.indexOf("\n\n")) !== -1) {
        const block = pending.slice(0, end);
        pending = pending.slice(end + 2);
        const lines = block.split("\n");
        const type = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!type || !data) continue;
        const parsed = JSON.parse(data);
        onEvent(type, parsed);
        if (type === "result") result = parsed;
      }
      if (pending.length > 1024 * 1024) throw new Error("Stream frame exceeded its size limit.");
      if (done) break;
    }
  } finally { reader.releaseLock(); }
  if (!result) throw new Error("Connection closed before the outcome arrived. Check incident history before starting another run.");
  return result;
}

const mark = ok => (ok ? "✓" : "✗");
const sentence = text => text.charAt(0).toUpperCase() + text.slice(1);
// Tool arguments read as "(value=60, plant=kiln)" rather than raw JSON.
function fmtArgs(args) {
  const parts = Object.entries(args || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  return parts.length ? `(${parts.join(", ")})` : "()";
}

export function investigationConsole() {
  const $ = id => document.getElementById(id), log = $("console-log");
  let controller, follow = true, count = 0, textNode, session;
  const status = text => { $("console-state").textContent = text; };
  function row(label, text, time, kind = "") {
    const item = document.createElement("div"); item.className = `console-row ${kind}`; item.dataset.tag = label;
    const stamp = document.createElement("time");
    stamp.textContent = new Date(time || Date.now()).toLocaleTimeString([], { hour12: false });
    const tag = document.createElement("span"); tag.className = "console-tag"; tag.textContent = label;
    const content = document.createElement("span"); content.className = "console-content"; content.textContent = text;
    item.append(stamp, tag, content); log.append(item);
    return content;
  }
  function event(e) {
    log.querySelector(".console-empty")?.remove();
    count++; $("console-count").textContent = `${count} events`;
    const b = e.body;
    if (e.kind === "agent_text") {
      if (!textNode) textNode = row("agent", "", e.time, "console-agent");
      textNode.append(document.createTextNode(b.text));
    } else {
      textNode = null;
      if (e.kind === "tool_called") row("tool", `${b.name}${fmtArgs(b.args)}`, e.time);
      else if (e.kind === "tool_result") row("result", `Duty ${b.value}%  →  ${mark(b.safe)} within envelope · ${mark(b.recovered)} recovers · final error ${Number(b.final_error).toFixed(2)} °C`, e.time, b.recovered ? "console-success" : "");
      else if (e.kind === "proposed") row("proposal", b.summary, e.time);
      else if (e.kind === "started") row("system", `Investigation started from revision r${b.revision}`, e.time);
      else if (e.kind === "measurement") row("sample", `${Number(b.temperature).toFixed(1)} °C · r${b.revision} · stable ${b.stable_samples}/10`, e.time);
      else if (e.kind === "approval_requested") row("approval", "Validated proposal is waiting for an operator decision", e.time);
      else if (e.kind === "specialist_result") row("specialist", `${b.specialist_id}: ${b.advisory}`, e.time);
      else row("system", sentence(`${e.kind.replaceAll("_", " ")}${b.status ? `: ${b.status}` : ""}`), e.time);
    }
    if (follow) log.scrollTop = log.scrollHeight;
  }
  function reset() { count = 0; textNode = null; log.replaceChildren(); $("console-count").textContent = "0 events"; }
  function finish(incident) {
    status(incident.status);
    row("outcome", incident.reason, undefined, incident.status === "failed" ? "console-error" : "console-success");
    if (follow) log.scrollTop = log.scrollHeight;
  }
  $("console-follow").onclick = () => {
    follow = !follow; $("console-follow").setAttribute("aria-pressed", String(follow));
    $("console-follow").textContent = follow ? "Follow output" : "Output paused";
    if (follow) log.scrollTop = log.scrollHeight;
  };
  $("console-cancel").onclick = () => controller?.abort();
  $("console-export").onclick = () => {
    const url = URL.createObjectURL(new Blob([log.innerText], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `fabrix-${session || "investigation"}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return {
    detach(clear = false) {
      controller?.abort(); controller = null;
      if(clear) { reset(); status("Ready"); $("console-session").textContent = "Run an investigation to stream activity."; }
    },
    async watch(incidentId) {
      if(controller) controller.abort();
      reset(); session = incidentId; $("agent-console").open = true;
      $("console-session").textContent = `Automation · ${incidentId.slice(0,8)} · live activity`;
      const observer = new AbortController(); controller = observer;
      $("console-cancel").disabled = true;
      try {
        const response = await fetch(`/api/incidents/${encodeURIComponent(incidentId)}/stream`, {signal:observer.signal});
        return await readSSE(response, (type,data) => {
          if(controller !== observer) return;
          if(type === "session") status("Following automation");
          else if(type === "activity") event(data);
          else if(type === "result") finish(data);
        });
      } catch(error) {
        if(error.name !== "AbortError" && controller === observer) {
          status("Disconnected"); row("system",error.message,undefined,"console-error");
        }
        throw error;
      } finally { if(controller === observer) controller = null; }
    },
    async run(plantId, harness) {
      reset(); $("agent-console").open = true; status("Connecting");
      $("agent-console").scrollIntoView({ block: "nearest" });
      $("console-session").textContent = `${harness} · connecting`;
      controller = new AbortController(); $("console-cancel").disabled = false;
      try {
        const response = await fetch(`/api/plants/${encodeURIComponent(plantId)}/resolve/stream`, {
          method: "POST", headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
          body: JSON.stringify({ harness }), signal: controller.signal,
        });
        return await readSSE(response, (type, data) => {
          if (type === "session") {
            session = data.incident_id; status("Streaming");
            $("console-session").textContent = `${data.harness} · ${data.model || "deterministic"} · ${session.slice(0,8)}`;
          } else if (type === "activity") event(data);
          else if (type === "result") finish(data);
        });
      } catch (error) {
        status(error.name === "AbortError" ? "Cancellation requested" : "Connection error");
        row("system", error.name === "AbortError" ? "Cancellation requested. Check incident history for the final state." : error.message, undefined, "console-error");
        throw error;
      } finally { controller = null; $("console-cancel").disabled = true; }
    },
    show(incident, events) {
      if (controller) return;
      $("agent-console").open = true;
      reset(); session = incident.id;
      $("console-session").textContent = `${incident.harness} · ${session.slice(0,8)} · recorded activity`;
      events.forEach(event); finish(incident);
    },
  };
}
