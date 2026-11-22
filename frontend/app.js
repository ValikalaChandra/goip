const view = document.querySelector("#view");
const app = document.querySelector("#app");
const loginScreen = document.querySelector("#login-screen");
const login = document.querySelector("#login");
const FX = window.GOIPFX || { reduce: true, enter() {}, counters() {}, bars() {}, spotlight() {}, feel() {}, smooth() {}, toTop() {}, network() {}, stopNetwork() {} };

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (response.status === 401) {
    showLogin();
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

function state(kind, message) {
  return window.GOIPFormat.viewState(kind, message);
}

/* Source text can contain HTML or entities. Show it as plain text: DOMParser strips tags and decodes entities without running anything. */
function plain(value) {
  const text = String(value ?? "");
  if (!/[<&]/.test(text)) return text;
  try { return (new DOMParser().parseFromString(text, "text/html").body.textContent || "").replace(/\s+/g, " ").trim(); } catch (error) { return text; }
}

function host(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch (error) { return ""; }
}

const VERIFY = {
  source_linked: "Stored with its link. The page itself was not re-read when this was scored.",
  quote_matches_stored_text: "The quoted text matches what was stored.",
};

/* Room messages are Markdown. The dashboard shows them as readable plain text (no HTML is ever built from them). */
function mdText(value) {
  return String(value ?? "")
    .split("\n")
    .filter((line) => !/^\|\s*-{2,}/.test(line))
    .map((line) => line
      .replace(/^#{1,6}\s+/, "")
      .replace(/^\|\s*|\s*\|\s*$/g, "")
      .replace(/\s*\|\s*/g, " · ")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/^>\s?/, "")
      .replace(/^-\s+/, "• "))
    .join("\n")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

function nice(value) {
  return esc(String(value ?? "").replaceAll("_", " "));
}

function when(value) {
  if (!value) return "undated";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/* One call after every render: entrance, counters, bars, spotlight, press feel. */
function finish(root) {
  FX.enter(root, ".card, .table-scroll, .rec, .note", { stagger: 0.05 });
  FX.counters(root);
  FX.bars(root);
  FX.spotlight(root);
  FX.feel(document);
}

/* ---------------------------------------------------------------- shell */

function showLogin() {
  app.classList.add("hidden");
  loginScreen.classList.remove("hidden");
  FX.network(document.querySelector("#login-bg"));
}

function showApp() {
  FX.stopNetwork();
  loginScreen.classList.add("hidden");
  app.classList.remove("hidden");
  FX.smooth();
  FX.feel(document);
  pollSwitch();
}

async function pollSwitch() {
  const dot = document.querySelector("#switch-dot");
  const label = document.querySelector("#switch-label");
  try {
    const response = await fetch("/health");
    const data = await response.json();
    const live = data.switch === "connected";
    dot.className = "dot " + (live ? "live" : "off");
    label.textContent = live ? "Switch connected" : "Switch offline";
  } catch (error) {
    dot.className = "dot off";
    label.textContent = "API unreachable";
  }
  setTimeout(pollSwitch, 20000);
}

const TITLES = { overview: "Overview", agents: "Agents", explorer: "Opportunities", reconciliation: "Reconciliation", activity: "Switch room", sources: "Sources", settings: "Settings" };

/* ------------------------------------------------------------- overview */

function funnelBars(funnel) {
  if (!funnel) return "<p class='muted'>No run yet.</p>";
  return `<div class="funnel">${Object.entries(funnel).map(([stage, item]) => {
    const target = Number(item.target) || 0;
    const pct = target ? Math.min(100, (Number(item.actual) / target) * 100) : 0;
    return `<div class="funnel-row"><span class="label">${esc(stage)}</span><div class="track ${item.shortfall > 0 ? "short" : ""}"><b data-w="${pct.toFixed(1)}"></b></div><span class="num">${esc(item.actual)} / ${esc(item.target)}</span></div>`;
  }).join("")}</div>`;
}

function statusMix(rows) {
  if (!rows || !rows.length) return "";
  const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0);
  if (!total) return "";
  const bar = rows.map((row) => `<span class="mix mix-${esc(row.status)}" data-w="${((Number(row.count) / total) * 100).toFixed(2)}"></span>`).join("");
  const legend = rows.map((row) => `<span><i class="mix mix-${esc(row.status)}"></i>${nice(row.status)} <b class="mono">${esc(row.count)}</b></span>`).join("");
  return `<section class="card spot"><h2>Where the leads stand</h2><p class="muted">Stored status across every run. A person approves each step.</p><div class="mixbar" role="img" aria-label="Stored opportunity status counts">${bar}</div><div class="legend">${legend}</div></section>`;
}

function rankList(rows) {
  if (!rows || !rows.length) return "<p class='muted'>None recorded yet.</p>";
  const top = Math.max(...rows.map((row) => Number(row.count) || 0), 1);
  return `<div class="rank">${rows.slice(0, 8).map((row) => `<div class="rank-row"><span>${esc(row.name)}</span><span class="n">${esc(row.count)}</span><div class="bar"><b data-w="${((Number(row.count) / top) * 100).toFixed(1)}"></b></div></div>`).join("")}</div>`;
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
  const banner = data.llm && data.llm.ok === false
    ? `<section class="card banner" role="alert"><strong>The language model is not working.</strong><span>${esc(data.llm.message || "It did not answer.")} Until it is back, research quotes the source without a model summary, headline naming is off, and the room's free-text routing is off. Commands like <span class="mono">run</span>, <span class="mono">status</span> and <span class="mono">approve G…</span> still work.</span></section>`
    : "";
  const kpi = (label, value, cls = "", hint = "") => `<article class="card kpi spot lift ${cls}"><span>${esc(label)}</span><strong data-count="${esc(value ?? 0)}">0</strong>${hint ? `<small>${esc(hint)}</small>` : ""}</article>`;
  view.innerHTML = `
    ${banner}
    <section class="grid kpis">
      ${kpi("Companies stored", data.companies, "", "researched from public sources")}
      ${kpi("High priority", data.high_priority, "good", "states a freelance or contract need")}
      ${kpi("Qualified", data.qualified, "", "includes high priority")}
      ${kpi("Needs review", data.needs_review, "accent", "waiting for a person")}
      ${kpi("Unlinked signals", data.unlinked_signals, "", "classified in Reconciliation")}
      <article class="card kpi spot lift"><span>Switch</span><strong class="fs-26 ${statusClass(data.switch.connection)}">${esc(data.switch.connection)}</strong><small>agents collaborate in the room</small></article>
    </section>
    ${statusMix(data.status_counts)}
    <section class="two">
      <article class="card spot">
        <h2>Latest run</h2>
        <p class="muted mono">${run ? `${esc(run.id.slice(0, 8))} · ${esc(run.status)} · switch ${esc(run.switch_status)} · telegram ${esc(run.telegram_status)}` : "No research run has been stored."}</p>
        ${run ? funnelBars(run.funnel) : ""}
        ${run ? `<div class="links"><a href="/api/runs/${esc(run.id)}/export.csv">Download CSV</a><a href="/api/runs/${esc(run.id)}/export.json">Download JSON</a></div>` : ""}
        <p class="muted mt-14 fs-13">Targets are configuration. Bars show actual stored counts, and a shortfall stays visible instead of being padded.</p>
      </article>
      <article class="card spot"><h2>Industries</h2>${rankList(data.industries)}</article>
      <article class="card spot"><h2>Countries</h2>${rankList(data.countries)}</article>
    </section>`;
  finish(view);
}

/* ------------------------------------------------------------- explorer */

const PAGE = 100;

function leadRow(item) {
  return `<tr><td><a href="#lead-${esc(item.id)}" class="mono">${esc(item.id)}</a></td><td><strong>${esc(item.company)}</strong>${item.headline && plain(item.headline) !== item.company ? `<div class="muted fs-13 clip">${esc(plain(item.headline))}</div>` : ""}</td><td>${esc(item.signal || "")}</td><td>${safeUrl(item.source_url) ? `<a href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer" class="src-link" title="${esc(plain(item.headline || ""))}">${esc(host(item.source_url))} ↗</a>` : ""}${item.source_name ? `<div class="muted fs-13">${esc(item.source_name)}</div>` : ""}</td><td class="mono">${esc(item.business_signal_score ?? "")}</td><td class="mono">${esc(item.technical_evidence_score ?? "")}</td><td class="mono">${esc(item.freelance_fit_score ?? "")}</td><td><span class="pill pill-${esc(item.status)}">${nice(item.status)}</span></td><td>${esc(item.qa_verdict || "")}</td></tr>`;
}

async function showExplorer() {
  view.innerHTML = `<div class="filters"><input id="q" placeholder="Search a company" aria-label="Search a company"><select id="status" aria-label="Status"><option value="">Any status</option><option>high_priority</option><option>qualified</option><option>needs_review</option><option>research_requested</option><option>approved</option><option>rejected</option><option>outreach_drafted</option></select><button id="filter" class="primary" type="button">Filter</button></div><div id="leads">${state("loading", "Loading opportunities.")}</div>`;
  let offset = 0;
  const wire = (scope) => scope.querySelectorAll("a[href^='#lead-']").forEach((link) => {
    if (link.dataset.wired) return;
    link.dataset.wired = "1";
    link.addEventListener("click", (event) => { event.preventDefault(); showLead(link.textContent); });
  });
  const fetchPage = async () => {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    const q = document.querySelector("#q").value;
    const status = document.querySelector("#status").value;
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    return api("/api/opportunities?" + params.toString());
  };
  const counter = (shown, total) => `Showing <b>${esc(shown)}</b> of <b>${esc(total)}</b> opportunities`;
  const load = async () => {
    offset = 0;
    const box = document.querySelector("#leads");
    box.innerHTML = state("loading", "Loading opportunities.");
    let data;
    try {
      data = await fetchPage();
    } catch (error) {
      box.innerHTML = state("error", "The opportunity list could not be loaded.");
      return;
    }
    if (!data.opportunities.length) {
      box.innerHTML = state("empty", "No opportunities match this filter.");
      return;
    }
    offset = data.opportunities.length;
    box.innerHTML = `<p class="muted fs-13 mb-6" id="count">${counter(offset, data.total)}</p><div class="table-scroll"><table id="lead-table"><tr><th>Lead</th><th>Company</th><th>Signal</th><th>Source</th><th>Business</th><th>Technical</th><th>Freelance</th><th>Status</th><th>QA</th></tr>${data.opportunities.map(leadRow).join("")}</table></div>${offset < data.total ? `<p class="mt-14"><button id="more" class="btn" type="button">Show ${esc(Math.min(PAGE, data.total - offset))} more</button></p>` : ""}`;
    wire(box);
    FX.enter(box, "tr", { stagger: 0.02, y: 8 });
    const more = document.querySelector("#more");
    if (more) more.addEventListener("click", async () => {
      more.disabled = true;
      try {
        const next = await fetchPage();
        document.querySelector("#lead-table").insertAdjacentHTML("beforeend", next.opportunities.map(leadRow).join(""));
        offset += next.opportunities.length;
        document.querySelector("#count").innerHTML = counter(offset, next.total);
        wire(box);
        if (offset >= next.total) more.remove(); else { more.disabled = false; more.textContent = `Show ${Math.min(PAGE, next.total - offset)} more`; }
      } catch (error) {
        more.textContent = error.message;
      }
    });
  };
  document.querySelector("#filter").addEventListener("click", load);
  document.querySelector("#q").addEventListener("keydown", (event) => { if (event.key === "Enter") load(); });
  FX.feel(document);
  await load();
}

/* --------------------------------------------------------- lead details */

function classTag(value) {
  const known = ["observed_fact", "derived_fact", "inference", "hypothesis", "unknown"];
  const label = known.includes(value) ? value : "unknown";
  return `<span class="tag class-${esc(label)}">${nice(label)}</span>`;
}

function evaluationBlock(row, currentId) {
  if (!row) return state("empty", "No versioned evaluation is stored yet. The historical composite score is unchanged.");
  const current = row.id && row.id === currentId;
  const findings = (row.findings || []).map((item) => `
    <li>
      ${classTag(item.classification)}
      <strong>${esc(plain(item.claim))}</strong>
      <div class="muted">Source · ${safeUrl(item.source_url) ? `<a href="${safeUrl(item.source_url)}" rel="noopener noreferrer" target="_blank" title="${esc(item.source_id || "")}">${esc(host(item.source_url) || item.source_url)} ↗</a>` : "no url"}</div>
      ${item.quotation ? `<blockquote>${esc(plain(item.quotation))}</blockquote>` : ""}
      <div class="muted">Published ${esc(item.published_at || "unknown")} · Retrieved ${esc(item.retrieved_at || "unknown")} · Confidence ${esc(item.confidence)} · ${esc(item.verification_status)}</div>
    </li>`).join("");
  const services = (row.services || []).map((item) => `
    <li>${item.proposed_service ? esc(item.proposed_service) : "Further research, no service recommended"}
      · ${classTag(item.evidence_classification)}
      <div class="muted">${esc(item.why || "")}</div>
      <div class="muted">Missing: ${esc(item.missing || "")}</div>
    </li>`).join("");
  const checks = ((row.detail || {}).qa || {}).checks || [];
  const warnings = checks.filter((check) => check.result === "reject" || check.result === "flag");
  const agents = (row.agent_contributions || []).map((item) => `<li>${esc(item.agent)} · ${esc(item.body)}</li>`).join("");
  const reviews = (row.reviews || []).map((item) => `<li>${esc(item.action)} · ${esc(item.note)} · ${esc(item.actor)} · ${esc(item.at || "")}</li>`).join("");
  return `
    <article class="${current ? "current" : ""}">
    <p class="muted">${current ? "Current evaluation" : "Historical evaluation"} · version ${esc(row.version)} · ${esc(row.method)} · ${esc(row.created_at || "undated")}</p>
    <p class="muted">QA ${esc(row.qa_verdict)} · qualification ${nice(row.qualification)} · configuration ${esc(row.config_version || "not recorded")}</p>
    <p class="muted">Previous evaluation: ${esc(row.previous_evaluation_id || "none, this is the first stored version")}</p>
    <div class="scores">
      <article><span>Business signal</span><strong>${esc(row.business_signal_score ?? "n/a")}</strong></article>
      <article><span>Technical evidence</span><strong>${esc(row.technical_evidence_score ?? "n/a")}</strong></article>
      <article><span>Freelance fit</span><strong>${esc(row.freelance_fit_score ?? "n/a")}</strong></article>
      <article><span>Confidence</span><strong>${esc(row.confidence)}</strong></article>
    </div>
    <p class="muted">Historical composite score kept on this version: ${esc(row.legacy_score ?? "n/a")}. Confidence is separate from the scores. None of these numbers is a probability of hiring.</p>
    <h3>Findings</h3>
    <ul class="findings">${findings || "<li>None</li>"}</ul>
    <h3>Services</h3>
    <ul>${services || "<li>None</li>"}</ul>
    <h3>Quality assurance</h3>
    ${warnings.length ? `<ul>${warnings.map((check) => `<li class="qa-${esc(check.result)}">${esc(check.result)} · ${esc(check.name)} · ${esc(check.detail)}</li>`).join("")}</ul>` : "<p>No QA warnings on this version.</p>"}
    <p class="muted">${esc(row.limitations || "")}</p>
    <h3>Review recorded against this version</h3>
    <ul>${reviews || "<li>No human review is tied to this version.</li>"}</ul>
    <h3>Agent contributions captured with this version</h3>
    <ul>${agents || "<li>No agent message for this lead was stored with the version.</li>"}</ul>
    </article>`;
}

function evidenceCard(item) {
  const signals = item.signals || [];
  if (!signals.length) return `<section class="card evidence">${state("empty", "No source is stored for this lead.")}</section>`;
  const cards = signals.map((sig) => {
    const url = safeUrl(sig.source_url);
    const disc = safeUrl(sig.discussion_url);
    const title = plain(sig.title);
    const excerpt = plain(sig.evidence);
    const useful = excerpt && excerpt.toLowerCase() !== title.toLowerCase() && !/^comments$/i.test(excerpt);
    return `<article class="ev">
      <div class="ev-meta"><span class="pill">${esc(sig.source_name)}</span><span class="pill">${nice(sig.signal_type)}</span><span class="muted">${sig.published_at ? `Published ${when(sig.published_at)}` : "No publish date in the feed"} · collected ${when(sig.retrieved_at)}</span></div>
      <h3 class="ev-title">${esc(title || "Untitled item")}</h3>
      <div class="ev-links">
        ${url ? `<a class="btn primary btn-sm" href="${url}" target="_blank" rel="noopener noreferrer">Read the original · ${esc(host(sig.source_url))} ↗</a>` : ""}
        ${disc ? `<a class="btn btn-sm" href="${disc}" target="_blank" rel="noopener noreferrer">Discussion on Hacker News ↗</a>` : ""}
      </div>
      ${useful ? `<blockquote>${esc(excerpt.length > 700 ? excerpt.slice(0, 700) + "…" : excerpt)}</blockquote>` : `<p class="muted fs-13">The feed gave only the headline${disc ? " and a link to the comments" : ""}. Open the original to read the full item.</p>`}
      <p class="muted fs-13">Stored as <b>${nice(sig.claim_kind || "observed")}</b>. ${esc(VERIFY[sig.verification_status] || nice(sig.verification_status || ""))}</p>
    </article>`;
  }).join("");
  return `<section class="card evidence spot"><h2>Where this lead came from</h2><p class="muted">${signals.length === 1 ? "The one item" : `The ${signals.length} items`} GOIP found. Every claim below is based on ${signals.length === 1 ? "it" : "these"}. Open the original to check it yourself.</p><div class="ev-list">${cards}</div></section>`;
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
    <button class="btn ghost btn-sm back-link" id="back" type="button">← Opportunities</button>
    ${evidenceCard(item)}
    <article class="card">
      <h2>${esc(item.company)} <span class="tag mono">${esc(item.id)}</span></h2>
      <p>Current status: <span class="pill pill-${esc(item.status)}">${nice(item.status)}</span> Historical composite score: ${esc(item.score ?? "n/a")}. Current evaluation: <span class="mono">${esc(item.current_evaluation_id || "none")}</span></p>
      <p>Commercial intent: ${esc((item.commercial_intent || {}).classification || "unknown")}. ${esc((item.commercial_intent || {}).reason || "")}</p>
      <p>${item.service_supported ? `Validated service: ${esc(item.service)}` : `Historical recommendation, not validated: ${esc(item.service || "none")}`}</p>
      <p>${safeUrl(item.website) ? `<a href="${safeUrl(item.website)}" rel="noopener noreferrer" target="_blank">${safeUrl(item.website)}</a>` : "Website not established from the source."}</p>
      <p class="muted">The status can change when a person reviews the lead. Stored evaluation versions stay as written.</p>
      <h3>Current scores</h3>
      ${current ? evaluationBlock(current, item.current_evaluation_id) : state("empty", "No three-score evaluation is stored yet.")}
      <h3>Evaluation history</h3>
      <div class="history">${history || state("empty", "No evaluation history is stored.")}</div>
      <h3>Sources</h3>
      ${(item.signals || []).length ? (item.signals || []).map((signal) => `<p><strong>${esc(signal.signal_type)}</strong> · <a href="${safeUrl(signal.source_url)}" rel="noopener noreferrer" target="_blank">${esc(signal.source_name)}</a><br>${esc(plain(signal.evidence))}<br><span class="tag">${esc(signal.claim_kind || "unknown")}</span></p>`).join("") : state("empty", "No source is stored for this lead.")}
      <h3>Research tasks</h3>
      <ul>${tasks || "<li>No additional research has been requested.</li>"}</ul>
      <h3>Audit trail</h3>
      <ul>${events || "<li>No status change is recorded.</li>"}</ul>
      <form class="review" id="review">
        <h3>Human review</h3>
        <p class="muted">Approval records further consideration. It does not send outreach. Rejecting keeps the evaluation history.</p>
        <textarea id="note" placeholder="Reviewer note" aria-label="Reviewer note"></textarea>
        <p>
          <button type="button" class="btn good-btn" data-act="approve">Approve for further consideration</button>
          <button type="button" class="btn danger" data-act="reject">Reject</button>
          <button type="button" class="btn" data-act="request_research">Request additional research</button>
          <button type="button" class="btn" data-act="outreach">Draft outreach</button>
        </p>
        <p id="review-error" class="bad" role="alert"></p>
      </form>
      <pre>${(item.drafts || []).map((draft) => esc(draft.body)).join("\n\n")}</pre>
    </article>`;
  document.querySelector("#back").addEventListener("click", () => { activate("explorer"); });
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
  finish(view);
}

/* ------------------------------------------------------- activity, etc. */

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
  view.innerHTML = `<section class="card spot"><h2>Agents in this room</h2><p class="muted">Seven agents are registered. A row below is a stored message. It is not a claim that every agent finished a task on the latest run.</p><ul class="agents mt-12"><li>goip-discovery</li><li>goip-company-research</li><li>goip-technical-intelligence</li><li>goip-qualification</li><li>goip-strategy</li><li>goip-quality-assurance</li><li>goip-orchestrator</li></ul></section><div class="table-scroll"><table><tr><th>When</th><th>Agent</th><th>Direction</th><th>Delivery</th><th>Message</th></tr>${
    data.messages.map((row) => `<tr><td class="mono">${esc(row.at)}</td><td>${esc(row.agent)}</td><td>${esc(row.direction)}</td><td class="${statusClass(row.delivered)}">${esc(row.delivered)}</td><td class="msg">${esc(mdText(row.body))}</td></tr>`).join("")
  }</table></div>`;
  finish(view);
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
  // Rows arrive newest first. Show the latest reading per source, plus how reliable it has been.
  const latest = new Map();
  const history = new Map();
  data.sources.forEach((row) => {
    if (!latest.has(row.name)) latest.set(row.name, row);
    const h = history.get(row.name) || { total: 0, bad: 0 };
    h.total += 1;
    if (row.status !== "ok") h.bad += 1;
    history.set(row.name, h);
  });
  const stamp = (value) => (value ? new Date(value).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
  const rows = [...latest.values()].map((row) => {
    const h = history.get(row.name);
    return `<tr><td><strong>${esc(row.name)}</strong></td><td>${esc(row.parent_domain)}</td><td>${esc(row.access_method)}</td><td class="${statusClass(row.status)}">${esc(row.status)}</td><td class="mono">${esc(row.records)}</td><td class="mono">${esc(h.total - h.bad)}/${esc(h.total)} ok</td><td class="muted">${esc(stamp(row.fetched_at))}</td><td>${esc(row.error || "")}</td></tr>`;
  }).join("");
  view.innerHTML = `
    <section class="card spot"><h2>${latest.size} sources, latest reading each</h2><p class="muted">Each row is the most recent fetch. The reliability column counts how many of the last ${esc(data.sources.length)} stored fetches succeeded.</p></section>
    <div class="table-scroll"><table><tr><th>Source</th><th>Domain</th><th>Method</th><th>Status</th><th>Records</th><th>Reliability</th><th>Last fetch</th><th>Error</th></tr>${rows}</table></div>
    <details class="card"><summary>All ${esc(data.sources.length)} stored fetches</summary><div class="table-scroll mt-12"><table><tr><th>When</th><th>Source</th><th>Status</th><th>Records</th><th>Error</th></tr>${
      data.sources.map((row) => `<tr><td class="mono">${esc(stamp(row.fetched_at))}</td><td>${esc(row.name)}</td><td class="${statusClass(row.status)}">${esc(row.status)}</td><td class="mono">${esc(row.records)}</td><td>${esc(row.error || "")}</td></tr>`).join("")
    }</table></div></details>`;
  finish(view);
}

async function showSettings() {
  const data = await api("/api/settings");
  const integrations = data.integrations || {};
  const rows = Object.entries(integrations).map(([name, status]) => `<div><span>${esc(name)}</span><strong class="${statusClass(status)}">${esc(status)}</strong></div>`).join("");
  view.innerHTML = `<section class="card spot"><h2>Integrations</h2><div class="integrations">${rows}</div><p class="muted">Secrets are not returned by this API. A configured integration is not the same as a delivered report.</p></section><details class="card"><summary>Runtime configuration</summary><pre>${esc(JSON.stringify(data.runtime, null, 2))}</pre></details>`;
  finish(view);
}

/* ----------------------------------------------------------- agents */

const AGENT_ORDER = ["goip-orchestrator", "goip-discovery", "goip-company-research", "goip-technical-intelligence", "goip-qualification", "goip-strategy", "goip-quality-assurance"];
const AGENT_LABEL = { "goip-orchestrator": "Orchestrator", "goip-discovery": "Discovery", "goip-company-research": "Research", "goip-technical-intelligence": "Technical", "goip-qualification": "Freelance judge", "goip-strategy": "Strategy", "goip-quality-assurance": "Quality" };
const AGENT_ROLE = {
  "goip-orchestrator": "Plans the run from your request, reviews what discovery found, and writes the assessment.",
  "goip-discovery": "Chooses which sources to read, and when it has enough.",
  "goip-company-research": "Reads each company's stored evidence and quotes it. May open a stored page.",
  "goip-technical-intelligence": "Searches GitHub for a repository that belongs to the company.",
  "goip-qualification": "Judges whether a posting is a company offering paid contract engineering work.",
  "goip-strategy": "Names a service the posting's own words support.",
  "goip-quality-assurance": "Tries to disprove each strong lead, and can re-open the original page.",
};

function modeBadge(mode) {
  return mode === "llm" ? `<span class="pill badge-model">model decided</span>` : `<span class="pill badge-fixed">fixed policy</span>`;
}

function stepRow(step) {
  const args = step.args && Object.keys(step.args).length ? Object.entries(step.args).map(([k, v]) => `${esc(k)}=${esc(String(v).slice(0, 60))}`).join(", ") : "";
  return `<li class="astep">
    <div class="astep-head">${modeBadge(step.mode)}${step.tool ? `<span class="tool mono">${esc(step.tool)}(${args})</span>` : (step.mode === "llm" ? `<span class="tool mono">answer</span>` : "")}</div>
    <p class="thought">${esc(step.thought)}</p>
    ${step.observation ? `<details><summary>What it saw</summary><pre>${esc(step.observation)}</pre></details>` : ""}
  </li>`;
}

async function showAgents() {
  view.innerHTML = state("loading", "Loading the agents' reasoning.");
  let data;
  try {
    data = await api("/api/runs/latest/trace");
  } catch (error) {
    view.innerHTML = state("empty", "No run has been traced yet. Start a run and the agents' decisions will appear here.");
    return;
  }
  const byAgent = {};
  data.trace.forEach((s) => { (byAgent[s.agent] = byAgent[s.agent] || []).push(s); });
  const plan = (byAgent["goip-orchestrator"] || []).find((s) => s.stage === "plan");
  const modes = Object.entries(data.modes || {});
  const summary = modes.length
    ? modes.map(([stage, mode]) => `<span class="pill ${mode === "llm" ? "badge-model" : "badge-fixed"}">${esc(stage)}: ${mode === "llm" ? "model" : "fixed"}</span>`).join(" ")
    : "";
  const sections = AGENT_ORDER.filter((a) => byAgent[a]).map((agent) => `
    <section class="card agent-card spot">
      <div class="agent-top"><h2>${esc(AGENT_LABEL[agent])}</h2><span class="muted fs-13">${esc(AGENT_ROLE[agent])}</span></div>
      <ol class="asteps">${byAgent[agent].map(stepRow).join("")}</ol>
    </section>`).join("");
  view.innerHTML = `
    <section class="card spot">
      <h2>How the agents decided</h2>
      <p class="muted">Run <span class="mono">${esc(data.run_id.slice(0, 8))}</span> · ${esc(data.status)}${data.sources.length ? ` · sources used: ${esc(data.sources.join(", "))}` : ""}${data.judged ? ` · ${esc(data.judged)} postings judged` : ""}</p>
      <p class="mt-14">${summary}</p>
      ${plan ? `<blockquote>${esc(plan.thought)}</blockquote>` : ""}
      <p class="muted fs-13 mt-14"><b>Model decided</b> means a language model chose the steps and every answer was checked against the stored text. <b>Fixed policy</b> means the model was unavailable, so the agent ran its fixed rules.</p>
    </section>
    ${sections || state("empty", "This run has no recorded decisions.")}`;
  finish(view);
}

/* ------------------------------------------------------- reconciliation */

const CLASS_ORDER = ["probable_match", "ambiguous_match", "unmatched", "duplicate_signal", "confirmed_match"];
const CLASS_LABEL = { confirmed_match: "Confirmed", probable_match: "Probable", ambiguous_match: "Ambiguous", unmatched: "Unmatched", duplicate_signal: "Duplicate" };
const CLASS_HELP = {
  confirmed_match: "The source is on the company's own website.",
  probable_match: "Exactly one stored company is named, but nothing proves it.",
  ambiguous_match: "A company is mentioned, or several fit. A mention is not an identity.",
  unmatched: "No company could be identified.",
  duplicate_signal: "This exact source is already stored against a company.",
};
const CHECK_ICON = { pass: "✓", fail: "✕", warn: "!", info: "i" };
let reconFilter = "all";

function confBars(level) {
  const n = { low: 1, medium: 2, high: 3 }[level] || 1;
  return `<span class="conf" title="Confidence: ${esc(level)}"><i>${[1, 2, 3].map((i) => `<b class="${i <= n ? "on" : ""}"></b>`).join("")}</i>${esc(level)} confidence</span>`;
}

function checkList(checks) {
  return `<ul class="checks">${(checks || []).map((check) => `<li class="${esc(check.status)}"><span class="ic" aria-hidden="true">${CHECK_ICON[check.status] || "i"}</span><div><div class="lbl">${esc(check.label)}</div><div class="det">${esc(check.detail)}</div></div></li>`).join("")}</ul>`;
}

function candidateBlock(r) {
  const c = r.reasoning.candidate;
  if (!c) return `<div class="cand-none"><strong>No candidate company.</strong><br>Nothing stored matches this signal, so there is no company to link it to.</div>`;
  const basis = { domain: "matched by website domain", name: "matched by company name", person: "chosen by a person" }[c.basis] || "mentioned only";
  const alts = (r.reasoning.alternatives || []).filter((a) => a.id !== c.id);
  return `<div class="cand-card"><strong>${esc(c.name)}</strong>
    <div class="row"><span class="tag">${esc(basis)}</span>${c.domain ? `<span class="mono">${esc(c.domain)}</span>` : "<span>no website stored</span>"}</div>
    <div class="row"><span>${esc(c.stored_signals ?? 0)} stored signal${c.stored_signals === 1 ? "" : "s"}</span>${c.lead_id ? `<span>· lead <a href="#" class="lead-link mono" data-lead="${esc(c.lead_id)}">${esc(c.lead_id)}</a> <span class="pill pill-${esc(c.lead_status)}">${nice(c.lead_status)}</span></span>` : "<span>· no lead yet</span>"}</div></div>
    ${alts.length ? `<div><p class="muted fs-13 mb-6">Other companies that also fit</p><ul class="alts">${alts.map((a) => `<li>${esc(a.name)}${a.domain ? ` <span class="mono muted">${esc(a.domain)}</span>` : ""}</li>`).join("")}</ul></div>` : ""}`;
}

function reconCard(r) {
  const decided = r.human_action;
  const cands = [];
  const c = r.reasoning.candidate;
  if (c) cands.push({ id: c.id, name: c.name });
  (r.reasoning.alternatives || []).forEach((a) => { if (!cands.some((x) => x.id === a.id)) cands.push({ id: a.id, name: a.name }); });
  const needsPerson = !decided && (r.classification === "probable_match" || r.classification === "ambiguous_match");
  return `<article class="card rec spot" data-class="${esc(r.classification)}" data-signal="${esc(r.signal_id)}">
    <div class="rec-head">
      <div class="rec-meta">
        <span class="pill class-${esc(r.classification)}">${esc(CLASS_LABEL[r.classification] || r.classification)}</span>
        ${confBars(r.confidence)}
        ${needsPerson ? `<span class="pill accent-pill">needs a person</span>` : ""}
        <span class="src">${esc(r.source_name)} · ${nice(r.signal_type)} · ${when(r.published_at)}</span>
      </div>
      <h3 class="rec-title">${safeUrl(r.source_url) ? `<a href="${safeUrl(r.source_url)}" rel="noopener noreferrer" target="_blank">${esc(plain(r.title))}</a>` : esc(plain(r.title))}</h3>
    </div>
    ${r.excerpt && plain(r.excerpt) !== plain(r.title) ? `<blockquote class="rec-quote">${esc(plain(r.excerpt))}</blockquote>` : ""}
    <div class="rec-body">
      <div class="rec-why">
        <h4>Why this class</h4>
        <p class="verdict">${esc(r.reasoning.headline)}</p>
        ${checkList(r.reasoning.checks)}
        <div class="callout"><b>What this class means</b><span>${esc(r.reasoning.class_meaning)}</span></div>
      </div>
      <div class="rec-cand">
        <h4>Candidate company</h4>
        ${candidateBlock(r)}
        ${r.reasoning.why_not_higher ? `<div class="callout"><b>Why not a higher class</b><span>${esc(r.reasoning.why_not_higher)}</span></div>` : ""}
        ${r.reasoning.to_confirm ? `<div class="callout next"><b>What would confirm it</b><span>${esc(r.reasoning.to_confirm)}</span></div>` : ""}
      </div>
    </div>
    ${decided ? `<div class="decided"><strong>A person decided: ${nice(decided)}</strong><span>${esc(r.rationale)}</span><span class="muted">by ${esc(r.decided_by || "operator")}</span></div>` : ""}
    <div class="rec-actions">
      <textarea data-note aria-label="Note for this decision" placeholder="Why? (optional, kept in the audit trail)"></textarea>
      <div class="row">
        ${cands.length ? `<select data-company aria-label="Company to confirm">${cands.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select><button class="btn primary btn-sm" data-act="confirm" type="button">Confirm match</button>` : ""}
        <button class="btn danger btn-sm" data-act="reject" type="button">Not this company</button>
        <button class="btn btn-sm" data-act="duplicate" type="button">Duplicate</button>
        <button class="btn btn-sm" data-act="unassigned" type="button">Keep unassigned</button>
        <button class="btn btn-sm" data-act="request_research" type="button">Request research</button>
      </div>
      <p class="bad" data-error role="alert"></p>
    </div>
  </article>`;
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
  const rank = (r) => (r.human_action ? 9 : CLASS_ORDER.indexOf(r.classification));
  const rows = [...data.signals].sort((a, b) => rank(a) - rank(b));
  const chip = (key, label, n) => `<button type="button" data-filter="${esc(key)}" aria-pressed="${reconFilter === key}">${esc(label)} <span class="n">${esc(n)}</span></button>`;
  view.innerHTML = `
    <section class="card rec-top spot">
      <div class="rec-lead">
        <div>
          <h2>Which company is this signal about?</h2>
          <p>${esc(data.total)} signals could not be linked to a stored company. For each one, the matcher shows the checks it ran, the company it would pick and why, and what a person has to verify. Nothing is linked unless the source is on the company's own website, or a person confirms it.</p>
        </div>
        <div class="rec-legend">${CLASS_ORDER.map((k) => `<div><span class="pill class-${k}">${CLASS_LABEL[k]}</span><span>${esc(CLASS_HELP[k])}</span></div>`).join("")}</div>
      </div>
      ${data.unclassified ? `<div class="callout next inspect"><b>Not classified yet</b><span>${esc(data.unclassified)} unlinked signal${data.unclassified === 1 ? " has" : "s have"} not been checked by the matcher.</span><button class="btn primary btn-sm" id="inspect" type="button">Classify them now</button></div>` : ""}
      <div class="chips" role="group" aria-label="Filter by class">
        ${chip("all", "All", data.total)}${chip("needs", "Needs a person", data.needs_person)}
        ${CLASS_ORDER.map((k) => chip(k, CLASS_LABEL[k], data.counts[k] || 0)).join("")}
      </div>
    </section>
    <div class="rec-list" id="rec-list">${rows.map(reconCard).join("")}</div>`;
  const apply = () => {
    document.querySelectorAll("#view [data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === reconFilter)));
    document.querySelectorAll("#rec-list .rec").forEach((card) => {
      const row = rows.find((r) => r.signal_id === card.dataset.signal);
      const show = reconFilter === "all" || (reconFilter === "needs" ? !row.human_action && ["probable_match", "ambiguous_match"].includes(row.classification) : row.classification === reconFilter);
      card.classList.toggle("hidden", !show);
    });
  };
  const inspect = document.querySelector("#inspect");
  if (inspect) inspect.addEventListener("click", async () => {
    inspect.disabled = true;
    inspect.textContent = "Classifying…";
    try { await api("/api/reconciliation/inspect", { method: "POST", body: "{}" }); showReconciliation(); }
    catch (error) { inspect.textContent = error.message; inspect.disabled = false; }
  });
  view.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { reconFilter = button.dataset.filter; apply(); }));
  view.querySelectorAll(".lead-link").forEach((link) => link.addEventListener("click", (event) => { event.preventDefault(); showLead(link.dataset.lead); }));
  view.querySelectorAll(".rec button[data-act]").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".rec");
      const select = card.querySelector("[data-company]");
      const note = card.querySelector("[data-note]").value.trim() || "dashboard";
      const body = { action: button.dataset.act, company_id: button.dataset.act === "confirm" && select ? select.value : "", note };
      button.disabled = true;
      try {
        await api("/api/reconciliation/" + card.dataset.signal, { method: "POST", body: JSON.stringify(body) });
        showReconciliation();
      } catch (error) {
        card.querySelector("[data-error]").textContent = error.message;
        button.disabled = false;
      }
    });
  });
  apply();
  finish(view);
}

/* ---------------------------------------------------------------- wiring */

const screens = { overview: showOverview, agents: showAgents, explorer: showExplorer, reconciliation: showReconciliation, activity: showActivity, sources: showSources, settings: showSettings };

function activate(name) {
  document.querySelectorAll("nav button[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
  document.querySelector("#page-title").textContent = TITLES[name] || "";
  FX.toTop();
  return screens[name]().catch((error) => { if (error.message !== "auth") view.textContent = error.message; });
}

document.querySelectorAll("nav button[data-view]").forEach((button) => {
  button.addEventListener("click", () => activate(button.dataset.view));
});

document.querySelector("#run").addEventListener("click", async () => {
  const button = document.querySelector("#run");
  button.disabled = true;
  document.querySelector("#page-title").textContent = "Research running";
  view.innerHTML = `<section class="card spot"><h2>Seven agents are working</h2><p class="muted">Discovery, research, repository search, qualification, strategy and QA run in order. Each stage is checked by a guardrail before the next one starts. This can take a minute or two.</p><div class="funnel mt-16">${["Discovery", "Research", "Technical", "Qualification", "Strategy", "Quality"].map((s, i) => `<div class="funnel-row"><span class="label">${s}</span><div class="track"><b data-w="${Math.min(100, 18 + i * 16)}"></b></div><span class="num">${i === 0 ? "running" : "queued"}</span></div>`).join("")}</div></section>`;
  finish(view);
  try {
    const goal = (document.querySelector("#goal").value || "").trim();
    const result = await api("/api/runs", { method: "POST", body: JSON.stringify({ goal }) });
    activate("overview");
    view.insertAdjacentHTML("afterbegin", `<p class="note">Run ${esc(result.run_id.slice(0, 8))} finished in mode ${esc(result.mode)}.</p>`);
  } catch (error) {
    view.innerHTML = `<p class="error">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#logout").addEventListener("click", async () => {
  try { await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); } catch (error) {}
  showLogin();
});

login.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#login-error");
  error.textContent = "";
  const response = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: document.querySelector("#token").value }) });
  if (response.status === 429) {
    error.textContent = "Too many attempts. Wait a few minutes and try again.";
    return;
  }
  if (!response.ok) {
    error.textContent = "Token rejected.";
    return;
  }
  document.querySelector("#token").value = "";
  showApp();
  activate("overview");
});

fetch("/api/session").then((response) => response.json()).then((data) => {
  if (data.authenticated) {
    showApp();
    activate("overview");
  } else {
    showLogin();
  }
}).catch(() => showLogin());
