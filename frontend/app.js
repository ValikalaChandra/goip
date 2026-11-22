const view = document.querySelector("#view");
const app = document.querySelector("#app");
const login = document.querySelector("#login");

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (response.status === 401) {
    app.classList.add("hidden");
    login.classList.remove("hidden");
    throw new Error("auth");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("json")) return response.json();
  return response.text();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "http:" || url.protocol === "https:") return esc(url.href);
  } catch (error) {}
  return "";
}
function statusClass(value) {
  if (value === "connected" || value === "delivered" || value === "ok" || value === "authenticated" || value === "configured") return "good";
  if (value === "offline" || value === "failed" || value === "missing") return "bad";
  return "warn";
}

function funnelTable(funnel) {
  if (!funnel) return "<p>No run yet.</p>";
  const rows = Object.entries(funnel).map(([stage, item]) =>
    `<tr><td>${stage}</td><td>${item.target}</td><td>${item.actual}</td><td>${item.shortfall}</td></tr>`
  ).join("");
  return `<table><tr><th>Stage</th><th>Target</th><th>Actual</th><th>Shortfall</th></tr>${rows}</table>`;
}

function statusMix(rows) {
  if (!rows || !rows.length) return "";
  const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
  if (!total) return "";
  const bar = rows.map((row) => `<span class="mix mix-${esc(row.status)}" style="width:${(Number(row.count) / total) * 100}%"></span>`).join("");
  const legend = rows.map((row) => `<span><i class="mix mix-${esc(row.status)}"></i>${esc(row.status.replaceAll("_", " "))} ${esc(row.count)}</span>`).join("");
  return `<section class="card section"><h2>Stored status</h2><div class="mixbar" role="img" aria-label="Stored opportunity status counts">${bar}</div><div class="legend">${legend}</div></section>`;
}

function state(kind, message) {
  return window.GOIPFormat.viewState(kind, message);
}

async function showOverview() {
  view.innerHTML = state("loading", "Loading the overview.");
  let data;
  try {
    data = await api("/api/overview");
  } catch (error) {
    view.innerHTML = state("error", error.message === "auth" ? "Sign in to see the overview." : "The overview could not be loaded.");
    return;
  }
  const run = data.latest_run;
  view.innerHTML = `
    <section class="grid">
      <article class="card"><span>Companies stored</span><strong>${esc(data.companies)}</strong></article>
      <article class="card"><span>Qualified, including priority</span><strong>${esc(data.qualified)}</strong></article>
      <article class="card"><span>Stored high priority</span><strong>${esc(data.high_priority)}</strong></article>
      <article class="card"><span>Switch</span><strong class="${statusClass(data.switch.connection)}">${esc(data.switch.connection)}</strong></article>
      <article class="card"><span>Unlinked signals</span><strong>${esc(data.unlinked_signals ?? "")}</strong></article>
      <article class="card"><span>Needs review</span><strong>${esc(data.needs_review ?? "")}</strong></article>
    </section>
    ${statusMix(data.status_counts)}
    <p class="note">Stored status comes from the first scoring run. The three-score rewrite has not been applied to those older rows, so a high-priority label is not a confirmed freelance opportunity.</p>
    <section class="card section">
      <h2>Latest run</h2>
      <p>${run ? `${esc(run.id)} · ${esc(run.status)} · switch ${esc(run.switch_status)} · telegram ${esc(run.telegram_status)}` : "No research run has been stored."}</p>
      ${run ? `<div class="table-scroll">${funnelTable(run.funnel)}</div>` : ""}
      ${run ? `<p><a href="/api/runs/${run.id}/export.csv">CSV</a> · <a href="/api/runs/${run.id}/export.json">JSON</a></p>` : ""}
      <p>Targets are configuration. Actual counts come from stored records. A shortfall is reported as a shortfall.</p>
    </section>
    <section class="grid" style="margin-top:16px">
      <article class="card"><h3>Industries</h3>${data.industries.map((row) => `<div>${esc(row.name)}: ${esc(row.count)}</div>`).join("") || "<p>None</p>"}</article>
      <article class="card"><h3>Countries</h3>${data.countries.map((row) => `<div>${esc(row.name)}: ${esc(row.count)}</div>`).join("") || "<p>None</p>"}</article>
    </section>`;
}

async function showExplorer() {
  view.innerHTML = `<div class="filters"><input id="q" placeholder="Company"><select id="status"><option value="">Any status</option><option>high_priority</option><option>qualified</option><option>needs_review</option><option>research_requested</option><option>approved</option><option>rejected</option><option>outreach_drafted</option></select><button id="filter">Filter</button></div><div id="leads">${state("loading", "Loading opportunities.")}</div>`;
  const load = async () => {
    const params = new URLSearchParams();
    const q = document.querySelector("#q").value;
    const status = document.querySelector("#status").value;
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    document.querySelector("#leads").innerHTML = state("loading", "Loading opportunities.");
    let data;
    try {
      data = await api("/api/opportunities?" + params.toString());
    } catch (error) {
      document.querySelector("#leads").innerHTML = state("error", "The opportunity list could not be loaded.");
      return;
    }
    if (!data.opportunities.length) {
      document.querySelector("#leads").innerHTML = state("empty", "No opportunities match this filter.");
      return;
    }
    document.querySelector("#leads").innerHTML = `<div class="table-scroll"><table><tr><th>Lead</th><th>Company</th><th>Signal</th><th>Historical</th><th>Business</th><th>Technical</th><th>Freelance</th><th>Status</th><th>QA</th></tr>${
      data.opportunities.map((item) => `<tr><td><a href="#lead-${esc(item.id)}">${esc(item.id)}</a></td><td>${esc(item.company)}</td><td>${esc(item.signal || "")}</td><td>${esc(item.score ?? "")}</td><td>${esc(item.business_signal_score ?? "")}</td><td>${esc(item.technical_evidence_score ?? "")}</td><td>${esc(item.freelance_fit_score ?? "")}</td><td><span class="pill pill-${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(item.qa_verdict || "")}</td></tr>`).join("")
    }</table></div>`;
    document.querySelectorAll("#leads a").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        showLead(link.textContent);
      });
    });
  };
  document.querySelector("#filter").addEventListener("click", load);
  await load();
}

function classTag(value) {
  const known = ["observed_fact", "derived_fact", "inference", "hypothesis", "unknown"];
  const label = known.includes(value) ? value : "unknown";
  return `<span class="tag class-${esc(label)}">${esc(label)}</span>`;
}

function evaluationBlock(row, currentId) {
  if (!row) return state("empty", "No versioned evaluation is stored yet. The historical composite score is unchanged.");
  const current = row.id && row.id === currentId;
  const findings = (row.findings || []).map((item) => `
    <li>
      ${classTag(item.classification)}
      <strong>${esc(item.claim)}</strong>
      <div>Source ${esc(item.source_id || "none")} · ${safeUrl(item.source_url) ? `<a href="${safeUrl(item.source_url)}">${esc(item.source_url)}</a>` : "no url"}</div>
      ${item.quotation ? `<blockquote>${esc(item.quotation)}</blockquote>` : ""}
      <div>Published ${esc(item.published_at || "unknown")} · Retrieved ${esc(item.retrieved_at || "unknown")} · Confidence ${esc(item.confidence)} · ${esc(item.verification_status)}</div>
    </li>`).join("");
  const services = (row.services || []).map((item) => `
    <li>${item.proposed_service ? esc(item.proposed_service) : "Further research, no service recommended"}
      · ${classTag(item.evidence_classification)}
      <div>${esc(item.why || "")}</div>
      <div>Missing: ${esc(item.missing || "")}</div>
    </li>`).join("");
  const checks = ((row.detail || {}).qa || {}).checks || [];
  const warnings = checks.filter((check) => check.result === "reject" || check.result === "flag");
  const agents = (row.agent_contributions || []).map((item) => `<li>${esc(item.agent)} · ${esc(item.body)}</li>`).join("");
  const reviews = (row.reviews || []).map((item) => `<li>${esc(item.action)} · ${esc(item.note)} · ${esc(item.actor)} · ${esc(item.at || "")}</li>`).join("");
  return `
    <article class="${current ? "current" : ""}">
    <p>${current ? "Current evaluation" : "Historical evaluation"} · version ${esc(row.version)} · ${esc(row.method)} · ${esc(row.created_at || "undated")}</p>
    <p>QA ${esc(row.qa_verdict)} · qualification ${esc(row.qualification)} · configuration ${esc(row.config_version || "not recorded")}</p>
    <p>Previous evaluation: ${esc(row.previous_evaluation_id || "none, this is the first stored version")}</p>
    <div class="scores">
      <article><span>Business signal</span><strong>${esc(row.business_signal_score ?? "n/a")}</strong></article>
      <article><span>Technical evidence</span><strong>${esc(row.technical_evidence_score ?? "n/a")}</strong></article>
      <article><span>Freelance fit</span><strong>${esc(row.freelance_fit_score ?? "n/a")}</strong></article>
      <article><span>Confidence</span><strong>${esc(row.confidence)}</strong></article>
    </div>
    <p>Historical composite score kept on this version: ${esc(row.legacy_score ?? "n/a")}. Confidence is separate from the scores. None of these numbers is a probability of hiring.</p>
    <h3>Findings</h3>
    <ul class="findings">${findings || "<li>None</li>"}</ul>
    <h3>Services</h3>
    <ul>${services || "<li>None</li>"}</ul>
    <h3>Quality assurance</h3>
    ${warnings.length ? `<ul>${warnings.map((check) => `<li class="qa-${esc(check.result)}">${esc(check.result)} · ${esc(check.name)} · ${esc(check.detail)}</li>`).join("")}</ul>` : "<p>No QA warnings on this version.</p>"}
    <p>${esc(row.limitations || "")}</p>
    <h3>Review recorded against this version</h3>
    <ul>${reviews || "<li>No human review is tied to this version.</li>"}</ul>
    <h3>Agent contributions captured with this version</h3>
    <ul>${agents || "<li>No agent message for this lead was stored with the version.</li>"}</ul>
    </article>`;
}

async function showLead(id) {
  view.innerHTML = state("loading", "Loading the opportunity.");
  let item;
  try {
    item = await api("/api/opportunities/" + id);
  } catch (error) {
    view.innerHTML = state("error", error.message === "Lead not found" ? "That lead is not in the database." : "The opportunity could not be loaded.");
    return;
  }
  const versions = item.evaluations || [];
  const current = versions.filter((row) => row.method === "v2_dimensions").slice(-1)[0];
  const history = versions.filter((row) => row.id !== item.current_evaluation_id).map((row) => evaluationBlock(row, item.current_evaluation_id)).join("");
  const tasks = (item.research_tasks || []).map((task) => `<li>${esc(task.status)} · ${esc((task.agents || []).join(", "))} · ${esc(task.note)}</li>`).join("");
  const events = (item.status_events || []).map((event) => `<li>${esc(event.from_status || "none")} → ${esc(event.to_status)} · ${esc(event.actor)} · ${esc(event.reason)}</li>`).join("");
  view.innerHTML = `
    <article class="card">
      <h2>${esc(item.company)} <span class="tag">${esc(item.id)}</span></h2>
      <p>Current status: <span class="pill pill-${esc(item.status)}">${esc(item.status)}</span>. Historical composite score: ${esc(item.score ?? "n/a")}. Current evaluation: ${esc(item.current_evaluation_id || "none")}.</p>
      <p>Commercial intent: ${esc((item.commercial_intent || {}).classification || "unknown")}. ${esc((item.commercial_intent || {}).reason || "")}</p>
      <p>${item.service_supported ? `Validated service: ${esc(item.service)}` : `Historical recommendation, not validated: ${esc(item.service || "none")}`}</p>
      <p>${safeUrl(item.website) ? `<a href="${safeUrl(item.website)}">${safeUrl(item.website)}</a>` : "Website not established from the source."}</p>
      <p>The status can change when a person reviews the lead. Stored evaluation versions stay as written.</p>
      <h3>Current scores</h3>
      ${current ? evaluationBlock(current, item.current_evaluation_id) : state("empty", "No three-score evaluation is stored yet.")}
      <h3>Evaluation history</h3>
      <div class="history">${history || state("empty", "No evaluation history is stored.")}</div>
      <h3>Sources</h3>
      ${(item.signals || []).length ? (item.signals || []).map((signal) => `<p><strong>${esc(signal.signal_type)}</strong> · <a href="${safeUrl(signal.source_url)}">${esc(signal.source_name)}</a><br>${esc(signal.evidence)}<br><span class="tag">${esc(signal.claim_kind || "unknown")}</span></p>`).join("") : state("empty", "No source is stored for this lead.")}
      <h3>Research tasks</h3>
      <ul>${tasks || "<li>No additional research has been requested.</li>"}</ul>
      <h3>Audit trail</h3>
      <ul>${events || "<li>No status change is recorded.</li>"}</ul>
      <form class="review" id="review">
        <h3>Human review</h3>
        <p>Approval records further consideration. It does not send outreach. Rejecting keeps the evaluation history.</p>
        <textarea id="note" placeholder="Reviewer note"></textarea>
        <p>
          <button type="button" data-act="approve">Approve for further consideration</button>
          <button type="button" data-act="reject">Reject</button>
          <button type="button" data-act="request_research">Request additional research</button>
          <button type="button" data-act="outreach">Draft outreach</button>
        </p>
        <p id="review-error" class="bad"></p>
      </form>
      <pre>${(item.drafts || []).map((draft) => esc(draft.body)).join("\n\n")}</pre>
    </article>`;
  view.querySelectorAll("button[data-act]").forEach((button) => {
    button.addEventListener("click", async () => {
      const act = button.dataset.act;
      const note = document.querySelector("#note").value;
      const error = document.querySelector("#review-error");
      error.textContent = "";
      try {
        if (act === "outreach") {
          const draft = await api(`/api/opportunities/${id}/outreach`, { method: "POST", body: "{}" });
          error.textContent = draft.sent ? "The draft was sent." : "Draft stored. It was not sent.";
        } else {
          const result = await api(`/api/opportunities/${id}/decision`, { method: "POST", body: JSON.stringify({ action: act, note }) });
          if (result.outreach_sent) error.textContent = "Outreach was sent.";
        }
        showLead(id);
      } catch (failure) {
        error.textContent = failure.message;
      }
    });
  });
}

async function showActivity() {
  view.innerHTML = state("loading", "Loading Switch activity.");
  let data;
  try {
    data = await api("/api/activity");
  } catch (error) {
    view.innerHTML = state("error", "Switch activity could not be loaded.");
    return;
  }
  if (!data.messages.length) {
    view.innerHTML = state("empty", "No Switch messages are stored.");
    return;
  }
  view.innerHTML = `<section class="card"><h2>Agents in this room</h2><p>Seven agents are registered. A row in the table is a stored message. It is not a claim that every agent finished a task on the latest run.</p><ul class="agents"><li>goip-discovery</li><li>goip-company-research</li><li>goip-technical-intelligence</li><li>goip-qualification</li><li>goip-strategy</li><li>goip-quality-assurance</li><li>goip-orchestrator</li></ul></section><div class="table-scroll section"><table><tr><th>When</th><th>Agent</th><th>Direction</th><th>Delivery</th><th>Message</th></tr>${
    data.messages.map((row) => `<tr><td>${esc(row.at)}</td><td>${esc(row.agent)}</td><td>${esc(row.direction)}</td><td class="${statusClass(row.delivered)}">${esc(row.delivered)}</td><td>${esc(row.body)}</td></tr>`).join("")
  }</table></div>`;
}

async function showSources() {
  view.innerHTML = state("loading", "Loading sources.");
  let data;
  try {
    data = await api("/api/sources");
  } catch (error) {
    view.innerHTML = state("error", "Sources could not be loaded.");
    return;
  }
  if (!data.sources.length) {
    view.innerHTML = state("empty", "No source health rows are stored.");
    return;
  }
  view.innerHTML = `<div class="table-scroll"><table><tr><th>Source</th><th>Domain</th><th>Method</th><th>Status</th><th>Records</th><th>Error</th></tr>${
    data.sources.map((row) => `<tr><td>${esc(row.name)}</td><td>${esc(row.parent_domain)}</td><td>${esc(row.access_method)}</td><td class="${statusClass(row.status)}">${esc(row.status)}</td><td>${esc(row.records)}</td><td>${esc(row.error || "")}</td></tr>`).join("")
  }</table></div>`;
}

async function showSettings() {
  const data = await api("/api/settings");
  const integrations = data.integrations || {};
  const rows = Object.entries(integrations).map(([name, status]) => `<div><span>${esc(name)}</span><strong class="${statusClass(status)}">${esc(status)}</strong></div>`).join("");
  view.innerHTML = `<section class="card"><h2>Integrations</h2><div class="integrations">${rows}</div><p>Secrets are not returned by this API. A configured integration is not the same as a delivered report.</p></section><details class="card section"><summary>Runtime configuration</summary><pre>${esc(JSON.stringify(data.runtime, null, 2))}</pre></details>`;
}

async function showReconciliation() {
  view.innerHTML = state("loading", "Loading unlinked signals.");
  let data;
  try {
    data = await api("/api/reconciliation");
  } catch (error) {
    view.innerHTML = state("error", "Reconciliation could not be loaded.");
    return;
  }
  if (!data.signals.length) {
    view.innerHTML = state("empty", "No reconciliation rows are stored. Unlinked signals have not been classified yet.");
    return;
  }
  view.innerHTML = `<p class="note">A headline mention is not a confirmed company. Confirm is the only action that links a signal.</p><div class="table-scroll"><table><tr><th>Source</th><th>Title</th><th>Class</th><th>Candidate</th><th>Why</th><th></th></tr>${
    data.signals.map((row) => `<tr><td>${esc(row.source_name)}</td><td>${safeUrl(row.source_url) ? `<a href="${safeUrl(row.source_url)}">${esc(row.title)}</a>` : esc(row.title)}</td><td>${esc(row.classification)}</td><td>${esc(row.candidate_company || "")}</td><td>${esc(row.rationale)}</td><td>${row.classification === "ambiguous_match" && row.candidate_company_id ? `<button data-signal="${esc(row.signal_id)}" data-company="${esc(row.candidate_company_id)}" data-act="confirm">Confirm</button>` : ""}<button data-signal="${esc(row.signal_id)}" data-act="unassigned">Keep unassigned</button></td></tr>`).join("")
  }</table></div>`;
  view.querySelectorAll("button[data-act]").forEach((button) => {
    button.addEventListener("click", async () => {
      const body = { action: button.dataset.act, company_id: button.dataset.company || "", note: "dashboard" };
      try {
        await api("/api/reconciliation/" + button.dataset.signal, { method: "POST", body: JSON.stringify(body) });
        showReconciliation();
      } catch (error) {
        view.insertAdjacentHTML("afterbegin", state("error", error.message));
      }
    });
  });
}

const screens = { overview: showOverview, explorer: showExplorer, reconciliation: showReconciliation, activity: showActivity, sources: showSources, settings: showSettings };
document.querySelectorAll("nav button[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("nav button[data-view]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    screens[button.dataset.view]().catch((error) => { view.textContent = error.message; });
  });
});
document.querySelector("#run").addEventListener("click", async () => {
  view.innerHTML = "<p>Research is running. This can take a few minutes because agents wait on each other.</p>";
  try {
    const result = await api("/api/runs", { method: "POST", body: "{}" });
    view.innerHTML = `<p>Run ${result.run_id} finished in mode ${result.mode}.</p>`;
    showOverview();
  } catch (error) {
    view.innerHTML = `<p class="bad">${error.message}</p>`;
  }
});
login.addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: document.querySelector("#token").value }) });
  if (!response.ok) {
    document.querySelector("#login-error").textContent = "Token rejected.";
    return;
  }
  login.classList.add("hidden");
  app.classList.remove("hidden");
  showOverview().catch((error) => { view.textContent = error.message; });
});
fetch("/api/overview").then((response) => {
  if (response.ok) {
    login.classList.add("hidden");
    app.classList.remove("hidden");
    showOverview();
  }
}).catch(() => {});
