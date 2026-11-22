import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.db import (
    Company,
    EvaluationVersion,
    HumanDecision,
    Opportunity,
    OutreachDraft,
    PipelineRun,
    ResearchTask,
    Signal,
    make_engine,
    make_session_factory,
    upgrade,
    utcnow,
)
from app.review import apply_review
from app.scoring.persist import record_evaluation, record_if_changed
from app.scoring.rollout import preview_opportunity


def _session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    upgrade(engine)
    return make_session_factory(engine)()


def _lead(session, evidence: str, score: int = 76):
    company = Company(
        id=str(uuid.uuid4()),
        identity_key=str(uuid.uuid4()),
        name="Example Co",
        normalized_name="example",
        created_at=utcnow(),
    )
    run = PipelineRun(id=str(uuid.uuid4()), status="completed", trigger="test", targets={}, counts={}, started_at=utcnow())
    opportunity = Opportunity(
        id=str(uuid.uuid4()),
        public_id="GTEST1234",
        run_id=run.id,
        company_id=company.id,
        status="needs_review",
        score=score,
        confidence="medium",
        score_detail={},
        recommended_service="LLM integration and RAG",
        facts=[],
        inferences=[],
        recommendations=[],
    )
    signal = Signal(
        id=str(uuid.uuid4()),
        company_id=company.id,
        run_id=run.id,
        identity_hint="example",
        source_name="Hacker News",
        source_url="https://news.ycombinator.com/item?id=1",
        category="product",
        title="Show HN: Example",
        summary="Launch",
        evidence=evidence,
        signal_type="product",
        published_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        discovered_at=utcnow(),
    )
    session.add_all([company, run, opportunity, signal])
    session.commit()
    return opportunity


def test_versions_link_and_do_not_change():
    session = _session()
    opportunity = _lead(session, "Our team is excited to launch Example this week. We&#x27;ve shipped a workspace.")
    first = record_evaluation(session, opportunity, preserve_record=True)
    assert first.previous_evaluation_id
    assert first.config_version.startswith("scoring_v2-")
    again, wrote = record_if_changed(session, opportunity, preserve_record=True)
    assert wrote is False
    assert again.id == first.id
    count = session.scalar(select(func.count()).select_from(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id))
    assert count == 2
    session.refresh(opportunity)
    assert opportunity.score == 76
    first.confidence = "high"
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_review_does_not_send_or_erase_history():
    session = _session()
    opportunity = _lead(session, "Our team is excited to launch Example this week.")
    record_evaluation(session, opportunity, preserve_record=True)
    before = session.scalar(select(func.count()).select_from(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id))
    approved = apply_review(session, opportunity, "approve", "Looks worth a second reading.", actor="operator", channel="dashboard")
    assert approved["outreach_sent"] is False
    assert approved["status"] == "approved"
    drafts = session.scalar(select(func.count()).select_from(OutreachDraft).where(OutreachDraft.opportunity_id == opportunity.id))
    assert drafts == 0
    rejected = apply_review(session, opportunity, "reject", "Not a fit.", actor="operator", channel="dashboard")
    assert rejected["status"] == "rejected"
    after = session.scalar(select(func.count()).select_from(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity.id))
    assert after == before
    decisions = session.scalars(select(HumanDecision).where(HumanDecision.opportunity_id == opportunity.id)).all()
    assert {row.action for row in decisions} == {"approve", "reject"}
    assert all(row.evaluation_version_id for row in decisions)
    session.refresh(opportunity)
    assert opportunity.score == 76


def test_research_request_is_a_task():
    session = _session()
    opportunity = _lead(session, "Our team is excited to launch Example this week.")
    record_evaluation(session, opportunity, preserve_record=True)
    result = apply_review(session, opportunity, "request_research", "Need a second source.", channel="dashboard")
    assert result["research_task_id"]
    task = session.get(ResearchTask, result["research_task_id"])
    assert task.status == "open"
    assert "goip-company-research" in task.agents
    assert "goip-technical-intelligence" in task.agents
    session.refresh(opportunity)
    assert opportunity.status == "research_requested"
    drafts = session.scalar(select(func.count()).select_from(OutreachDraft))
    assert drafts == 0


def test_preview_does_not_write():
    session = _session()
    opportunity = _lead(session, "Our team is excited to launch Example this week.")
    before_status = opportunity.status
    row = preview_opportunity(session, opportunity)
    session.refresh(opportunity)
    assert opportunity.status == before_status
    assert opportunity.score == 76
    stored = session.scalar(select(func.count()).select_from(EvaluationVersion))
    assert stored == 0
    assert row["freelance_fit_score"] == 0
    assert row["qualification"] == "research_candidate"
    assert row["historical_score"] == 76
