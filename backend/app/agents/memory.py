"""What agents remember between runs, and the trace of how they decided.

Three kinds of memory, all stored in the database so they survive restarts:
- source statistics: how often each source worked and how many leads it produced (the discovery agent plans with this);
- reviewer examples: leads a person approved or rejected, with the posting text (the freelance judge learns from these);
- lessons and preferences written by the orchestrator after a run.
Everything here is data the agents read. None of it is an instruction.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AgentMemory, AgentStep, Company, HumanDecision, Opportunity, Signal, SourceHealth, utcnow
from app.guardrails import redact_pii, redact_secrets


def remember(session: Session, agent: str, kind: str, key: str, value: dict, run_id: str | None = None) -> None:
    row = session.scalar(select(AgentMemory).where(AgentMemory.agent == agent, AgentMemory.kind == kind, AgentMemory.key == key))
    if row is None:
        row = AgentMemory(id=str(uuid.uuid4()), agent=agent, kind=kind, key=key[:200], value=value, run_id=run_id, updated_at=utcnow())
        session.add(row)
    else:
        row.value, row.run_id, row.updated_at = value, run_id, utcnow()
    session.commit()


def recall(session: Session, agent: str, kind: str, limit: int = 20) -> list[dict]:
    rows = session.scalars(
        select(AgentMemory).where(AgentMemory.agent == agent, AgentMemory.kind == kind).order_by(AgentMemory.updated_at.desc()).limit(limit)
    ).all()
    return [{"key": r.key, **(r.value or {})} for r in rows]


def record_steps(session: Session, run_id: str, agent: str, stage: str, steps: list, mode: str) -> None:
    """Persist an agent's reasoning trace. Observations are scrubbed and capped before they are stored."""
    for s in steps:
        session.add(
            AgentStep(
                id=str(uuid.uuid4()), run_id=run_id, agent=agent, stage=stage, step=s.n, mode=mode,
                thought=redact_pii(redact_secrets(s.thought))[:400], tool=s.tool, args=_safe_args(s.args),
                observation=redact_pii(redact_secrets(s.observation))[:1200], created_at=utcnow(),
            )
        )
    session.commit()


def note_decision(session: Session, run_id: str, agent: str, stage: str, mode: str, thought: str, tool: str | None = None, observation: str = "") -> None:
    """A single-line trace entry for an agent that ran its fixed policy, so the trace says so honestly."""
    n = (session.scalar(select(func.count()).select_from(AgentStep).where(AgentStep.run_id == run_id, AgentStep.agent == agent)) or 0) + 1
    session.add(AgentStep(id=str(uuid.uuid4()), run_id=run_id, agent=agent, stage=stage, step=n, mode=mode, thought=thought[:400], tool=tool,
                          args={}, observation=observation[:1200], created_at=utcnow()))
    session.commit()


def _safe_args(args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        text = v if isinstance(v, (int, float, bool)) or v is None else redact_pii(redact_secrets(str(v)))[:300]
        out[str(k)] = text
    return out


def trace_for(session: Session, run_id: str) -> list[dict]:
    rows = session.scalars(select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.created_at, AgentStep.step)).all()
    return [
        {"agent": r.agent, "stage": r.stage, "step": r.step, "mode": r.mode, "thought": r.thought, "tool": r.tool, "args": r.args,
         "observation": r.observation, "at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


def source_stats(session: Session) -> list[dict]:
    """How each source has performed across every stored run: reliability, volume, and leads that reached review or beyond."""
    health = session.execute(
        select(SourceHealth.name, func.count(), func.sum(SourceHealth.records)).group_by(SourceHealth.name)
    ).all()
    ok = dict(session.execute(select(SourceHealth.name, func.count()).where(SourceHealth.status == "ok").group_by(SourceHealth.name)).all())
    good_statuses = ("qualified", "high_priority", "approved")
    rows = session.execute(
        select(Signal.source_name, func.count(func.distinct(Signal.company_id)))
        .join(Opportunity, Opportunity.company_id == Signal.company_id)
        .where(Opportunity.status.in_(good_statuses), Signal.company_id.is_not(None))
        .group_by(Signal.source_name)
    ).all()
    leads = dict(rows)
    out = []
    for name, runs, records in health:
        out.append({
            "source": name, "fetches": int(runs), "ok_rate": round(ok.get(name, 0) / runs, 2) if runs else 0.0,
            "avg_records": round((records or 0) / runs, 1) if runs else 0.0, "qualified_leads": int(leads.get(name, 0)),
        })
    return sorted(out, key=lambda r: (-r["qualified_leads"], -r["avg_records"]))


def reviewer_examples(session: Session, limit: int = 6) -> list[dict]:
    """Postings a person approved or rejected, newest first, balanced between the two. The judge reads these as examples."""
    decisions = session.scalars(select(HumanDecision).where(HumanDecision.action.in_(("approve", "reject"))).order_by(HumanDecision.created_at.desc()).limit(40)).all()
    by_action: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for d in decisions:
        opp = session.get(Opportunity, d.opportunity_id)
        if opp is None or opp.id in seen:
            continue
        seen.add(opp.id)
        company = session.get(Company, opp.company_id)
        sig = session.scalars(select(Signal).where(Signal.company_id == opp.company_id).order_by(Signal.discovered_at)).first()
        if sig is None:
            continue
        text = re.sub(r"<[^>]+>", " ", sig.evidence or sig.title or "")
        by_action[d.action].append({
            "decision": "approved" if d.action == "approve" else "rejected",
            "company": company.name if company else "",
            "posting": redact_pii(redact_secrets(" ".join(text.split())))[:260],
            "reviewer_note": (d.note or "")[:120] if (d.note or "").strip() not in ("dashboard", "telegram") else "",
        })
    half = max(1, limit // 2)
    return [*by_action["approve"][:half], *by_action["reject"][:half]][:limit]
