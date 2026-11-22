"""Signal-to-company resolution. Ambiguous headlines are not attached."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Company, ReconciliationEvent, Signal, SignalReconciliation, utcnow
from app.discovery.extract import extract_company_name, is_publisher, normalize_name, registrable_domain

CLASSIFICATIONS = (
    "confirmed_match",
    "probable_match",
    "ambiguous_match",
    "unmatched",
    "duplicate_signal",
)


def classify_signal(
    *,
    title: str,
    identity_hint: str,
    source_url: str,
    companies: list[dict],
    linked_urls: set[str],
) -> dict:
    """Classify one signal. A name mentioned in a headline is not a confirmed identity."""
    if source_url and source_url in linked_urls:
        return {
            "classification": "duplicate_signal",
            "candidate_company_id": None,
            "confidence": "high",
            "rationale": "This source URL is already stored on a linked signal. The unlinked row is a duplicate record, not a second company.",
        }
    text = normalize_name(f"{title} {identity_hint}")
    extracted = extract_company_name(title or "")
    extracted_norm = normalize_name(extracted or "")
    host = registrable_domain(source_url)
    domain_hits = []
    if host and not is_publisher(host):
        domain_hits = [company for company in companies if company.get("domain") and company["domain"] == host]
    if len(domain_hits) == 1:
        return {
            "classification": "confirmed_match",
            "candidate_company_id": domain_hits[0]["id"],
            "confidence": "high",
            "rationale": f"The source host {host} matches the company domain. Publisher hosts are excluded.",
        }
    if len(domain_hits) > 1:
        return {
            "classification": "ambiguous_match",
            "candidate_company_id": None,
            "confidence": "low",
            "rationale": f"The host {host} matches more than one company domain.",
        }
    name_hits = []
    for company in companies:
        norm = company.get("normalized_name") or ""
        if len(norm) < 4:
            continue
        if re.search(rf"\b{re.escape(norm)}\b", text):
            name_hits.append(company)
    if len(name_hits) == 1 and extracted_norm and extracted_norm == name_hits[0]["normalized_name"]:
        return {
            "classification": "probable_match",
            "candidate_company_id": name_hits[0]["id"],
            "confidence": "medium",
            "rationale": "The extracted name matches one company, and the source host does not confirm it. It is not linked automatically.",
        }
    if name_hits:
        names = ", ".join(company["name"] for company in name_hits[:3])
        return {
            "classification": "ambiguous_match",
            "candidate_company_id": name_hits[0]["id"] if len(name_hits) == 1 else None,
            "confidence": "low",
            "rationale": f"The headline mentions {names}. A mention is not an identity match, so the signal stays unassigned.",
        }
    return {
        "classification": "unmatched",
        "candidate_company_id": None,
        "confidence": "low",
        "rationale": "No company name survived extraction, and the source host is not a stored company domain. The signal stays unassigned.",
    }


def _companies(session: Session) -> list[dict]:
    rows = []
    for company in session.scalars(select(Company)).all():
        rows.append(
            {
                "id": company.id,
                "name": company.name,
                "normalized_name": company.normalized_name,
                "domain": (company.domain or "").lower().removeprefix("www.") or None,
            }
        )
    return rows


def inspect_unlinked(session: Session) -> list[dict]:
    companies = _companies(session)
    linked_urls = {
        row.source_url
        for row in session.scalars(select(Signal).where(Signal.company_id.is_not(None))).all()
        if row.source_url
    }
    findings = []
    for signal in session.scalars(select(Signal).where(Signal.company_id.is_(None)).order_by(Signal.discovered_at)).all():
        result = classify_signal(
            title=signal.title or "",
            identity_hint=signal.identity_hint or "",
            source_url=signal.source_url or "",
            companies=companies,
            linked_urls=linked_urls,
        )
        findings.append({"signal": signal, **result})
    return findings


def record_inspection(session: Session, actor: str = "goip-reconciliation") -> dict:
    """Insert a classification for each unlinked signal that does not have one. Does not set company_id."""
    created = 0
    skipped = 0
    for finding in inspect_unlinked(session):
        signal = finding["signal"]
        existing = session.scalar(select(SignalReconciliation).where(SignalReconciliation.signal_id == signal.id))
        if existing is not None:
            skipped += 1
            continue
        if finding["classification"] == "confirmed_match" and finding["candidate_company_id"]:
            signal.company_id = finding["candidate_company_id"]
        session.add(
            SignalReconciliation(
                id=str(uuid.uuid4()),
                signal_id=signal.id,
                classification=finding["classification"],
                candidate_company_id=finding["candidate_company_id"],
                confidence=finding["confidence"],
                rationale=finding["rationale"],
                method="deterministic",
                actor=actor,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        session.add(
            ReconciliationEvent(
                id=str(uuid.uuid4()),
                signal_id=signal.id,
                action="classified",
                classification=finding["classification"],
                note=finding["rationale"],
                actor=actor,
                created_at=utcnow(),
            )
        )
        created += 1
    session.commit()
    return {"created": created, "skipped": skipped}


def apply_human_action(
    session: Session,
    signal_id: str,
    action: str,
    *,
    company_id: str | None = None,
    note: str = "",
    actor: str = "operator",
) -> SignalReconciliation:
    allowed = {"confirm", "reject", "duplicate", "unassigned", "request_research"}
    if action not in allowed:
        raise ValueError(f"unsupported reconciliation action: {action}")
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise LookupError(signal_id)
    row = session.scalar(select(SignalReconciliation).where(SignalReconciliation.signal_id == signal_id))
    if row is None:
        row = SignalReconciliation(
            id=str(uuid.uuid4()),
            signal_id=signal_id,
            classification="unmatched",
            confidence="low",
            rationale="",
            method="human",
            created_at=utcnow(),
        )
        session.add(row)
    if action == "confirm":
        if not company_id or session.get(Company, company_id) is None:
            raise ValueError("confirm requires a stored company")
        signal.company_id = company_id
        row.classification = "confirmed_match"
        row.candidate_company_id = company_id
        row.confidence = "high"
        row.rationale = note or "A person confirmed this match."
    elif action == "reject":
        row.classification = "unmatched"
        row.candidate_company_id = None
        row.rationale = note or "A person rejected the suggested match."
    elif action == "duplicate":
        row.classification = "duplicate_signal"
        row.rationale = note or "A person marked this signal as a duplicate. The row was not deleted."
    elif action == "unassigned":
        row.classification = "unmatched"
        row.candidate_company_id = None
        row.rationale = note or "A person left this signal unassigned."
    else:
        row.rationale = note or "Additional research requested. The signal stays unassigned."
    row.human_action = action
    row.method = "human"
    row.actor = actor
    row.updated_at = utcnow()
    session.add(
        ReconciliationEvent(
            id=str(uuid.uuid4()),
            signal_id=signal_id,
            action=action,
            classification=row.classification,
            note=row.rationale,
            actor=actor,
            created_at=utcnow(),
        )
    )
    session.commit()
    return row
