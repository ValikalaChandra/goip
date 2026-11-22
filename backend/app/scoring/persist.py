"""Store a new evaluation version without replacing an earlier composite score."""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import AgentMessage, EvaluationVersion, Opportunity, Signal, utcnow
from app.scoring.evidence import canonical_url, decode_text, quote_supported
from app.scoring.v2 import evaluate, scoring_config_version


def _sources_for(session: Session, opportunity: Opportunity, fetches: dict[str, dict] | None = None) -> list[dict]:
    signals = session.scalars(select(Signal).where(Signal.company_id == opportunity.company_id)).all()
    sources = []
    for signal in signals:
        raw = signal.evidence or signal.summary or signal.title or ""
        fetched = (fetches or {}).get(canonical_url(signal.source_url or "")) or {}
        sources.append(
            {
                "source_id": signal.id,
                "source_url": signal.source_url,
                "source_name": signal.source_name,
                "raw_text": raw,
                "quotation": decode_text(raw)[:400],
                "published_at": signal.published_at.isoformat() if signal.published_at else None,
                "retrieved_at": signal.discovered_at.isoformat() if signal.discovered_at else None,
                "fetch_status": fetched.get("fetch_status") or "not_refetched",
                "signal_type": signal.signal_type,
                "live_text": fetched.get("live_text") or "",
            }
        )
    return sources


def source_fingerprint(sources: list[dict]) -> str:
    payload = [
        (source.get("source_id"), source.get("raw_text"), source.get("published_at"), source.get("fetch_status"))
        for source in sources
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def _agent_snapshot(session: Session, opportunity: Opportunity) -> list[dict]:
    messages = session.scalars(
        select(AgentMessage)
        .where(or_(AgentMessage.run_id == opportunity.run_id, AgentMessage.body.contains(opportunity.public_id)))
        .order_by(AgentMessage.created_at)
    ).all()
    company_name = ""
    if opportunity.company is not None:
        company_name = opportunity.company.name or ""
    needles = [opportunity.public_id]
    if company_name:
        needles.append(company_name)
    chosen = []
    for message in messages:
        body = message.body or ""
        if not any(needle and needle in body for needle in needles):
            continue
        chosen.append(
            {
                "agent": message.agent_name,
                "direction": message.direction,
                "at": message.created_at.isoformat() if message.created_at else None,
                "body": body[:500],
            }
        )
    return chosen[-12:]


def record_if_changed(
    session: Session,
    opportunity: Opportunity,
    *,
    fetches: dict[str, dict] | None = None,
    preserve_record: bool = True,
) -> tuple[EvaluationVersion, bool]:
    """Append a version only when the sources or the scoring configuration changed."""
    sources = _sources_for(session, opportunity, fetches)
    fingerprint = source_fingerprint(sources)
    config_version = scoring_config_version()
    latest = session.scalars(
        select(EvaluationVersion)
        .where(EvaluationVersion.opportunity_id == opportunity.id, EvaluationVersion.method == "v2_dimensions")
        .order_by(EvaluationVersion.version.desc())
    ).first()
    if latest is not None and latest.config_version == config_version and (latest.detail or {}).get("source_fingerprint") == fingerprint:
        return latest, False
    version = record_evaluation(session, opportunity, fetches=fetches, preserve_record=preserve_record)
    return version, True


def record_evaluation(
    session: Session,
    opportunity: Opportunity,
    *,
    fetches: dict[str, dict] | None = None,
    preserve_record: bool = True,
) -> EvaluationVersion:
    """Append a version. The opportunity score, status, and service fields stay as they are."""
    existing = session.scalars(
        select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id).order_by(EvaluationVersion.version)
    ).all()
    if not any(row.method == "v1_composite" for row in existing):
        session.add(
            EvaluationVersion(
                id=str(uuid.uuid4()),
                opportunity_id=opportunity.id,
                version=(existing[-1].version + 1) if existing else 1,
                method="v1_composite",
                legacy_score=opportunity.score,
                confidence=opportunity.confidence or "low",
                qualification="historical",
                qa_verdict="not_run",
                findings=[],
                services=[{"proposed_service": opportunity.recommended_service, "evidence_classification": "historical"}],
                detail={"score_detail": opportunity.score_detail or {}, "note": "Preserved composite score from the earlier qualifier."},
                limitations="This row is the historical composite score. It is not a three-dimension evaluation.",
                previous_evaluation_id=existing[-1].id if existing else None,
                config_version="v1_composite",
                agent_contributions=[],
                created_at=utcnow(),
            )
        )
        session.flush()
        existing = session.scalars(
            select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id).order_by(EvaluationVersion.version)
        ).all()
    sources = _sources_for(session, opportunity, fetches)
    result = evaluate(sources, historical_service=opportunity.recommended_service)
    for source in sources:
        live = source.get("live_text") or ""
        quotation = source.get("quotation") or ""
        if source.get("fetch_status") == "fetched" and quotation and not quote_supported(quotation, live):
            result["findings"].append(
                {
                    "claim": "The stored quotation was not found in the re-fetched page. The live page is not a second source.",
                    "classification": "unknown",
                    "source_id": source.get("source_id") or "",
                    "source_url": source.get("source_url") or "",
                    "quotation": "",
                    "published_at": source.get("published_at"),
                    "retrieved_at": source.get("retrieved_at"),
                    "confidence": "low",
                    "verification_status": "not_on_refetched_page",
                    "fetch_status": "fetched",
                }
            )
            result["limitations"] += " The stored quotation was not found on the re-fetched page."
            if result["qa"]["verdict"] == "pass":
                result["qa"]["verdict"] = "flag"
            result["qa"]["checks"].append(
                {
                    "name": "refetch",
                    "result": "flag",
                    "detail": "Re-fetch succeeded, but the stored quotation is not on that page.",
                }
            )
    version = EvaluationVersion(
        id=str(uuid.uuid4()),
        opportunity_id=opportunity.id,
        version=existing[-1].version + 1,
        method="v2_dimensions",
        legacy_score=opportunity.score,
        business_signal_score=result["business_signal_score"],
        technical_evidence_score=result["technical_evidence_score"],
        freelance_fit_score=result["freelance_fit_score"],
        confidence=result["confidence"],
        qualification=result["qualification"],
        qa_verdict=result["qa"]["verdict"],
        findings=result["findings"],
        services=result["services"],
        detail={
            "explanation": result["explanation"],
            "qa": result["qa"],
            "technical_kind": result["technical_kind"],
            "freelance_kind": result["freelance_kind"],
            "independent_sources": result["independent_sources"],
            "historical_service": opportunity.recommended_service,
            "source_fingerprint": source_fingerprint(sources),
        },
        limitations=result["limitations"],
        previous_evaluation_id=existing[-1].id,
        config_version=scoring_config_version(),
        agent_contributions=_agent_snapshot(session, opportunity),
        created_at=utcnow(),
    )
    session.add(version)
    if not preserve_record:
        opportunity.confidence = result["confidence"]
    session.commit()
    return version
