"""Human review. Approval records a decision. It does not send outreach."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import EvaluationVersion, HumanDecision, Opportunity, ResearchTask, StatusEvent, utcnow

RESEARCH_AGENTS = (
    "goip-company-research",
    "goip-technical-intelligence",
    "goip-discovery",
)

_ACTIONS = {
    "approve": (
        "approved",
        "Approved for further consideration. No outreach was sent.",
    ),
    "reject": (
        "rejected",
        "Rejected. The research history is retained.",
    ),
    "request_research": (
        "research_requested",
        "Additional research requested. No outreach was sent.",
    ),
    "needs_review": (
        "needs_review",
        "Returned to review. No outreach was sent.",
    ),
}


def latest_evaluation(session: Session, opportunity_id: str) -> EvaluationVersion | None:
    return session.scalars(
        select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity_id).order_by(EvaluationVersion.version.desc())
    ).first()


def apply_review(
    session: Session,
    opportunity: Opportunity,
    action: str,
    note: str = "",
    *,
    actor: str = "operator",
    channel: str = "dashboard",
) -> dict:
    if action not in _ACTIONS:
        raise ValueError(f"unsupported review action: {action}")
    status, default_reason = _ACTIONS[action]
    reason = (note or "").strip() or default_reason
    current = latest_evaluation(session, opportunity.id)
    previous = opportunity.status
    from app.guardrails import check_status_transition, require

    require(check_status_transition(previous, status, actor))
    opportunity.status = status
    opportunity.status_reason = reason
    if action == "approve":
        opportunity.recommended_action = "Approved for further consideration. Outreach is a separate draft and is not sent."
    elif action == "reject":
        opportunity.recommended_action = "Rejected. History retained. No outreach."
    elif action == "request_research":
        opportunity.recommended_action = "Additional research requested."
    session.add(
        StatusEvent(
            id=str(uuid.uuid4()),
            opportunity_id=opportunity.id,
            from_status=previous,
            to_status=status,
            reason=reason,
            actor=actor,
            created_at=utcnow(),
        )
    )
    decision = HumanDecision(
        id=str(uuid.uuid4()),
        opportunity_id=opportunity.id,
        action=action,
        note=reason,
        actor=actor,
        channel=channel,
        evaluation_version_id=current.id if current else None,
        created_at=utcnow(),
    )
    session.add(decision)
    task_id = None
    if action == "request_research":
        task = ResearchTask(
            id=str(uuid.uuid4()),
            opportunity_id=opportunity.id,
            evaluation_version_id=current.id if current else None,
            note=reason,
            status="open",
            agents=list(RESEARCH_AGENTS),
            actor=actor,
            created_at=utcnow(),
        )
        session.add(task)
        task_id = task.id
    session.commit()
    return {
        "status": opportunity.status,
        "decision_id": decision.id,
        "evaluation_version_id": current.id if current else None,
        "research_task_id": task_id,
        "outreach_sent": False,
    }
