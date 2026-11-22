"""The specialist agents' decision-making.

Each function here gives one GOIP agent a goal, a set of read-only perception tools, and a bounded loop. The model
chooses which tool to use next and what to conclude. Everything it concludes is checked in code before it is stored:
quotes must occur in text the agent was shown, ids must belong to the run, services must come from the allowed list.

Every function returns None (or an empty result) when the model is unavailable or gave nothing valid. The caller then
runs the agent's fixed policy, and the trace records which mode actually ran.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents import memory
from app.agents.runtime import AgentResult, ToolSpec, run_agent
from app.agents.toolbox import ToolBox
from app.config import load_runtime
from app.db import Company, EvaluationVersion, Opportunity, Signal
from app.discovery.extract import RawItem, normalize_name
from app.discovery.gather import ALL_SOURCES, DEMAND_SOURCES, Gatherer
from app.discovery.sources import _CONTRACT, get_capped
from app.guardrails import Verdict
from app.scoring.evidence import quote_supported
from app.scoring.v2 import valid_verdict

_HN_ITEM = re.compile(r"https://news\.ycombinator\.com/item\?id=\d+")


def plain(text: str, limit: int = 3000) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text or "")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())[:limit]


def _ok(rule: str, detail: str = "") -> Verdict:
    return Verdict("output", rule, True, detail)


def _bad(rule: str, detail: str) -> Verdict:
    return Verdict("output", rule, False, detail)


class NoArgs(BaseModel):
    pass


def toolbox(t, agent: str, specs: list[ToolSpec]) -> ToolBox:
    return ToolBox(agent, t.budget, {s.name: s.fn for s in specs})


# ====================================================================== discovery


class FetchSourceArgs(BaseModel):
    source: str = Field(max_length=30)


class DiscoveryFinal(BaseModel):
    sources_used: list[str] = Field(max_length=8)
    stop_reason: str = Field(max_length=300)


@dataclass
class DiscoveryOutcome:
    result: AgentResult
    pool: list[RawItem] = field(default_factory=list)
    used: list[str] = field(default_factory=list)


async def agentic_discovery(t, goal: str, focus: str | None, exclude: tuple[str, ...] = (), hint: str = "") -> DiscoveryOutcome:
    """The agent decides which sources are worth fetching for this goal, in what order, and when it has enough."""
    gatherer = Gatherer(t.session, t.http, t.settings, t.run, sector=focus)
    pool: list[RawItem] = []
    used: list[str] = []

    def list_sources():
        return {
            "sources": {n: {"what": d, "explicit_demand": n in DEMAND_SOURCES, "already_fetched": n in used or n in exclude} for n, d in gatherer.available().items()},
            "fetched_so_far": len(pool),
        }

    def source_stats():
        return memory.source_stats(t.session)[:10]

    async def fetch_source(source: str):
        if source not in gatherer.available():
            raise ValueError(f"unknown or unavailable source. Choose from {', '.join(gatherer.available())}")
        if source in used or source in exclude:
            return {"note": "already fetched, use what you have"}
        items = await gatherer.run_source(source)
        pool.extend(items)
        used.append(source)
        return {
            "source": source, "fetched": len(items), "with_company_name": sum(1 for i in items if i.company_name),
            "explicit_contract_postings": sum(1 for i in items if _CONTRACT.search(f"{i.title} {i.excerpt}")),
            "sample_titles": [i.title[:90] for i in items[:4]],
        }

    specs = [
        ToolSpec("list_sources", "List the sources you can fetch, what each is good for, and which are explicit demand.", NoArgs, list_sources),
        ToolSpec("source_stats", "How each source performed in earlier runs: reliability, volume and leads it produced.", NoArgs, source_stats),
        ToolSpec("fetch_source", "Fetch one source and learn how many postings it returned and how many state a contract.", FetchSourceArgs, fetch_source),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        bad = [s for s in final["sources_used"] if s not in used]
        if bad or not used:
            return _bad("sources_not_fetched", f"you named sources you did not fetch: {bad or 'none fetched'}")
        return _ok("sources_fetched")

    result = await run_agent(
        role="Discovery",
        mission=(
            "Your job is to collect public postings that show a COMPANY wants paid freelance or contract engineering help. "
            "Sources marked explicit_demand return postings that can state that need; other sources only show business news "
            "and rarely do. Check source_stats to skip sources that have been unreliable or unproductive, honour the operator's focus "
            "(keep only what is about it), fetch the most promising sources first, and stop once you have about 8 postings that state a contract or "
            "you have tried the useful sources. Fetch at most 5 sources."
        ),
        goal=goal or "Find companies asking for freelance engineering help.",
        context={"focus": focus, "hint_from_orchestrator": hint or None, "already_fetched_elsewhere": list(exclude)},
        tools=specs, final_model=DiscoveryFinal, llm=t.llm, toolbox=toolbox(t, "goip-discovery", specs), budget=t.budget, max_steps=8,
        grounding=grounding, model_role="agent",
    )
    return DiscoveryOutcome(result, pool if result.used_model else pool, used)


# ======================================================================= research


class PageArgs(BaseModel):
    url: str = Field(max_length=500)


class ResearchFinal(BaseModel):
    evidence_quote: str = Field(min_length=3, max_length=600)
    industry: str = Field(default="", max_length=200)
    country: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=1000)
    inferred_need: str = Field(min_length=3, max_length=800)


async def agentic_research(t, company: Company, signals: list[Signal], evidence: str) -> AgentResult:
    """Research one company. The agent may open a page already stored for the company when the evidence is thin."""
    allowed = {s.source_url for s in signals if s.source_url}
    for s in signals:
        allowed.update(_HN_ITEM.findall(html.unescape(s.evidence or "")))

    def read_signals():
        return [{"type": s.signal_type, "source": s.source_name, "url": s.source_url, "title": s.title, "text": plain(s.evidence, 1200)} for s in signals]

    async def fetch_stored_page(url: str):
        if url not in allowed:
            raise ValueError("you may only open a page that is already stored for this company: " + ", ".join(sorted(allowed)[:4]))
        response = await get_capped(t.http, url, timeout=20, max_bytes=600_000)
        if response.status_code >= 400:
            return {"status": response.status_code, "text": ""}
        return {"status": response.status_code, "text": plain(response.text, 2800)}

    specs = [
        ToolSpec("read_signals", "Everything stored about this company: each signal's headline, source and text.", NoArgs, read_signals),
        ToolSpec("fetch_stored_page", "Open one of this company's stored source pages to read more of it.", PageArgs, fetch_stored_page),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        if not quote_supported(final["evidence_quote"], seen):
            return _bad("quote_not_in_source", "evidence_quote must be copied exactly from text you were shown")
        return _ok("grounded")

    return await run_agent(
        role="Company research",
        mission=(
            "Research ONE company from what is stored about it. If the stored text is thin and a stored page might say more, "
            "open it. Then answer with: one exact quote that shows why this company appeared (copied word for word), its "
            "industry and country only if the text states them, a one-sentence description, and the technical need AS AN "
            "INFERENCE (what the text suggests, never a claim that they are hiring unless it says so)."
        ),
        goal=f"Research {company.name}.",
        context={"company": company.name, "domain": company.domain, "signals_preview": plain(evidence, 900)},
        tools=specs, final_model=ResearchFinal, llm=t.llm, toolbox=toolbox(t, "goip-company-research", specs), budget=t.budget,
        max_steps=3, grounding=grounding, model_role="research",
    )


# ================================================================ freelance judge


class VerdictIn(BaseModel):
    signal_id: str = Field(max_length=40)
    is_freelance_opportunity: bool
    poster: Literal["company", "individual_seeker", "recruiter", "unknown"]
    engagement: Literal["contract", "freelance", "part_time", "full_time", "unclear"]
    work: Literal["engineering", "other"]
    confidence: Literal["low", "medium", "high"]
    quote: str = Field(default="", max_length=300)
    reasoning: str = Field(default="", max_length=300)


class PageListArgs(BaseModel):
    offset: int = Field(default=0, ge=0, le=500)


class SubmitArgs(BaseModel):
    verdicts: list[VerdictIn] = Field(max_length=25)


class JudgeFinal(BaseModel):
    summary: str = Field(max_length=400)
    judged: int = Field(ge=0, le=200)


def _raw(signal: Signal) -> str:
    return signal.evidence or signal.summary or signal.title or ""


def judge_candidates(t, limit: int = 16) -> list[tuple[Opportunity, Signal]]:
    """Postings in this run that could be a demand signal and have no verdict yet."""
    out: list[tuple[Opportunity, Signal]] = []
    for opp in t.session.scalars(select(Opportunity).where(Opportunity.run_id == t.run_id)).all():
        for sig in t.session.scalars(select(Signal).where(Signal.company_id == opp.company_id, Signal.run_id == t.run_id)).all():
            text = f"{sig.title} {_raw(sig)}"
            if sig.classification is None and (sig.category == "hiring" or sig.signal_type == "hiring" or _CONTRACT.search(text)):
                out.append((opp, sig))
    return out[:limit]


async def agentic_judge(t) -> tuple[AgentResult, int]:
    """Decide, posting by posting, whether a COMPANY is offering paid contract or freelance engineering work.

    The agent reads each posting, may look at examples of what the reviewer approved or rejected before, and submits
    verdicts through one validated tool. A verdict that claims an offer is stored only if its quote is in the posting.
    """
    candidates = judge_candidates(t)
    by_id = {sig.id: (opp, sig) for opp, sig in candidates}
    stored: list[str] = []
    if not candidates:
        return AgentResult(mode="fallback", reason="no postings to judge"), 0

    PAGE = 4  # a page must fit in one observation, so the model sees every posting it is asked to judge

    def list_postings(offset: int = 0):
        page = candidates[offset : offset + PAGE]
        return {
            "total": len(candidates), "offset": offset, "next_offset": offset + PAGE if offset + PAGE < len(candidates) else None,
            "postings": [
                {"signal_id": sig.id, "lead": opp.public_id, "company": (t.session.get(Company, opp.company_id) or Company()).name,
                 "source": sig.source_name, "posting": plain(f"{sig.title}. {_raw(sig)}", 600)}
                for opp, sig in page
            ],
        }

    def reviewer_examples():
        return memory.reviewer_examples(t.session)

    def submit_verdicts(verdicts: list[dict]):
        accepted, rejected = 0, []
        for v in verdicts:
            pair = by_id.get(v["signal_id"])
            if pair is None:
                rejected.append({"signal_id": v["signal_id"], "reason": "not one of the postings you were given"})
                continue
            _, sig = pair
            norm = valid_verdict({k: v[k] for k in v if k != "signal_id"}, _raw(sig))
            if norm is None:
                rejected.append({"signal_id": v["signal_id"], "reason": "a verdict that claims a contract offer must quote the posting word for word"})
                continue
            sig.classification = {**norm, "by": "goip-qualification", "at": datetime.now(timezone.utc).isoformat()}
            stored.append(sig.id)
            accepted += 1
        t.session.commit()
        return {"accepted": accepted, "rejected": rejected}

    specs = [
        ToolSpec("list_postings", "A page of four postings to judge (id, company, source, text). Call again with next_offset for the next page.", PageListArgs, list_postings),
        ToolSpec("reviewer_examples", "Postings the human reviewer approved or rejected before, to calibrate what counts.", NoArgs, reviewer_examples),
        ToolSpec("submit_verdicts", "Record your verdicts. Each needs the signal_id, a decision, who is posting, the engagement type, and an exact quote.", SubmitArgs,
                 lambda verdicts: submit_verdicts([v if isinstance(v, dict) else v.model_dump() for v in verdicts])),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        if final["judged"] > len(stored):
            return _bad("judged_more_than_stored", f"you claim {final['judged']} verdicts but {len(stored)} were accepted")
        return _ok("verdicts_stored")

    result = await run_agent(
        role="Freelance opportunity judge",
        mission=(
            "For each posting decide whether it is a COMPANY offering paid contract or freelance ENGINEERING work (building, "
            "integrating or consulting on software). These are NOT freelance opportunities: a person offering their own services "
            "(poster individual_seeker, for example 'Location / Willing to relocate / Freelance: Yes'), permanent or full-time "
            "roles, internships, unpaid work, non-engineering work, or a recruiter collecting CVs with no client named. A company "
            "may describe it without the word 'contract' (a fixed-length engagement, a project, 'help us build'). Quote the exact "
            "words that state the engagement; if the posting does not state one, answer is_freelance_opportunity=false with "
            "engagement 'unclear'. Use the reviewer examples to calibrate. Work through every page, submitting verdicts for each page, then answer."
        ),
        goal="Identify which postings are real freelance or contract engineering opportunities.",
        context={"postings_to_judge": len(candidates)}, tools=specs, final_model=JudgeFinal, llm=t.llm,
        toolbox=toolbox(t, "goip-qualification", specs), budget=t.budget, max_steps=14, grounding=grounding, model_role="qualification",
    )
    return result, len(stored)


# ================================================================ technical


class GithubSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=80)


class RepoArgs(BaseModel):
    full_name: str = Field(pattern=r"^[\w.-]{1,60}/[\w.-]{1,100}$")


class RepoMatch(BaseModel):
    company_id: str = Field(max_length=40)
    repo_url: str | None = Field(default=None, max_length=300)
    why: str = Field(default="", max_length=240)


class TechnicalFinal(BaseModel):
    matches: list[RepoMatch] = Field(max_length=12)


def technical_candidates(t, limit: int = 6) -> list[tuple[Opportunity, Company]]:
    rows = []
    for opp in t.session.scalars(select(Opportunity).where(Opportunity.run_id == t.run_id)).all():
        company = t.session.get(Company, opp.company_id)
        if company is None:
            continue
        sigs = t.session.scalars(select(Signal).where(Signal.company_id == opp.company_id, Signal.run_id == t.run_id)).all()
        demand = any(s.category == "hiring" or s.signal_type == "hiring" for s in sigs)
        rows.append((0 if demand else 1, opp, company))
    rows.sort(key=lambda r: r[0])
    return [(o, c) for _, o, c in rows[:limit]]


async def _github_json(t, url: str, accept: str = "application/vnd.github+json"):
    response = await get_capped(t.http, url, timeout=20, max_bytes=800_000, headers={"Accept": accept, "User-Agent": "GOIP-research"})
    if response.status_code == 404:
        raise ValueError("not found")
    response.raise_for_status()
    return response


async def agentic_technical(t, candidates: list[tuple[Opportunity, Company]]) -> tuple[AgentResult, dict[str, dict]]:
    """Find public repositories that really belong to the candidate companies. Returns the agent result and the repos it saw."""
    seen_repos: dict[str, dict] = {}
    cand = {c.id: (o, c) for o, c in candidates}

    def remember_repo(item: dict, readme: str = "") -> dict:
        info = {
            "full_name": item.get("full_name"), "url": item.get("html_url"), "description": item.get("description") or "",
            "license": ((item.get("license") or {}).get("spdx_id") or "unknown"), "stars": item.get("stargazers_count"),
            "topics": item.get("topics") or [], "readme": readme[:1200],
        }
        if info["url"]:
            seen_repos[info["url"]] = info
        return info

    def list_candidates():
        return [{"company_id": c.id, "name": c.name, "domain": c.domain, "description": (c.description or "")[:200]} for _, c in candidates]

    async def github_search(query: str):
        data = (await _github_json(t, f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page=5&sort=stars")).json()
        return [{k: v for k, v in remember_repo(i).items() if k != "readme"} for i in (data.get("items") or [])[:5]]

    async def github_repo(full_name: str):
        item = (await _github_json(t, f"https://api.github.com/repos/{full_name}")).json()
        try:
            readme = (await _github_json(t, f"https://api.github.com/repos/{full_name}/readme", "application/vnd.github.raw")).text
        except Exception:  # noqa: BLE001 - a repository without a README is still a repository
            readme = ""
        return remember_repo(item, plain(readme, 1200))

    specs = [
        ToolSpec("read_company", "The companies you are matching: id, name, domain, description.", NoArgs, list_candidates),
        ToolSpec("github_search", "Search public GitHub repositories. Try the company name, its product, or its domain.", GithubSearchArgs, github_search),
        ToolSpec("github_repo", "Read one repository's description, topics, licence and the start of its README.", RepoArgs, github_repo),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        for m in final["matches"]:
            if m["company_id"] not in cand:
                return _bad("unknown_company", f"{m['company_id']} is not one of your companies")
            if not m["repo_url"]:
                continue
            repo = seen_repos.get(m["repo_url"])
            if repo is None:
                return _bad("repo_not_seen", f"{m['repo_url']} was never returned by a search or read; do not invent repositories")
            company = cand[m["company_id"]][1]
            hay = normalize_name(f"{repo['full_name']} {repo['description']} {' '.join(repo['topics'])} {repo['readme']}")
            name = normalize_name(company.name)
            stem = (company.domain or "").split(".")[0].lower()
            if not ((len(name) >= 3 and name in hay) or (len(stem) >= 4 and stem in hay)):
                return _bad("repo_not_about_company", f"{repo['full_name']} never mentions {company.name}")
        return _ok("repos_grounded")

    result = await run_agent(
        role="Technical intelligence",
        mission=(
            "For each company, find a public GitHub repository that genuinely belongs to it or is its product (not a library that "
            "merely shares a word with its name). Search with the company name, then read promising repositories before you "
            "decide. A match needs a repository you actually saw whose text mentions the company. If you cannot find one, give "
            "repo_url null for that company. Never invent a repository. Spend at most about 8 tool calls."
        ),
        goal="Match companies to their public repositories.", context={"companies": len(candidates)},
        tools=specs, final_model=TechnicalFinal, llm=t.llm, toolbox=toolbox(t, "goip-technical-intelligence", specs), budget=t.budget,
        max_steps=10, grounding=grounding, model_role="technical",
    )
    return result, seen_repos


# ================================================================== strategy


class EvalArgs(BaseModel):
    opportunity_id: str = Field(max_length=24)


class Recommendation(BaseModel):
    opportunity_id: str = Field(max_length=24)
    service: str = Field(max_length=120)
    requirement_quote: str = Field(min_length=3, max_length=400)
    rationale: str = Field(default="", max_length=300)


class StrategyFinal(BaseModel):
    recommendations: list[Recommendation] = Field(max_length=10)


def reviewable(t, statuses=("qualified", "high_priority"), limit: int = 8) -> list[Opportunity]:
    rows = t.session.scalars(select(Opportunity).where(Opportunity.run_id == t.run_id, Opportunity.status.in_(statuses))).all()
    return rows[:limit]


def posting_text(t, opp: Opportunity) -> str:
    return "\n".join(_raw(s) for s in t.session.scalars(select(Signal).where(Signal.company_id == opp.company_id, Signal.run_id == t.run_id)).all())


def _latest_eval(t, opp: Opportunity) -> EvaluationVersion | None:
    return t.session.scalars(select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opp.id, EvaluationVersion.method == "v2_dimensions")
                             .order_by(EvaluationVersion.version.desc())).first()


def _read_opportunity(t, opp: Opportunity) -> dict:
    ev = _latest_eval(t, opp)
    company = t.session.get(Company, opp.company_id)
    out = {"opportunity_id": opp.public_id, "company": company.name if company else "", "status": opp.status, "posting": plain(posting_text(t, opp), 900)}
    if ev:
        out.update({
            "qualification": ev.qualification, "qa_verdict": ev.qa_verdict, "confidence": ev.confidence,
            "scores": {"business": ev.business_signal_score, "technical": ev.technical_evidence_score, "freelance_fit": ev.freelance_fit_score},
            "findings": [{"kind": f.get("classification"), "claim": str(f.get("claim"))[:160], "quote": str(f.get("quotation"))[:160]} for f in (ev.findings or [])[:6]],
            "qa_flags": [c for c in ((ev.detail or {}).get("qa") or {}).get("checks", []) if c.get("result") in ("flag", "reject")][:4],
        })
    return out


async def agentic_strategy(t, candidates: list[Opportunity]) -> AgentResult:
    """Name which allowed service a lead's own words support, quoting the requirement. Never contacts anyone."""
    by_pid = {o.public_id: o for o in candidates}
    services = list(load_runtime().get("services", []))

    def read_evaluation(opportunity_id: str):
        opp = by_pid.get(opportunity_id)
        if opp is None:
            raise ValueError("not one of your leads: " + ", ".join(by_pid))
        return _read_opportunity(t, opp)

    specs = [
        ToolSpec("read_evaluation", "A lead's posting text, evaluation, scores and findings.", EvalArgs, read_evaluation),
        ToolSpec("list_services", "The services a recommendation may name. Nothing else is allowed.", NoArgs, lambda: services),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        for r in final["recommendations"]:
            opp = by_pid.get(r["opportunity_id"])
            if opp is None:
                return _bad("unknown_lead", f"{r['opportunity_id']} is not one of your leads")
            if r["service"] not in services:
                return _bad("service_not_allowed", f"'{r['service']}' is not in the allowed list")
            if not quote_supported(r["requirement_quote"], posting_text(t, opp)):
                return _bad("quote_not_in_posting", f"the requirement quote for {r['opportunity_id']} is not in its posting")
        return _ok("grounded")

    return await run_agent(
        role="Strategy",
        mission=(
            "For each lead, say which ONE allowed service its own posting supports, and quote the words of the posting that state "
            "the requirement. If the posting states no requirement that maps to a service, leave that lead out. You only describe a "
            "possible service. You never draft, send or approve anything."
        ),
        goal="Match each qualified lead to a service its posting supports.", context={"leads": list(by_pid)},
        tools=specs, final_model=StrategyFinal, llm=t.llm, toolbox=toolbox(t, "goip-strategy", specs), budget=t.budget,
        max_steps=len(candidates) + 3, grounding=grounding, model_role="strategy",
    )


# ========================================================================== QA


class Review(BaseModel):
    opportunity_id: str = Field(max_length=24)
    verdict: Literal["pass", "flag", "reject"]
    reasons: list[str] = Field(default_factory=list, max_length=4)


class QAFinal(BaseModel):
    reviews: list[Review] = Field(max_length=12)


async def agentic_qa(t, candidates: list[Opportunity]) -> AgentResult:
    """Try to disprove each strong lead. The agent can re-open the original page to confirm the evidence is still there."""
    by_pid = {o.public_id: o for o in candidates}

    def read_opportunity(opportunity_id: str):
        opp = by_pid.get(opportunity_id)
        if opp is None:
            raise ValueError("not one of your leads: " + ", ".join(by_pid))
        return _read_opportunity(t, opp)

    async def recheck_source(opportunity_id: str):
        opp = by_pid.get(opportunity_id)
        if opp is None:
            raise ValueError("not one of your leads: " + ", ".join(by_pid))
        sig = t.session.scalars(select(Signal).where(Signal.company_id == opp.company_id, Signal.run_id == t.run_id).order_by(Signal.discovered_at)).first()
        if sig is None or not (sig.source_url or "").startswith("https://"):
            return {"checked": False, "reason": "no stored https source"}
        snippet = plain(_raw(sig), 90) or plain(sig.title, 90)
        response = await get_capped(t.http, sig.source_url, timeout=20, max_bytes=900_000)
        text = plain(response.text, 400_000).lower() if response.status_code < 400 else ""
        return {"checked": True, "http_status": response.status_code, "page_chars": len(text), "stored_text_still_on_page": bool(snippet) and snippet.lower() in text, "stored_text_checked": snippet}

    specs = [
        ToolSpec("read_opportunity", "A lead's posting text, status, scores, findings and the QA flags already raised.", EvalArgs, read_opportunity),
        ToolSpec("recheck_source", "Re-open the lead's original page and report whether the stored text is still on it.", EvalArgs, recheck_source),
    ]

    def grounding(final: dict, seen: str) -> Verdict:
        for r in final["reviews"]:
            if r["opportunity_id"] not in by_pid:
                return _bad("unknown_lead", f"{r['opportunity_id']} is not one of your leads")
            if r["verdict"] != "pass" and not r["reasons"]:
                return _bad("no_reason", f"a {r['verdict']} for {r['opportunity_id']} needs at least one reason")
        return _ok("reviewed")

    return await run_agent(
        role="Quality assurance",
        mission=(
            "You are the adversarial reviewer. For each lead, try to DISPROVE it: is the posting really a company offering paid "
            "contract engineering work, or something else? Is the evidence consistent with the scores? Re-check the original page "
            "when the evidence looks thin or surprising. Answer pass, flag (a concern a human should see) or reject (the lead should "
            "not be shown as strong). Give a reason for every flag or reject. You can only lower trust in a lead, never raise it."
        ),
        goal="Review each strong lead and look for reasons it is wrong.", context={"leads": list(by_pid)},
        tools=specs, final_model=QAFinal, llm=t.llm, toolbox=toolbox(t, "goip-quality-assurance", specs), budget=t.budget,
        max_steps=len(candidates) * 2 + 3, grounding=grounding, model_role="qa",
    )
