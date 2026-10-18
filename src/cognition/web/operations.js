const $ = id => document.getElementById(id);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if(text !== undefined) node.textContent = text;
  if(className) node.className = className;
  return node;
};
const names = {reflexive:"Reflexive",perceptual:"Perceptual",cognitive:"Cognitive"};
const eventNames = {started:"Investigation opened",proposed:"Plan proposed",approval_requested:"Operator approval required",approval_decided:"Approval decision recorded",command_dispatch:"Official MCP command dispatch",command_committed:"Gateway committed command",action_applied:"Actuator command applied",measurement:"Fresh process measurement",verified:"Sustained recovery verified",verification_failed:"Recovery verification failed",cancelled:"Investigation stopped",completed:"Investigation updated"};

export function operationsView() {
  let current, plant, points = [], prior, lastAnnouncement;
  const dialog = $("layer-dialog");
  $("layer-dialog-close").onclick = () => dialog.close();
  for(const layer of Object.keys(names)) {
    $("layer-"+layer).onclick = () => {
      if(!current) return;
      $("layer-dialog-title").textContent = names[layer]+" layer";
      const report = current[layer], host = $("layer-dialog-content");
      host.replaceChildren();
      host.append(element("p", report.basis || report.authority));
      if(layer === "reflexive") {
        host.append(element("p",report.policy));
        host.append(element("p",`Command ${report.commanded_duty.toFixed(1)}% · actuator ${report.actuator_position.toFixed(1)}% · cognitive control ${report.cognitive_control_permitted ? "permitted within gateway limits" : "blocked"}.`));
      } else if(layer === "perceptual") {
        host.append(element("p",`Provider: ${report.provider}. ${report.trained_model ? "Learned provider" : "Simulator heuristic; no trained model deployed"}. ${report.excluded_observations} expired or obsolete observations excluded.`));
        for(const item of report.observations) {
          const row = element("article",undefined,"layer-evidence");
          row.append(element("strong",`${item.label} · ${item.status}`));
          row.append(element("p",`${item.model} / ${item.source} · ${(item.confidence*100).toFixed(0)}% confidence · revision ${item.revision}`));
          row.append(element("p",item.summary));
          host.append(row);
        }
        for(const conflict of report.conflicts) host.append(element("p",conflict,"layer-conflict"));
        host.append(element("p",report.evidence_policy));
      } else {
        host.append(element("p",`Industry skill: ${current.skill}. Harness: ${report.harness || "Not selected for a run"}.`));
        host.append(element("p",report.reason));
        const list = element("ol",undefined,"action-timeline");
        for(const event of current.events) {
          const row = element("li");
          row.append(element("time",new Date(event.time).toLocaleTimeString()));
          row.append(element("span",eventNames[event.kind] || event.kind));
          if(event.kind === "measurement") row.append(element("small",`${event.body.temperature.toFixed(1)} °C · actuator ${event.body.actuator?.toFixed(1) ?? "—"}% · stable ${event.body.stable_samples}/10`));
          list.append(row);
        }
        host.append(list);
      }
      dialog.showModal();
    };
  }
  return {
    update(data) {
      if(plant !== data.snapshot.spec.id) { plant=data.snapshot.spec.id; points=[]; prior=null; }
      current = data;
      const state = data.snapshot;
      const statuses = {reflexive:data.reflexive.status,perceptual:data.perceptual.conflicts.length ? "conflict" : data.perceptual.status,cognitive:data.cognitive.phase};
      for(const [layer,status] of Object.entries(statuses)) {
        const button = $("layer-"+layer);
        button.dataset.status = status;
        button.querySelector("strong").textContent = status.replaceAll("_"," ");
        button.setAttribute("aria-label",`${names[layer]} layer: ${status.replaceAll("_"," ")}. Inspect evidence.`);
      }
      if(state.quality === "good" && (!prior || prior.revision !== state.revision)) {
        points.push({temperature:state.temperature, tick:state.tick});
        points=points.slice(-60);
      }
      const trend = prior && state.tick > prior.tick && state.quality === "good" && prior.quality === "good" ? state.temperature-prior.temperature : 0;
      const direction = Math.abs(trend)<0.05 ? "Steady" : trend<0 ? "Falling" : "Rising";
      $("response-trend").textContent = state.quality !== "good" ? "Signal unavailable" : `${direction}${Math.abs(trend)>=0.05 ? ` ${Math.abs(trend).toFixed(1)} °C since last sample` : ""}`;
      const applied = data.response.applied;
      const action = data.incident?.proposal?.action;
      let commandText = "No cognitive command applied";
      if (action) {
        if (action.control === "thermal_duty" || typeof action.value === "number") {
          commandText = applied
            ? `Last command: ${action.value.toFixed(1)}% duty applied`
            : `${action.value.toFixed(1)}% proposed · awaiting execution`;
        } else if (action.control === "maintenance") {
          commandText = applied
            ? `Last command: ${action.remedy} on ${action.equipment} applied`
            : `Repair ${action.remedy} on ${action.equipment} proposed`;
        } else if (action.control === "monitor_config") {
          commandText = applied
            ? `Last config: ${action.setting} on ${action.target || action.core} applied`
            : `${action.setting} on ${action.target || action.core} proposed`;
        }
      }
      $("response-command").textContent = commandText;
      $("response-verification").textContent = data.response.verified ? "Recovery verified" : data.receipt?.verification === "pending" ? data.incident.status === "verifying" ? "Verifying measured response" : "Verification incomplete" : data.receipt?.recovered ? "New deviation · prior recovery was verified" : data.response.source;
      $("response-verification").dataset.verified=String(data.response.verified);
      const svg = $("response-sparkline"), line = svg.querySelector("polyline");
      svg.hidden = points.length < 2;
      $("response-trend").hidden = points.length < 2;
      if(points.length > 1) {
        const low = Math.min(state.target,...points.map(p=>p.temperature))-1;
        const high = Math.max(state.target,...points.map(p=>p.temperature))+1;
        const y = value => 31-(value-low)/(high-low)*26;
        line.setAttribute("points",points.map((p,i)=>`${i/(points.length-1)*270},${y(p.temperature)}`).join(" "));
        const target = svg.querySelector("line");
        target.setAttribute("y1",y(state.target)); target.setAttribute("y2",y(state.target));
      } else line.setAttribute("points","");
      svg.setAttribute("aria-label",`Observed temperature trend: ${points.length} simulator snapshots. ${direction}.`);
      const announcement = `${statuses.reflexive}|${statuses.perceptual}|${statuses.cognitive}|${data.response.verified}`;
      if(announcement !== lastAnnouncement) {
        $("operations-announcer").textContent = `Reflexive ${statuses.reflexive}, perceptual ${statuses.perceptual}, cognitive ${statuses.cognitive.replaceAll("_"," ")}. ${data.response.verified ? "Recovery verified." : ""}`;
        lastAnnouncement=announcement;
      }
      prior=state;
    },
    unavailable() {
      for(const layer of Object.keys(names)) $("layer-"+layer).querySelector("strong").textContent="Unavailable";
    },
  };
}
