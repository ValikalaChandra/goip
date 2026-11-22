from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, load_runtime
from app.db import (
    Company,
    Opportunity,
    PipelineRun,
    Signal,
    SourceHealth,
    StatusEvent,
    utcnow,
)
from app.discovery.gather import ALL_SOURCES, Gatherer, record_health as _record_health_row
from app.discovery.names import name_unnamed
from app.discovery.extract import RawItem, is_publisher, normalize_name, registrable_domain
from app.discovery.sources import (
    FOCUS_FEEDS,
    crawl4ai_scrape,
    crawl4ai_search,
    fetch_github,
    fetch_hacker_news,
    fetch_hn_hiring,
    fetch_job_boards,
    fetch_rss,
    matches_focus,
)
from app.integrations.openrouter import complete_json, quote_supported
from app.scoring.engine import score_opportunity
from app.guardrails import check_grounded_output
from app.security.text import injection_flags

CSV_HEADERS = [
    "Lead ID",
    "Company Name",
    "Website",
    "Industry",
    "Domain",
    "Country",
    "Company Description",
    "Business Signal",
    "Signal Date",
    "Discovery Date",
    "Source Name",
    "Source URL",
    "Evidence",
    "Potential Technical Need",
    "Why Approach This Company?",
    "Recommended Freelance Service",
    "Open-Source Starting Point",
    "GitHub Repository URL",
    "Repository License",
    "Potential Decision Maker",
    "Public Professional Profile URL",
    "Outreach Strategy",
    "Why Now?",
    "Opportunity Score",
    "Confidence Level",
    "Lead Status",
    "Recommended Action",
    "Research Timestamp",
]


def clean_model_fields(parsed) -> dict:
    """The model's JSON is untrusted too: keep only the five expected string fields, capped."""
    if not isinstance(parsed, dict):
        return {}
    caps = {"evidence_quote": 600, "industry": 200, "country": 120, "description": 1000, "inferred_need": 800}
    return {k: v.strip()[:n] for k, n in caps.items() if isinstance((v := parsed.get(k)), str) and v.strip()}


def _id() -> str:
    return str(uuid.uuid4())


def _public_id() -> str:
    return "G" + uuid.uuid4().hex[:8].upper()


def _record_health(session: Session, run_id: str, **kwargs) -> None:
    session.add(SourceHealth(id=_id(), run_id=run_id, fetched_at=utcnow(), **kwargs))


def _set_status(session: Session, opportunity: Opportunity, status: str, reason: str, actor: str) -> None:
    if opportunity.status == status and opportunity.status_reason == reason:
        return
    previous = opportunity.status
    from app.guardrails import check_status_transition, require

    require(check_status_transition(previous, status, actor))
    opportunity.status = status
    opportunity.status_reason = reason
    session.add(
        StatusEvent(
            id=_id(),
            opportunity_id=opportunity.id,
            from_status=previous,
            to_status=status,
            reason=reason,
            actor=actor,
        )
    )


def _company_for(session: Session, item: RawItem) -> Company | None:
    if not item.company_name:
        return None
    normalized = normalize_name(item.company_name)
    if not normalized or is_publisher(normalized):
        return None
    domain = registrable_domain(item.website)
    if domain and is_publisher(domain):
        domain = None
        item.website = None
    identity = f"domain:{domain}" if domain else f"name:{normalized}"
    company = session.scalar(select(Company).where(Company.identity_key == identity))
    if company is None and domain:
        company = session.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is None:
        company = Company(
            id=_id(),
            identity_key=identity,
            name=item.company_name,
            normalized_name=normalized,
            website=item.website,
            domain=domain,
            description=None,
            created_at=utcnow(),
        )
        session.add(company)
        session.flush()
    elif item.website and not company.website:
        company.website = item.website
        company.domain = domain
    return company


def _add_signal(session: Session, run_id: str, item: RawItem, company: Company | None, seen: set[tuple[str, str]]) -> bool:
    hint = company.identity_key if company else normalize_name(item.title)[:180]
    key = (item.source_url, hint)
    if key in seen:
        return False
    exists = session.scalar(
        select(Signal).where(Signal.source_url == item.source_url, Signal.identity_hint == hint)
    )
    if exists is not None:
        return False
    seen.add(key)
    session.add(
        Signal(
            id=_id(),
            company_id=company.id if company else None,
            run_id=run_id,
            identity_hint=hint,
            source_name=item.source_name,
            source_url=item.source_url,
            parent_domain=item.parent_domain,
            category=item.category,
            title=item.title,
            summary=item.title,
            evidence=(item.excerpt or item.title)[:2000],
            signal_type=item.signal_type,
            published_at=item.published_at,
            discovered_at=utcnow(),
            excerpt=(item.excerpt or "")[:2000],
            verification_status="source_linked",
            claim_kind="observed",
            agent_name="goip-discovery",
        )
    )
    return True


async def discover(
    session: Session,
    http: httpx.AsyncClient,
    settings: Settings,
    run: PipelineRun,
    sources: list[str] | None = None,
    pool: list[RawItem] | None = None,
    used: list[str] | None = None,
    focus: str | None = None,
) -> dict:
    """Gather (all sources, a chosen list, or an already gathered pool) and turn the items into companies and signals."""
    runtime = load_runtime()
    caps = runtime["fetch_caps"]
    gatherer = Gatherer(session, http, settings, run, sector=focus)
    sector = gatherer.sector
    used = list(used or [])
    if pool is None:
        pool, used = await gatherer.gather(list(sources) if sources else list(ALL_SOURCES))
    named_by_model = await name_unnamed(http, settings, [i for i in pool if i.category != "hiring"], int(caps.get("name_llm_titles", 60)))
    raw_count = 0
    duplicate_signals = 0
    companies: dict[str, Company] = {}
    seen: set[tuple[str, str]] = set()
    for item in pool:
        raw_count += 1
        company = _company_for(session, item)
        created = _add_signal(session, run.id, item, company, seen)
        if not created:
            duplicate_signals += 1
        if company is not None:
            companies[company.id] = company
    session.flush()
    screened_ids = []
    for company in companies.values():
        signals = session.scalars(select(Signal).where(Signal.company_id == company.id, Signal.run_id == run.id)).all()
        if any(signal.signal_type != "other" for signal in signals):
            screened_ids.append(company.id)
    run.counts = {
        "raw_items": raw_count,
        "duplicate_signals": duplicate_signals,
        "discovered": len(companies),
        "screened": len(screened_ids),
        "focus": sector,
        "hiring_posts": sum(1 for i in pool if i.category == "hiring"),
        "named_by_model": named_by_model,
        "sources": used,
        "unmatched_items": raw_count - sum(1 for item in pool if item.company_name),
    }
    session.commit()
    return {"company_ids": screened_ids, "counts": run.counts}


def _signals_for(session: Session, run_id: str, company_id: str) -> list[Signal]:
    return list(session.scalars(select(Signal).where(Signal.run_id == run_id, Signal.company_id == company_id)).all())


def _ensure_opportunity(session: Session, run: PipelineRun, company: Company) -> Opportunity:
    found = session.scalar(
        select(Opportunity).where(Opportunity.run_id == run.id, Opportunity.company_id == company.id)
    )
    if found:
        return found
    opportunity = Opportunity(
        id=_id(),
        public_id=_public_id(),
        run_id=run.id,
        company_id=company.id,
        status="screening",
        facts=[],
        inferences=[],
        recommendations=[],
        score_detail={},
    )
    session.add(opportunity)
    session.flush()
    _set_status(session, opportunity, "screening", "Passed the business-signal screen.", "goip-discovery")
    return opportunity


def prepare_research(session: Session, run: PipelineRun, company_id: str):
    """Everything a researcher needs for one company: the opportunity, its signals, and the evidence text."""
    company = session.get(Company, company_id)
    if company is None:
        return None
    opportunity = _ensure_opportunity(session, run, company)
    signals = _signals_for(session, run.id, company.id)
    evidence = "\n".join(f"{signal.title}\n{signal.evidence}\n{signal.source_url}" for signal in signals)
    return company, opportunity, signals, evidence


def apply_research(session: Session, company: Company, opportunity: Opportunity, signals: list[Signal], evidence: str, parsed: dict | None) -> bool:
    """Store a research result. The quote must really occur in the evidence; otherwise the stored signal text is used.

    `parsed` comes from a model (one-shot or an agent). It is never trusted: it is shape-checked and grounded here.
    Returns whether the model's quote was accepted.
    """
    parsed = clean_model_fields(parsed)
    facts = [
        {"kind": "observed", "text": signal.summary or signal.title, "source_url": signal.source_url, "signal_type": signal.signal_type}
        for signal in signals
    ]
    grounded = check_grounded_output("observed", parsed.get("evidence_quote", ""), evidence)
    if parsed and not grounded.blocked:
        quote = str(parsed["evidence_quote"])
        if parsed.get("industry") and not company.industry:
            company.industry = str(parsed["industry"])[:200]
        if parsed.get("country") and not company.country:
            company.country = str(parsed["country"])[:120]
        if parsed.get("description") and not company.description:
            company.description = str(parsed["description"])[:1000]
    else:
        quote = (signals[0].evidence if signals else "")[:400]
    flags = injection_flags(evidence)
    opportunity.facts = facts
    opportunity.inferences = [
        {
            "kind": "inference",
            "text": parsed.get("inferred_need")
            or "A recent business signal may create implementation work, but the source does not say the company is hiring a freelancer.",
            "grounded": not grounded.blocked,
        }
    ]
    opportunity.technical_need = opportunity.inferences[0]["text"]
    opportunity.technical_need_kind = "inference"
    opportunity.limitations = (
        "Industry, country, and technical need are incomplete where the source did not state them."
        + (f" Source text contained instruction-like phrases and they were ignored: {flags}." if flags else "")
    )
    if quote:
        opportunity.facts.append({"kind": "observed", "text": quote, "source_url": signals[0].source_url if signals else ""})
    _set_status(session, opportunity, "researching", "Company research recorded from linked sources.", "goip-company-research")
    opportunity.researched_at = utcnow()
    return not grounded.blocked


async def research(session: Session, http: httpx.AsyncClient, settings: Settings, run: PipelineRun, company_ids: list[str]) -> dict:
    """The fixed policy: one model call per company, or the stored text when the model is unavailable."""
    runtime = load_runtime()
    limit = int(runtime["targets"]["researched"])
    chosen = company_ids[:limit]
    usage_rows = []
    for company_id in chosen:
        prepared = prepare_research(session, run, company_id)
        if prepared is None:
            continue
        company, opportunity, signals, evidence = prepared
        parsed, usage = await complete_json(
            http,
            api_key=settings.openrouter_api_key,
            model=runtime["models"]["research"],
            fallbacks=runtime["model_fallbacks"],
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            system=(
                "You extract only what the source supports. Return JSON with keys "
                "evidence_quote, industry, country, description, inferred_need. "
                "evidence_quote must be copied from the source. inferred_need is an inference, not a vacancy."
            ),
            user=evidence,
        )
        usage_rows.append(usage)
        apply_research(session, company, opportunity, signals, evidence, parsed)
    counts = dict(run.counts or {})
    counts["researched"] = len(chosen)
    run.counts = counts
    run.llm_usage = {"calls": usage_rows}
    session.commit()
    return {"company_ids": chosen}


def attach_github(session: Session, run: PipelineRun, repos: list[dict]) -> dict:
    opportunities = session.scalars(select(Opportunity).where(Opportunity.run_id == run.id)).all()
    attached = 0
    for opportunity in opportunities:
        company = session.get(Company, opportunity.company_id)
        if company is None:
            continue
        needle = company.normalized_name
        match = None
        for repo in repos:
            haystack = f"{repo.get('name','')} {repo.get('description','')}".lower()
            if needle and needle in haystack:
                match = repo
                break
        if match is None and repos:
            match = None
        if match:
            license_name = match.get("license") or "unknown"
            if license_name in {"NOASSERTION", "OTHER", None}:
                relevance = "A public repository name-matches the company, but the license is unclear so it is a reference, not code to copy."
            else:
                relevance = f"The repository name or description matches the company. License: {license_name}. Use it as a starting point only if that license fits the engagement."
            opportunity.oss_name = match.get("name")
            opportunity.oss_url = match.get("url")
            opportunity.oss_license = license_name
            opportunity.oss_relevance = relevance
            attached += 1
        _set_status(session, opportunity, "researching", "Technical repository search completed.", "goip-technical-intelligence")
    session.commit()
    return {"repositories_seen": len(repos), "attached": attached}


def qualify(session: Session, run: PipelineRun) -> dict:
    runtime = load_runtime()
    opportunities = session.scalars(select(Opportunity).where(Opportunity.run_id == run.id)).all()
    qualified = 0
    priority = 0
    scored: list[tuple[int, Opportunity]] = []
    for opportunity in opportunities:
        company = session.get(Company, opportunity.company_id)
        signals = _signals_for(session, run.id, opportunity.company_id)
        if not signals or company is None:
            continue
        from app.scoring.persist import record_if_changed

        version, _wrote = record_if_changed(session, opportunity, preserve_record=True)
        opportunity.why_approach = (
            f"Observed signal: {signals[0].signal_type}. "
            "A business signal is not a freelance contract. "
            f"Qualification: {version.qualification}."
        )
        opportunity.why_now = (version.detail or {}).get("explanation", ["No v2 explanation was stored."])[0]
        opportunity.outreach_strategy = "Review the source, then decide whether a short, specific note is appropriate. Do not send it from GOIP."
        opportunity.recommended_action = "Human review"
        proposed = (version.services or [{}])[0].get("proposed_service")
        if proposed and not opportunity.recommended_service:
            opportunity.recommended_service = proposed
        if version.qualification == "freelance_evidence" and version.qa_verdict != "reject":
            _set_status(session, opportunity, "qualified", "An external contracting requirement is stated in a stored source.", "goip-qualification")
            qualified += 1
            scored.append((version.freelance_fit_score or 0, opportunity))
        else:
            _set_status(
                session,
                opportunity,
                "needs_review",
                "Business activity alone does not qualify a freelance opportunity.",
                "goip-qualification",
            )
    scored.sort(key=lambda item: item[0], reverse=True)
    cap = int(runtime["targets"]["priority"])
    for _fit, opportunity in scored[:cap]:
        _set_status(session, opportunity, "high_priority", "An external contracting requirement is stated. A person still has to approve any contact.", "goip-qualification")
        opportunity.recommended_action = "Review in Switch and approve before any outreach draft"
        priority += 1
    counts = dict(run.counts or {})
    counts["qualified"] = qualified
    counts["high_priority"] = priority
    run.counts = counts
    session.commit()
    return counts


def quality_check(session: Session, run: PipelineRun) -> dict:
    flagged = 0
    opportunities = session.scalars(select(Opportunity).where(Opportunity.run_id == run.id)).all()
    for opportunity in opportunities:
        signals = _signals_for(session, run.id, opportunity.company_id)
        notes = []
        if not signals:
            notes.append("No source signal is linked.")
        if any(not signal.source_url.startswith("http") for signal in signals):
            notes.append("A source URL is missing or not http(s).")
        if opportunity.technical_need_kind != "inference":
            notes.append("Technical need was not labelled as an inference.")
        if not opportunity.facts:
            notes.append("No observed fact was stored.")
        opportunity.qa_notes = " ".join(notes) if notes else "Source URL, observed fact, and inference label are present."
        if notes:
            flagged += 1
            if opportunity.status == "high_priority":
                _set_status(session, opportunity, "needs_review", opportunity.qa_notes, "goip-quality-assurance")
        else:
            opportunity.qa_notes = "QA checked the stored source URL and the fact/inference split. It did not independently re-fetch every page."
    counts = dict(run.counts or {})
    counts["qa_flags"] = flagged
    counts["high_priority"] = session.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.run_id == run.id, Opportunity.status == "high_priority")
    ) or 0
    run.counts = counts
    session.commit()
    return counts


def choose_stored_company(session: Session) -> tuple[Opportunity, Company, list[Signal]] | None:
    """One company already stored, with a plausible name and at least one sourced signal."""
    from app.discovery.extract import _plausible_company_name

    opportunities = session.scalars(select(Opportunity)).all()
    best: tuple[tuple[int, int], Opportunity, Company, list[Signal]] | None = None
    for opportunity in opportunities:
        company = session.get(Company, opportunity.company_id)
        if company is None or not _plausible_company_name(company.name):
            continue
        signals = [
            signal
            for signal in session.scalars(select(Signal).where(Signal.company_id == company.id)).all()
            if (signal.source_url or "").startswith("http") and (signal.evidence or signal.summary or signal.title)
        ]
        if not signals:
            continue
        rank = (len(signals), opportunity.score or 0)
        if best is None or rank > best[0]:
            best = (rank, opportunity, company, signals)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _stored_signals(session: Session, company_id: str) -> list[Signal]:
    return [
        signal
        for signal in session.scalars(select(Signal).where(Signal.company_id == company_id)).all()
        if (signal.source_url or "").startswith("http")
    ]


async def refresh_company_research(
    session: Session,
    http: httpx.AsyncClient,
    settings: Settings,
    opportunity: Opportunity,
    company: Company,
    signals: list[Signal],
) -> str:
    """Refresh one stored company from its existing sources. Does not change run counts."""
    runtime = load_runtime()
    evidence = "\n".join(f"{signal.title}\n{signal.evidence}\n{signal.source_url}" for signal in signals)
    facts = [
        {
            "kind": "observed",
            "text": signal.summary or signal.title,
            "source_url": signal.source_url,
            "signal_type": signal.signal_type,
        }
        for signal in signals
    ]
    parsed, _usage = await complete_json(
        http,
        api_key=settings.openrouter_api_key,
        model=runtime["models"]["research"],
        fallbacks=runtime["model_fallbacks"],
        site_url=settings.openrouter_site_url,
        app_name=settings.openrouter_app_name,
        system=(
            "You extract only what the source supports. Return JSON with keys "
            "evidence_quote, industry, country, description, inferred_need. "
            "evidence_quote must be copied from the source. inferred_need is an inference, not a vacancy."
        ),
        user=evidence,
    )
    parsed = clean_model_fields(parsed)
    if parsed and not check_grounded_output("observed", parsed.get("evidence_quote", ""), evidence).blocked:
        if parsed.get("industry") and not company.industry:
            company.industry = str(parsed["industry"])[:200]
        if parsed.get("country") and not company.country:
            company.country = str(parsed["country"])[:120]
        if parsed.get("description"):
            company.description = str(parsed["description"])[:1000]
        facts.append(
            {
                "kind": "observed",
                "text": str(parsed["evidence_quote"])[:500],
                "source_url": signals[0].source_url if signals else "",
            }
        )
    flags = injection_flags(evidence)
    opportunity.facts = facts
    inferred = (parsed or {}).get("inferred_need") or (
        "A recent business signal may create implementation work, but the source does not say the company is hiring a freelancer."
    )
    opportunity.inferences = [{"kind": "inference", "text": str(inferred)[:800]}]
    opportunity.technical_need = str(inferred)[:800]
    opportunity.technical_need_kind = "inference"
    opportunity.limitations = (
        "Industry, country, and technical need are incomplete where the source did not state them."
        + (f" Source text contained instruction-like phrases and they were ignored: {flags}." if flags else "")
    )
    opportunity.researched_at = utcnow()
    session.commit()
    described = company.description or "The stored sources do not describe the business model."
    return f"Recorded {len(facts)} observed item(s). Description: {described[:240]}"


def attach_repository(opportunity: Opportunity, company: Company, repos: list[dict]) -> str:
    needle = (company.normalized_name or "").lower()
    match = None
    for repo in repos:
        haystack = f"{repo.get('name', '')} {repo.get('description', '')}".lower()
        if needle and needle in haystack:
            match = repo
            break
    if match is None:
        opportunity.oss_name = None
        opportunity.oss_url = None
        opportunity.oss_license = None
        opportunity.oss_relevance = "No public repository in this search named or described this company."
        return opportunity.oss_relevance
    license_name = match.get("license") or "unknown"
    if license_name in {"NOASSERTION", "OTHER", None}:
        relevance = "A public repository name-matches the company, but the license is unclear so it is a reference, not code to copy."
    else:
        relevance = (
            f"The repository name or description matches the company. License: {license_name}. "
            "Use it as a starting point only if that license fits the engagement."
        )
    opportunity.oss_name = match.get("name")
    opportunity.oss_url = match.get("url")
    opportunity.oss_license = license_name
    opportunity.oss_relevance = relevance
    return f"{opportunity.oss_name}: {relevance}"


def score_one(session: Session, opportunity: Opportunity, company: Company, signals: list[Signal]) -> str:
    from app.scoring.persist import record_evaluation

    preserved = opportunity.score
    version = record_evaluation(session, opportunity, preserve_record=True)
    return (
        f"Business signal {version.business_signal_score}/100. "
        f"Technical evidence {version.technical_evidence_score}/100. "
        f"Freelance fit {version.freelance_fit_score}/100. "
        f"Confidence {version.confidence}. Qualification {version.qualification}. "
        f"QA {version.qa_verdict}. Historical composite score {preserved} was not overwritten. "
        f"Sources used: {len(signals)}. Company: {company.name}. "
        "These scores are not a probability of hiring."
    )


def review_strategy(session: Session, opportunity: Opportunity) -> str:
    from app.db import EvaluationVersion

    latest = session.scalar(
        select(EvaluationVersion)
        .where(EvaluationVersion.opportunity_id == opportunity.id, EvaluationVersion.method == "v2_dimensions")
        .order_by(EvaluationVersion.version.desc())
    )
    proposed = None
    if latest and latest.services:
        proposed = latest.services[0].get("proposed_service")
    opportunity.recommended_action = "Awaiting human review"
    session.commit()
    if not proposed:
        return "No service recommended. The stored sources do not state a requirement. Nothing was drafted or sent."
    return f"Recommended service: {proposed}. It is tied to an observed requirement. Nothing was drafted or sent."


def review_quality(session: Session, opportunity: Opportunity, signals: list[Signal]) -> str:
    notes = []
    if not signals:
        notes.append("No source signal is linked.")
    if any(not (signal.source_url or "").startswith("http") for signal in signals):
        notes.append("A source URL is missing or not http(s).")
    if opportunity.technical_need_kind != "inference":
        notes.append("Technical need was not labelled as an inference.")
    if not opportunity.facts:
        notes.append("No observed fact was stored.")
    if not opportunity.score_detail:
        notes.append("No score explanation was stored.")
    opportunity.qa_notes = (
        " ".join(notes)
        if notes
        else "QA checked the stored source URL and the fact/inference split. It did not independently re-fetch every page."
    )
    session.commit()
    return opportunity.qa_notes


def mark_awaiting_review(session: Session, opportunity: Opportunity) -> None:
    _set_status(
        session,
        opportunity,
        "needs_review",
        "Awaiting human review after an internal single-company evaluation. No outreach was sent.",
        "goip-orchestrator",
    )
    opportunity.recommended_action = "Awaiting human review"
    session.commit()


def shortfall(counts: dict, targets: dict) -> dict:
    actual = {
        "discovered": int(counts.get("discovered") or 0),
        "screened": int(counts.get("screened") or 0),
        "researched": int(counts.get("researched") or 0),
        "priority": int(counts.get("high_priority") or 0),
    }
    return {
        key: {"target": int(targets[key if key != "priority" else "priority"]), "actual": actual[key], "shortfall": max(0, int(targets[key if key != "priority" else "priority"]) - actual[key])}
        for key in actual
    }


def opportunity_row(session: Session, opportunity: Opportunity) -> list[object]:
    company = session.get(Company, opportunity.company_id)
    signals = _signals_for(session, opportunity.run_id, opportunity.company_id)
    signal = signals[0] if signals else None
    return [
        opportunity.public_id,
        company.name if company else "",
        company.website if company else "",
        company.industry if company else "",
        company.business_domain or (company.domain if company else ""),
        company.country if company else "",
        company.description if company else "",
        signal.signal_type if signal else "",
        signal.published_at.isoformat() if signal and signal.published_at else "",
        signal.discovered_at.isoformat() if signal else "",
        signal.source_name if signal else "",
        signal.source_url if signal else "",
        signal.evidence if signal else "",
        opportunity.technical_need,
        opportunity.why_approach,
        opportunity.recommended_service,
        opportunity.oss_name,
        opportunity.oss_url,
        opportunity.oss_license,
        opportunity.decision_maker,
        opportunity.profile_url,
        opportunity.outreach_strategy,
        opportunity.why_now,
        opportunity.score,
        opportunity.confidence,
        opportunity.status,
        opportunity.recommended_action,
        opportunity.researched_at.isoformat() if opportunity.researched_at else "",
    ]
