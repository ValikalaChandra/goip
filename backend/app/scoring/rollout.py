"""In-memory qualification preview. It does not write evaluations or change status."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Company, Opportunity, Signal
from app.scoring.persist import _sources_for
from app.scoring.v2 import evaluate, scoring_config_version


def preview_opportunity(session: Session, opportunity: Opportunity) -> dict:
    company = session.get(Company, opportunity.company_id)
    signals = session.scalars(select(Signal).where(Signal.company_id == opportunity.company_id)).all()
    sources = _sources_for(session, opportunity)
    result = evaluate(sources, historical_service=opportunity.recommended_service)
    return {
        "public_id": opportunity.public_id,
        "company": company.name if company else "",
        "status": opportunity.status,
        "historical_score": opportunity.score,
        "historical_service": opportunity.recommended_service,
        "sources": len(signals),
        "business_signal_score": result["business_signal_score"],
        "technical_evidence_score": result["technical_evidence_score"],
        "freelance_fit_score": result["freelance_fit_score"],
        "confidence": result["confidence"],
        "qualification": result["qualification"],
        "qa_verdict": result["qa"]["verdict"],
        "proposed_service": (result["services"] or [{}])[0].get("proposed_service"),
        "config_version": scoring_config_version(),
    }


def anomaly(row: dict) -> list[str]:
    notes = []
    historical = row["historical_score"] or 0
    if historical >= 70 and row["freelance_fit_score"] == 0:
        notes.append("historical composite is high while freelance fit is 0")
    if row["status"] == "high_priority" and row["qualification"] != "freelance_evidence":
        notes.append("high_priority status is not backed by an external contracting statement")
    if row["qa_verdict"] == "reject":
        notes.append("QA rejects the current reading")
    if row["sources"] < 2:
        notes.append("fewer than two stored sources")
    if row["proposed_service"] and row["qa_verdict"] == "reject":
        notes.append("a service is proposed while QA rejects the reading")
    return notes
