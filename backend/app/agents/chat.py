"""Human-facing replies for every agent.

Replies are deterministic and read only from the stored records: no model call, no network call, no
write. Every message passes the same guardrail pipeline before and after the handler runs:

    input size -> outreach refusal -> rate limit -> tool allowlist (read_store) -> handler -> output scrub
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import load_runtime
from app.db import Company, EvaluationVersion, Opportunity, PipelineRun, Signal, SourceHealth
from app.guardrails import check_input_text, check_outreach_request, check_tool_call, redact_pii, redact_secrets
from app.agents.format import NO_OUTREACH, card, cell, code, label, link, table
from app.discovery.focus import SECTOR_ALIASES, feed_sector_for, parse_focus_term  # noqa: F401  (SECTOR_ALIASES re-exported)
from app.observability import record_verdict

MAX_HUMAN_CHARS = 2000
MAX_REPLY_CHARS = 3500
RATE_LIMIT = 8  # messages per sender per window
RATE_WINDOW = 60.0

_PUBLIC_ID = re.compile(r"\bG[0-9A-F]{8}\b")
_SECRETS = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|lsv2_[A-Za-z0-9_]{10,}|\b\d{8,10}:AA[\w-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+\S+)"
)

REFUSAL = card(
    "Can't do that",
    lead="GOIP has no way to contact a company, and nobody in this room does either.",
    bullets=[
        "I only read stored research.",
        "A draft can be prepared only after a lead is approved.",
        "Sending stays a separate human action outside GOIP.",
    ],
)


def _help(title: str, rows: list[tuple[str, str]]) -> str:
    return card(
        f"{title} · what to ask",
        grid=table(["Try", "What you get"], [[f"`{a}`", b] for a, b in rows]),
        note="Replies come from stored records only. Nothing here contacts a company.",
    )


ROLE_HELP = {
    "goip-orchestrator": _help("Orchestrator", [
        ("run", "Start a run for new leads (one at a time)"),
        ("status", "Counts by status and the last run"),
        ("report", "The current best leads"),
        ("focus on fintech", "Narrow runs to one sector (`clear focus` resets)"),
        ("approve G1A2B3C4D", "Approve a lead. Also `reject` and `request research`"),
        ("draft outreach G1A2B3C4D", "A draft for an approved lead. It is never sent"),
    ]),
    "goip-discovery": _help("Discovery", [
        ("sources", "What the last run read, and how each source did"),
        ("G1A2B3C4D", "The signals stored for a lead"),
    ]),
    "goip-company-research": _help("Research", [
        ("G1A2B3C4D", "What is known about a lead, quoted from its source"),
        ("fintech", "Stored leads in a sector (from existing records)"),
    ]),
    "goip-technical-intelligence": _help("Technical", [("G1A2B3C4D", "The public repository that matches a lead, if any")]),
    "goip-qualification": _help("Qualification", [("G1A2B3C4D", "How a lead scored and why")]),
    "goip-strategy": _help("Strategy", [("G1A2B3C4D", "The service a lead's source supports, if any")]),
    "goip-quality-assurance": _help("Quality", [
        ("G1A2B3C4D", "QA notes for a lead"),
        ("qa", "The QA summary of the last run"),
    ]),
}


class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def scrub_reply(text: str) -> str:
    return redact_pii(redact_secrets(_SECRETS.sub("[redacted]", text or "")))[:MAX_REPLY_CHARS]


# ------------------------------------------------------------------ read helpers


def _lead(session: Session, body: str) -> Opportunity | None:
    match = _PUBLIC_ID.search(body.upper())
    if match:
        return session.scalar(select(Opportunity).where(Opportunity.public_id == match.group(0)))
    rows = session.scalars(select(Opportunity)).all()
    return max(rows, key=lambda o: (o.score or 0), default=None)


def _latest_eval(session: Session, opportunity: Opportunity) -> EvaluationVersion | None:
    return session.scalars(
        select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id).order_by(EvaluationVersion.version.desc())
    ).first()


def _signals(session: Session, opportunity: Opportunity) -> list[Signal]:
    return list(session.scalars(select(Signal).where(Signal.company_id == opportunity.company_id)).all())


def _name(session: Session, opportunity: Opportunity) -> str:
    company = session.get(Company, opportunity.company_id)
    return company.name if company else opportunity.public_id


def known_sectors() -> list[str]:
    extra = ["fintech", "healthtech", "edtech", "saas", "cybersecurity", "logistics", "climate", "e-commerce", "ai"]
    return sorted({s.lower() for s in load_runtime().get("industries", [])} | set(extra))


def _sector_in(body: str) -> str | None:
    text = body.lower()
    for sector in sorted(known_sectors(), key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(sector.replace(' and ', ' '))}(?![a-z])", text) or sector in text:
            return sector
    return None


def sector_matches(session: Session, sector: str, limit: int = 5) -> list[tuple[Opportunity, Company]]:
    needle = sector.lower().replace("fintech", "fin")  # matches 'FinTech', 'financial', 'fintech'
    out: list[tuple[Opportunity, Company]] = []
    seen: set[str] = set()
    for opportunity in session.scalars(select(Opportunity)).all():
        company = session.get(Company, opportunity.company_id)
        if company is None or company.id in seen:
            continue
        hay = f"{company.industry or ''} {company.description or ''} {company.name}".lower()
        if needle in hay:
            seen.add(company.id)
            out.append((opportunity, company))
    out.sort(key=lambda pair: pair[0].score or 0, reverse=True)
    return out[:limit]


# --------------------------------------------------------------------- handlers


def _no_lead() -> str:
    return card("Nothing stored yet", lead="I have no stored lead to look at.", next_step="Ask the orchestrator to `run`.")


def _reading(session: Session, o: Opportunity) -> str:
    ev = _latest_eval(session, o)
    if ev is None:
        return f"score {o.score}" if o.score is not None else "not scored"
    return f"{label(ev.qualification)} · fit {ev.freelance_fit_score}/100"


def _src(session: Session, o: Opportunity) -> str:
    sig = next(iter(_signals(session, o)), None)
    if sig is None or not sig.source_url:
        return ""
    host = re.sub(r"^https?://(www\.)?", "", sig.source_url).split("/")[0]
    return link(host, sig.source_url)


def _discovery(session: Session, body: str, lead: Opportunity | None) -> str:
    if _PUBLIC_ID.search(body.upper()) and lead:
        signals = _signals(session, lead)
        rows = [[label(s.signal_type), cell(s.title or s.summary, 70), link(s.source_name, s.source_url)] for s in signals[:5]]
        return card(f"Signals · {_name(session, lead)} {code(lead.public_id)}", lead=f"{len(signals)} stored signal(s).",
                    grid=table(["Type", "Headline", "Source"], rows) if rows else None)
    run = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at.desc())).first()
    if run is None:
        return card("Discovery", lead="No run has happened yet, so no source has been read.", next_step="Ask the orchestrator to `run`.")
    health = session.scalars(select(SourceHealth).where(SourceHealth.run_id == run.id)).all()
    c = run.counts or {}
    rows = [[cell(r.name, 40), r.status, r.records] for r in health]
    return card(
        f"Discovery · last run {code(run.id[:8])}",
        fields=[("Status", run.status), ("Items read", c.get("raw_items", 0)), ("New companies", c.get("discovered", 0)), ("Already stored", c.get("duplicate_signals", 0))],
        grid=table(["Source", "Status", "Records"], rows) if rows else None,
        note="Sources are fixed: Hacker News, its hiring thread, TechCrunch and sector feeds. I cannot add one on request.",
    )


def _research(session: Session, body: str, lead: Opportunity | None) -> str:
    sector = _sector_in(body)
    if sector and not _PUBLIC_ID.search(body.upper()):
        matches = sector_matches(session, sector)
        if not matches:
            return card(f"Stored leads · {sector}", lead=f"No stored company is described as {sector}.",
                        note="I only search what discovery already stored.", next_step=f"Tell the orchestrator `focus on {sector}`, then `run`.")
        rows = [[code(o.public_id), cell(c.name, 36), cell(c.industry or "not stated", 24), label(o.status), _reading(session, o)] for o, c in matches]
        return card(f"Stored leads · {sector}", lead="Read from existing records, not a new search.",
                    grid=table(["Lead", "Company", "Industry", "Status", "Reading"], rows))
    if lead is None:
        return _no_lead()
    signals = _signals(session, lead)
    first = signals[0] if signals else None
    quote = re.sub(r"<[^>]+>", " ", first.evidence or "")[:300].strip() if first else ""
    return card(
        f"Research · {_name(session, lead)} {code(lead.public_id)}",
        fields=[("Source", link(first.source_name, first.source_url) if first else "none stored"),
                ("Inference, not a vacancy", lead.technical_need or "none stored"), ("Confidence", lead.confidence)],
        quote=quote or None,
        note="An inference is a guess from the source. It is not an open vacancy.",
    )


def _technical(session: Session, body: str, lead: Opportunity | None) -> str:
    if lead is None:
        return _no_lead()
    if lead.oss_url:
        return card(f"Repository · {_name(session, lead)} {code(lead.public_id)}",
                    fields=[("Repository", link(lead.oss_name or lead.oss_url, lead.oss_url)), ("Licence", lead.oss_license or "unknown")], note=lead.oss_relevance or None)
    return card(f"Repository · {_name(session, lead)} {code(lead.public_id)}",
                lead=lead.oss_relevance or "No repository search has been recorded for this lead.")


def _qualification(session: Session, body: str, lead: Opportunity | None) -> str:
    if lead is None:
        return _no_lead()
    ev = _latest_eval(session, lead)
    if ev is None:
        return card(f"Scores · {_name(session, lead)} {code(lead.public_id)}", lead="No evaluation is stored yet.", fields=[("Historical score", lead.score)])
    explanation = " ".join(str(x) for x in ((ev.detail or {}).get("explanation") or []))[:400]
    return card(
        f"Scores · {_name(session, lead)} {code(lead.public_id)}",
        grid=table(["Dimension", "Score"], [["Business signal", f"{ev.business_signal_score}/100"], ["Technical evidence", f"{ev.technical_evidence_score}/100"], ["Freelance fit", f"{ev.freelance_fit_score}/100"]]),
        fields=[("Qualification", label(ev.qualification)), ("QA", ev.qa_verdict), ("Confidence", ev.confidence), ("Why", explanation)],
        note="Ranking scores, not a probability of being hired.",
    )


def _strategy(session: Session, body: str, lead: Opportunity | None) -> str:
    if lead is None:
        return _no_lead()
    ev = _latest_eval(session, lead)
    proposed = ((ev.services or [{}])[0].get("proposed_service") if ev and ev.services else None) or lead.recommended_service
    if not proposed:
        return card(f"Service · {_name(session, lead)} {code(lead.public_id)}", lead="No service is supported: the stored sources state no requirement.", fields=[("Status", label(lead.status))])
    return card(f"Service · {_name(session, lead)} {code(lead.public_id)}", fields=[("Possible service", proposed), ("Status", label(lead.status))],
                note="Tied to an observed requirement. Nothing was drafted or sent.")


def _qa(session: Session, body: str, lead: Opportunity | None) -> str:
    if _PUBLIC_ID.search(body.upper()) and lead:
        return card(f"QA · {_name(session, lead)} {code(lead.public_id)}", lead=lead.qa_notes or "No QA note is recorded.")
    run = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at.desc())).first()
    if run is None:
        return card("Quality", lead="No run has been checked yet.")
    c = run.counts or {}
    return card(f"Quality · last run {code(run.id[:8])}", fields=[("QA flags", c.get("qa_flags", 0)), ("High priority", c.get("high_priority", 0))],
                note="I check stored sources, not live pages.")


HANDLERS = {
    "goip-discovery": _discovery,
    "goip-company-research": _research,
    "goip-technical-intelligence": _technical,
    "goip-qualification": _qualification,
    "goip-strategy": _strategy,
    "goip-quality-assurance": _qa,
}


def guard_message(agent: str, body: str, sender: str, limiter: RateLimiter) -> str | None:
    """Return a refusal/notice text if the message must not reach a handler, else None."""
    size = record_verdict(check_input_text(body, limit=MAX_HUMAN_CHARS))
    if size.blocked:
        return card("Message too long", lead="That is too long for me to read safely.", next_step="Send a shorter request.")
    if record_verdict(check_outreach_request(body)).blocked:
        return REFUSAL
    if not limiter.allow(sender or "unknown"):
        return card("Slow down", lead="You are sending requests faster than I answer.", next_step="Wait a minute and try again.")
    return None


def reply(agent: str, body: str, sender: str, session: Session, limiter: RateLimiter) -> str:
    """Build the reply for one agent. Never raises; never writes to the store."""
    blocked = guard_message(agent, body, sender, limiter)
    if blocked:
        return scrub_reply(blocked)
    if record_verdict(check_tool_call(agent, "read_store")).blocked:
        return card("Not permitted", lead="I am not permitted to read the store.")
    handler = HANDLERS.get(agent)
    if handler is None:
        return scrub_reply(ROLE_HELP.get(agent, card("No requests", lead="I do not handle requests.")))
    lowered = body.lower()
    if re.fullmatch(r"\W*(help|\?|what can you do)\W*", lowered.strip()) or "what can you do" in lowered:
        return scrub_reply(ROLE_HELP[agent])
    try:
        text = handler(session, body, _lead(session, body))
    except Exception:  # noqa: BLE001 - a reply must never crash the socket loop
        return card("Could not read", lead="I could not read the stored record just now.")
    flagged = check_input_text(body)
    if not flagged.ok and not flagged.blocked:
        text += "\n\n> I ignored instruction-like text in your message."
    return scrub_reply(text)


# ------------------------------------------------------------ orchestrator extras

RUN_INTENT = re.compile(
    r"(\b(find|look for|search for|hunt for|discover|scan for|dig up)\b.{0,50}\b(jobs?|gigs?|contracts?|freelance|opportunit\w*|companies|leads?|work)\b|\bnew leads?\b|\bfresh leads?\b|\bfind (me )?(new |more )?leads?\b|\b(run|start|kick ?off|trigger)\b.{0,30}\b(pipeline|leads?|discovery|scan|search|run)\b|^\W*(please\s+|can (you|u)\s+)?(run|start)\b.{0,30}$)",
    re.I,
)
STATUS_INTENT = re.compile(r"\b(status|how many|summary|overview|where are we)\b", re.I)
RUN_COOLDOWN_SECONDS = 300


def wants_run(body: str) -> bool:
    return bool(RUN_INTENT.search(body or ""))


def wants_status(body: str) -> bool:
    return bool(STATUS_INTENT.search(body or ""))


def run_summary(session: Session, run_id: str) -> str:
    run = session.get(PipelineRun, run_id)
    if run is None:
        return card("Run not found", lead="I could not find that run.")
    c = run.counts or {}
    title = f"Run {code(run_id[:8])} · {run.status}"
    if run.status != "completed":
        return scrub_reply(card(title, lead=f"Stopped early: {run.error or 'no reason recorded'}.", note="Nothing was padded or sent."))
    rows_ = session.scalars(select(Opportunity).where(Opportunity.run_id == run_id)).all()
    fields = [("Items read", c.get("raw_items", 0)), ("Already stored", c.get("duplicate_signals", 0)), ("New leads", len(rows_)),
              ("Qualified", c.get("qualified", 0)), ("High priority", c.get("high_priority", 0))]
    if c.get("focus"):
        fields.insert(0, ("Focus", c["focus"]))
    if not rows_:
        return scrub_reply(card(title, lead="No new leads: everything read was already stored.", fields=fields, note=NO_OUTREACH,
                                next_step="`report` shows the best leads already stored."))
    rows_.sort(key=lambda o: (o.status != "high_priority", o.status != "qualified", -(o.score or 0)))
    grid = table(["Lead", "Company", "Status", "Reading", "Source"],
                 [[code(o.public_id), cell(_name(session, o), 34), label(o.status), _reading(session, o), _src(session, o)] for o in rows_[:6]])
    return scrub_reply(card(title, fields=fields, grid=grid,
                            note=f"A business signal alone is not a freelance requirement, so most stay in review. {NO_OUTREACH}",
                            next_step="`approve G…`, `reject G…` or `request research G…` with a lead id."))


def _llm_line() -> str:
    from app.integrations.openrouter import LLM_MESSAGES, llm_health

    state = llm_health()
    if state["ok"]:
        return "working"
    if state["ok"] is None and state["reason"] == "not_checked":
        return "not checked yet"
    return f"**not working**. {LLM_MESSAGES.get(state['reason'], 'unavailable')}"


def status_text(session: Session) -> str:
    from sqlalchemy import func

    rows = session.execute(select(Opportunity.status, func.count()).group_by(Opportunity.status)).all()
    run = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at.desc())).first()
    return scrub_reply(card(
        "GOIP status",
        fields=[("Last run", f"{code(run.id[:8])} · {run.status}" if run else "none yet"), ("Focus", current_focus() or "every topic"), ("Language model", _llm_line())],
        grid=table(["Status", "Leads"], [[label(s), n] for s, n in sorted(rows)]) if rows else None,
        next_step="`run` for new leads, or `report` for the best ones.",
    ))


# ------------------------------------------------------------------ sector focus

def parse_focus(body: str) -> tuple[str | None, bool]:
    """(term, clear). The term is the operator's own wording, never a category chosen for them."""
    return parse_focus_term(body)


def wants_focus(body: str) -> bool:
    """An unmistakable instruction to focus ("focus on X", "only X") or to clear the focus."""
    term, clear = parse_focus_term(body, explicit_only=True)
    return clear or term is not None


def current_focus() -> str | None:
    saved = load_runtime().get("focus") or {}
    return saved.get("term") or saved.get("sector")


def set_focus(term: str | None) -> str:
    """Persist the focus (validated, atomic). Returns the card to post."""
    from app.config import save_runtime

    sector = feed_sector_for(term) if term else None
    save_runtime({"focus": {"term": term, "sector": sector}})
    if term is None:
        return card("Focus cleared", lead="Runs use every topic again.")
    lead = f"The next run keeps only postings and stories about **{term}**."
    if sector:
        lead += f" The {sector} trade feeds are read as an extra source, and only items about {term} are kept."
    return card(f"Focus set · {term}", lead=lead, next_step="`run` to search now, or `clear focus` to go back.")


# ------------------------------------------------------------------ mentions and reports

_LEADING_MENTIONS = re.compile(r"^(?:\s*@[\w.-]+)+\s*")
REPORT_INTENT = re.compile(
    r"(\b(latest|last|recent|current)\s+(report|leads?|results?|shortlist)\b|\b(give|show|send)\s+(me\s+)?(the\s+)?(report|leads|results|shortlist)\b|^\W*report\W*$)",
    re.I,
)


def strip_mentions(body: str) -> str:
    """Switch puts '@agent-name' in front of a targeted message. Intent matching must see the words after it."""
    return _LEADING_MENTIONS.sub("", body or "", count=1).strip()


def wants_report(body: str) -> bool:
    return bool(REPORT_INTENT.search(body or ""))


def report_text(session: Session) -> str:
    """The standing shortlist: best leads across all runs."""
    from sqlalchemy import func

    opps = session.scalars(select(Opportunity)).all()
    if not opps:
        return card("Latest report", lead="There are no stored leads yet.", next_step="`run` to look for some.")
    order = {"high_priority": 0, "qualified": 1, "approved": 2, "research_requested": 3, "needs_review": 4}

    def fit(o: Opportunity) -> int:
        ev = _latest_eval(session, o)
        return -(ev.freelance_fit_score or 0) if ev else 0

    seen: set[str] = set()
    top: list[Opportunity] = []
    for o in sorted(opps, key=lambda o: (order.get(o.status, 9), fit(o))):
        if o.company_id in seen or o.status in {"rejected"}:
            continue
        seen.add(o.company_id)
        top.append(o)
        if len(top) == 6:
            break
    mix = session.execute(select(Opportunity.status, func.count()).group_by(Opportunity.status)).all()
    summary = " · ".join(f"{label(s)} {n}" for s, n in sorted(mix))
    ev_of = {o.id: _latest_eval(session, o) for o in top}
    grid = table(["Lead", "Company", "Status", "Reading", "QA", "Source"], [
        [code(o.public_id), cell(_name(session, o), 32), label(o.status), _reading(session, o), (ev_of[o.id].qa_verdict if ev_of[o.id] else ""), _src(session, o)]
        for o in top])
    return scrub_reply(card("Latest report", lead=f"Stored leads: {summary}.", grid=grid,
                            note=f"Full detail and the CSV/JSON export are in the desk at /app. {NO_OUTREACH}",
                            next_step="`approve G…`, `reject G…` or `request research G…` with a lead id."))
