"""Run the REAL model through the planner, the freelance judge and the research agent on sample postings.

Use it once OpenRouter has credit. It uses an in-memory database and makes no calls except to OpenRouter, so it cannot
touch your leads. It prints what the model decided, what the guardrails accepted and what they rejected.

    cd goip/backend && PYTHONPATH=. uv run python scripts/agent_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.specialists as sp
from app.agents.llm import OpenRouterLLM
from app.agents.orchestrator import plan_run
from app.config import get_settings
from app.db import Base, Company, Opportunity, PipelineRun, Signal, utcnow
from app.guardrails import Budget
from app.integrations.openrouter import LLM_MESSAGES, llm_health

POSTINGS = {
    "Acme Payments": ("a company, no keyword", "Acme Payments | Backend | We are looking for an experienced engineer to build our new ledger API over a three month engagement."),
    "Blackbird": ("a company, explicit", "Blackbird | Dev Shop | Remote | Contract. We build web and mobile products and work with lots of freelancers."),
    "Maya Dev": ("a job-seeker", "Maya Dev | Location: Estonia Willing to relocate: No Technologies: React Part-time/Freelance: Yes available for contract work."),
    "BigCo": ("a full-time role", "BigCo | Staff Engineer | Full-time, permanent, Berlin. Competitive salary and equity."),
}


async def main() -> int:
    settings = get_settings()
    if settings.goip_use_system_certs:  # same opt-in as the app, for networks with a TLS-inspecting proxy
        import truststore

        truststore.inject_into_ssl()
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
    session.add(PipelineRun(id="smoke", status="running", counts={}, started_at=utcnow()))
    for i, (name, (_, text)) in enumerate(POSTINGS.items()):
        session.add(Company(id=f"c{i}", identity_key=f"name:{i}", name=name, normalized_name=name.lower(), created_at=utcnow()))
        session.add(Opportunity(id=f"o{i}", public_id=f"GSMOKE{i:03d}", run_id="smoke", company_id=f"c{i}", status="researching"))
        session.add(Signal(id=f"s{i}", company_id=f"c{i}", run_id="smoke", identity_hint=name, source_name="smoke", source_url=f"https://example.com/{i}",
                           category="hiring", title=text.split("|")[0], evidence=text, signal_type="hiring", discovered_at=utcnow()))
    session.commit()
    async with httpx.AsyncClient() as http:
        budget = Budget()
        llm = OpenRouterLLM(http, settings, budget)
        t = SimpleNamespace(session=session, http=http, settings=settings, run_id="smoke", budget=budget, llm=llm, run=session.get(PipelineRun, "smoke"), plan=None)

        print("== orchestrator plan ==")
        plan = await plan_run(t, "find freelance fintech engineering jobs")
        print(f"mode={plan.mode} focus={plan.focus} prefer={plan.prefer} reason={plan.reason}\n  {plan.notes}")
        if plan.mode != "llm":
            state = llm_health()
            print("\nThe model did not answer:", LLM_MESSAGES.get(state.get("reason"), state))
            return 1

        print("\n== freelance judge (expected: Acme yes, Blackbird yes, Maya no, BigCo no) ==")
        result, stored = await sp.agentic_judge(t)
        print(f"mode={result.mode} verdicts stored={stored} steps={len(result.steps)}")
        for i, (name, (kind, _)) in enumerate(POSTINGS.items()):
            v = session.get(Signal, f"s{i}").classification
            got = "no verdict stored" if not v else f"offer={v['is_freelance_opportunity']} poster={v['poster']} engagement={v['engagement']} ({v['confidence']})"
            print(f"  {name:14} [{kind}] -> {got}")
        for s in result.steps:
            if not s.ok:
                print("  guardrail rejected a step:", s.observation[:140])

        print("\n== research agent on Acme Payments ==")
        sigs = [session.get(Signal, "s0")]
        r = await sp.agentic_research(t, session.get(Company, "c0"), sigs, "Acme Payments\n" + POSTINGS["Acme Payments"][1])
        print(f"mode={r.mode} steps={len(r.steps)}")
        print(json.dumps(r.final, indent=2) if r.final else f"no valid answer: {r.reason}")
        print(f"\nmodel calls used: {budget.llm_calls}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
