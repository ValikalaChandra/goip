from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import JSON

from app.config import DATA_DIR, get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(400), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    business_domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signals: Mapped[list[Signal]] = relationship(back_populates="company")


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("source_url", "identity_hint", name="uq_signal_url_hint"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True, index=True)
    identity_hint: Mapped[str] = mapped_column(String(400), default="")
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(Text)
    parent_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    signal_type: Mapped[str] = mapped_column(String(40), default="other")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified")
    claim_kind: Mapped[str] = mapped_column(String(40), default="observed")
    agent_name: Mapped[str] = mapped_column(String(80), default="goip-discovery")
    company: Mapped[Company | None] = relationship(back_populates="signals")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="running")
    trigger: Mapped[str] = mapped_column(String(40), default="manual")
    targets: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    switch_status: Mapped[str] = mapped_column(String(40), default="not_started")
    telegram_status: Mapped[str] = mapped_column(String(40), default="not_started")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_usage: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceHealth(Base):
    __tablename__ = "source_health"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    parent_domain: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    access_method: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(40), default="unknown")
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("run_id", "company_id", name="uq_opportunity_run_company"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="discovered", index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    technical_need: Mapped[str] = mapped_column(Text, default="")
    technical_need_kind: Mapped[str] = mapped_column(String(40), default="inference")
    why_approach: Mapped[str] = mapped_column(Text, default="")
    recommended_service: Mapped[str] = mapped_column(Text, default="")
    why_now: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    oss_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    oss_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    oss_license: Mapped[str | None] = mapped_column(String(120), nullable=True)
    oss_relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_maker: Mapped[str | None] = mapped_column(String(200), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    outreach_strategy: Mapped[str] = mapped_column(Text, default="")
    qa_notes: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[str] = mapped_column(Text, default="")
    facts: Mapped[list] = mapped_column(JSON, default=list)
    inferences: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    company: Mapped[Company] = relationship()


class EvaluationVersion(Base):
    """A scored reading of one opportunity. Version 1 keeps the historical composite score."""

    __tablename__ = "evaluation_versions"
    __table_args__ = (UniqueConstraint("opportunity_id", "version", name="uq_evaluation_opportunity_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(40))
    legacy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_signal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    technical_evidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    freelance_fit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    qualification: Mapped[str] = mapped_column(String(40), default="unknown")
    qa_verdict: Mapped[str] = mapped_column(String(20), default="flag")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    services: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[str] = mapped_column(Text, default="")
    previous_evaluation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    config_version: Mapped[str] = mapped_column(String(80), default="")
    agent_contributions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(EvaluationVersion, "before_update")
def _evaluation_versions_are_insert_only(_mapper, _connection, _target) -> None:
    raise RuntimeError("evaluation versions are immutable")


@event.listens_for(EvaluationVersion, "before_delete")
def _evaluation_versions_are_not_deleted(_mapper, _connection, _target) -> None:
    raise RuntimeError("evaluation versions are immutable")


class StatusEvent(Base):
    __tablename__ = "status_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(80))
    direction: Mapped[str] = mapped_column(String(20))
    room_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    switch_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delivered: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HumanDecision(Base):
    __tablename__ = "human_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="operator")
    channel: Mapped[str] = mapped_column(String(40), default="dashboard")
    evaluation_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchTask(Base):
    """A request for more research. It does not contact the company."""

    __tablename__ = "research_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    evaluation_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    agents: Mapped[list] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(120), default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SignalReconciliation(Base):
    """Current reconciliation for one signal. History lives in reconciliation_events."""

    __tablename__ = "signal_reconciliations"
    __table_args__ = (UniqueConstraint("signal_id", name="uq_reconciliation_signal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    classification: Mapped[str] = mapped_column(String(40))
    candidate_company_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    rationale: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(40), default="deterministic")
    human_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str] = mapped_column(String(120), default="goip-reconciliation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReconciliationEvent(Base):
    __tablename__ = "reconciliation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    classification: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="goip-reconciliation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    sent: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportFile(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id"), unique=True)
    report_date: Mapped[str] = mapped_column(String(10), index=True)
    csv_path: Mapped[str] = mapped_column(Text)
    json_path: Mapped[str] = mapped_column(Text)
    telegram_status: Mapped[str] = mapped_column(String(40), default="not_sent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str | None = None):
    url = url or get_settings().goip_database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


def make_session_factory(engine=None):
    engine = engine or make_engine()
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def upgrade(engine=None) -> str:
    engine = engine or make_engine()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        if session.get(SchemaMigration, "001") is None:
            session.add(SchemaMigration(version="001"))
            session.commit()
        if session.get(SchemaMigration, "002") is None:
            session.add(SchemaMigration(version="002"))
            session.commit()
        if session.get(SchemaMigration, "003") is None:
            session.add(SchemaMigration(version="003"))
            session.commit()
        if session.get(SchemaMigration, "004") is None:
            session.add(SchemaMigration(version="004"))
            session.commit()
    _ensure_history_columns(engine)
    _link_existing_versions(engine)
    return "004"


def _ensure_history_columns(engine) -> None:
    """Add history columns to databases created before schema 003. Does not drop data."""
    json_type = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    additions = {
        "evaluation_versions": {
            "previous_evaluation_id": "VARCHAR(36)",
            "config_version": "VARCHAR(80)",
            "agent_contributions": json_type,
        },
        "human_decisions": {
            "evaluation_version_id": "VARCHAR(36)",
        },
    }
    inspector = inspect(engine)
    for table, columns in additions.items():
        if table not in inspector.get_table_names():
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name in present:
                continue
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _link_existing_versions(engine) -> None:
    """Fill linkage on rows written before schema 003. Score columns are not changed."""
    from app.scoring.v2 import scoring_config_version

    config_version = scoring_config_version()
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, opportunity_id, version, method, config_version FROM evaluation_versions ORDER BY opportunity_id, version")
        ).all()
        previous: dict[str, str] = {}
        for row in rows:
            prior = previous.get(row.opportunity_id)
            if prior and not _column(connection, row.id, "previous_evaluation_id"):
                connection.execute(
                    text("UPDATE evaluation_versions SET previous_evaluation_id = :prior WHERE id = :id"),
                    {"prior": prior, "id": row.id},
                )
            if row.method == "v1_composite" and (row.config_version or "") != "v1_composite":
                connection.execute(
                    text("UPDATE evaluation_versions SET config_version = 'v1_composite' WHERE id = :id AND method = 'v1_composite'"),
                    {"id": row.id},
                )
            elif row.method != "v1_composite" and not (row.config_version or "").strip():
                connection.execute(
                    text("UPDATE evaluation_versions SET config_version = :config WHERE id = :id AND (config_version IS NULL OR config_version = '')"),
                    {"config": config_version, "id": row.id},
                )
            previous[row.opportunity_id] = row.id
    _backfill_agent_contributions(engine)


def _backfill_agent_contributions(engine) -> None:
    """Copy stored room messages onto versions that have no contribution snapshot."""
    import json

    postgres = engine.dialect.name == "postgresql"
    cast = "CAST(:payload AS json)" if postgres else ":payload"
    empty = "agent_contributions::text = '[]'" if postgres else "agent_contributions = '[]'"
    with engine.begin() as connection:
        versions = connection.execute(
            text(
                """
                SELECT ev.id, ev.agent_contributions, o.public_id, o.run_id
                FROM evaluation_versions ev
                JOIN opportunities o ON o.id = ev.opportunity_id
                """
            )
        ).all()
        for row in versions:
            existing = row.agent_contributions
            if isinstance(existing, str):
                try:
                    existing = json.loads(existing)
                except json.JSONDecodeError:
                    existing = None
            if isinstance(existing, list) and existing:
                continue
            messages = connection.execute(
                text(
                    """
                    SELECT agent_name, direction, body, created_at
                    FROM agent_messages
                    WHERE body LIKE :needle
                    ORDER BY created_at
                    """
                ),
                {"needle": f"%{row.public_id}%"},
            ).all()
            if not messages:
                continue
            payload = [
                {
                    "agent": message.agent_name,
                    "direction": message.direction,
                    "at": message.created_at.isoformat() if hasattr(message.created_at, "isoformat") else str(message.created_at),
                    "body": (message.body or "")[:500],
                    "captured": "schema_003_backfill",
                }
                for message in messages[-12:]
            ]
            connection.execute(
                text(
                    f"UPDATE evaluation_versions SET agent_contributions = {cast} "
                    f"WHERE id = :id AND (agent_contributions IS NULL OR {empty})"
                ),
                {"payload": json.dumps(payload), "id": row.id},
            )


def _column(connection, row_id: str, name: str):
    return connection.execute(text(f"SELECT {name} FROM evaluation_versions WHERE id = :id"), {"id": row_id}).scalar()
