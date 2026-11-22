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


CLASS_MEANING = {
    "confirmed_match": "The source is published on the company's own website, so the signal belongs to that company.",
    "probable_match": "The headline names exactly one stored company, but nothing on the page proves it is the same one. A person has to confirm.",
    "ambiguous_match": "The headline mentions a stored company, or the host fits several, but a mention is not an identity. It stays unassigned.",
    "unmatched": "No company could be identified from the headline or the host. It stays unassigned.",
    "duplicate_signal": "This exact source is already stored against a company. This row is a duplicate record, not a new company.",
}


def _check(key: str, label: str, status: str, detail: str) -> dict:
    """status: pass (supports a match), fail (blocks one), info (neutral fact), warn (weakens one)."""
    return {"key": key, "label": label, "status": status, "detail": detail}


def classify_signal(
    *,
    title: str,
    identity_hint: str,
    source_url: str,
    companies: list[dict],
    linked_urls: set[str],
) -> dict:
    """Classify one signal. A name mentioned in a headline is not a confirmed identity.

    Returns the classification plus a `reasoning` block: every check that was run, the candidate and the basis
    for it, why the class is not higher, and what a person would need to verify.
    """
    checks: list[dict] = []
    host = registrable_domain(source_url)
    publisher = bool(host and is_publisher(host))

    def done(classification, candidate_id, confidence, rationale, *, basis=None, alternatives=(), higher=None, confirm=None, extracted=None):
        by_id = {c["id"]: c for c in companies}
        cand = by_id.get(candidate_id) if candidate_id else None
        reasoning = {
            "headline": rationale,
            "checks": checks,
            "class_meaning": CLASS_MEANING[classification],
            "candidate": {"id": cand["id"], "name": cand["name"], "domain": cand.get("domain"), "basis": basis} if cand else None,
            "alternatives": [{"id": c["id"], "name": c["name"], "domain": c.get("domain")} for c in alternatives],
            "why_not_higher": higher,
            "to_confirm": confirm,
            "extracted_name": extracted,
            "source_host": host,
            "host_is_publisher": publisher,
        }
        return {
            "classification": classification,
            "candidate_company_id": candidate_id,
            "confidence": confidence,
            "rationale": rationale,
            "reasoning": reasoning,
        }

    if source_url and source_url in linked_urls:
        checks.append(_check("duplicate", "Source already stored?", "fail", "The same source URL is already stored on a signal that is linked to a company."))
        return done(
            "duplicate_signal", None, "high",
            "This source URL is already stored on a linked signal. The unlinked row is a duplicate record, not a second company.",
            higher=None, confirm="Nothing to verify. Mark it as a duplicate to clear it from the queue.",
        )
    checks.append(_check("duplicate", "Source already stored?", "pass", "No linked signal uses this exact URL, so this is not a duplicate."))

    text = normalize_name(f"{title} {identity_hint}")
    extracted = extract_company_name(title or "")
    extracted_norm = normalize_name(extracted or "")
    if extracted:
        checks.append(_check("extracted", "Company name in the headline", "pass", f"Extracted \u201c{extracted}\u201d from the headline using the \u201cX raises / launches / Show HN: X\u201d patterns."))
    else:
        checks.append(_check("extracted", "Company name in the headline", "fail", "No company name could be extracted. The headline does not follow a pattern that names a subject."))

    if not host:
        checks.append(_check("host", "Source website", "warn", "The source has no usable host, so it cannot identify a company."))
    elif publisher:
        checks.append(_check("host", "Source website", "warn", f"{host} is a news or community publisher. Where a story is published says nothing about who it is about."))
    else:
        checks.append(_check("host", "Source website", "info", f"{host} is not a known publisher, so it could be the company's own site."))

    domain_hits = []
    if host and not publisher:
        domain_hits = [c for c in companies if c.get("domain") and c["domain"] == host]
    if host and not publisher:
        if len(domain_hits) == 1:
            checks.append(_check("domain", "Matches a stored company domain", "pass", f"{host} is the stored domain of {domain_hits[0]['name']}."))
        elif len(domain_hits) > 1:
            checks.append(_check("domain", "Matches a stored company domain", "fail", f"{host} is stored for {len(domain_hits)} companies, so it cannot pick one."))
        else:
            checks.append(_check("domain", "Matches a stored company domain", "fail", f"No stored company has the domain {host}."))
    else:
        checks.append(_check("domain", "Matches a stored company domain", "info", "Skipped: a publisher host cannot be a company domain."))

    if len(domain_hits) == 1:
        return done(
            "confirmed_match", domain_hits[0]["id"], "high",
            f"The source host {host} matches the company domain. Publisher hosts are excluded.",
            basis="domain",
            confirm="Already confirmed by the domain. Review it only if the company name looks wrong.",
            extracted=extracted,
        )
    if len(domain_hits) > 1:
        return done(
            "ambiguous_match", None, "low",
            f"The host {host} matches more than one company domain.",
            alternatives=domain_hits,
            higher="Several companies share this domain, so the host cannot choose between them.",
            confirm="Pick the right company from the candidates and confirm it.",
            extracted=extracted,
        )

    name_hits = []
    for company in companies:
        norm = company.get("normalized_name") or ""
        if len(norm) < 4:
            continue
        if re.search(rf"\b{re.escape(norm)}\b", text):
            name_hits.append(company)
    if name_hits:
        listed = ", ".join(c["name"] for c in name_hits[:3])
        checks.append(_check("name", "Stored company named in the headline", "pass" if len(name_hits) == 1 else "warn",
                             f"The headline contains the stored name {listed}." if len(name_hits) == 1 else f"The headline contains {len(name_hits)} stored names: {listed}."))
    else:
        checks.append(_check("name", "Stored company named in the headline", "fail", "None of the stored company names appears in the headline."))

    if len(name_hits) == 1 and extracted_norm and extracted_norm == name_hits[0]["normalized_name"]:
        checks.append(_check("agree", "Extracted name equals the stored name", "pass", f"\u201c{extracted}\u201d and \u201c{name_hits[0]['name']}\u201d normalise to the same name."))
        return done(
            "probable_match", name_hits[0]["id"], "medium",
            "The extracted name matches one company, and the source host does not confirm it. It is not linked automatically.",
            basis="name",
            higher=("A name match is not an identity match: different companies share names, and the host is a publisher, "
                    "so the page does not prove which one this is." if publisher else
                    "The host is not a stored company domain, so only the name supports the match."),
            confirm=f"Open the source and check that the company in the story is {name_hits[0]['name']}"
                    + (f" ({name_hits[0]['domain']})" if name_hits[0].get("domain") else "") + ". If it is, confirm; if not, reject.",
            extracted=extracted,
        )
    if name_hits:
        checks.append(_check("agree", "Extracted name equals the stored name", "fail" if extracted else "info",
                             "The extracted name does not equal the stored name, so this is only a mention." if extracted else "No extracted name to compare."))
        names = ", ".join(company["name"] for company in name_hits[:3])
        one = len(name_hits) == 1
        return done(
            "ambiguous_match", name_hits[0]["id"] if one else None, "low",
            f"The headline mentions {names}. A mention is not an identity match, so the signal stays unassigned.",
            basis="name" if one else None,
            alternatives=name_hits if not one else (),
            higher="The company is named in the text but is not the clear subject of the story (the subject extraction disagrees or is missing).",
            confirm="Read the source. If the story is about this company, confirm it; if it only mentions it, reject.",
            extracted=extracted,
        )
    return done(
        "unmatched", None, "low",
        "No company name survived extraction, and the source host is not a stored company domain. The signal stays unassigned.",
        higher="There is nothing to match on: no extracted name, no stored name in the text, no company domain.",
        confirm="Request research, or read the source and confirm a company if one is clearly the subject.",
        extracted=extracted,
    )


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
