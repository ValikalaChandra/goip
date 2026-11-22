import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GOIP_SWITCH_ENABLED", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.exports as exports
import app.graph.build as build
from app.db import Base, PipelineRun
from app.guardrails import GuardrailViolation
from app.agents.toolbox import ToolBox
from app.guardrails import Budget


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _stub(monkeypatch, raw_items=3, calls=None):
    calls = calls if calls is not None else []

    async def discover(session, http, settings, run):
        calls.append("discover")
        return {"company_ids": [], "counts": {"raw_items": raw_items, "discovered": 0, "screened": 0}}

    async def research(session, http, settings, run, ids):
        calls.append("research")
        return {"company_ids": []}

    async def search(session, http, run):
        calls.append("technical")
        return {"attached": 0}

    monkeypatch.setattr(build, "discover", discover)
    monkeypatch.setattr(build, "research", research)
    monkeypatch.setattr(build, "_search_and_attach", search)
    monkeypatch.setattr(build, "qualify", lambda s, r: calls.append("qualify") or {"qualified": 0})
    monkeypatch.setattr(build, "quality_check", lambda s, r: calls.append("qa") or {"qa_flags": 0})
    return calls


async def test_clean_run_completes_in_order(factory, monkeypatch):
    calls = _stub(monkeypatch)
    run_id = await build.run_graph(factory, None, "test")
    with factory() as s:
        run = s.get(PipelineRun, run_id)
        assert run.status == "completed", run.error
    assert calls == ["discover", "research", "technical", "qualify", "qa"]


async def test_empty_sources_halt_the_run_before_later_stages(factory, monkeypatch):
    calls = _stub(monkeypatch, raw_items=0)
    run_id = await build.run_graph(factory, None, "test")
    with factory() as s:
        run = s.get(PipelineRun, run_id)
        assert run.status == "partial"
        assert run.error == "discover:no_sources_returned"
    # discovery retries once (two-step loop) before the guardrail halts the run; no later stage runs
    assert calls == ["discover", "discover"]


async def test_toolbox_blocks_forbidden_and_unlisted_tools():
    box = ToolBox("goip-strategy", Budget(), {"send_email": lambda: "sent"})
    with pytest.raises(GuardrailViolation):
        await box.call("send_email")
    box = ToolBox("goip-qualification", Budget(), {"score_all": lambda: "ok"})
    assert await box.call("score_all") == "ok"
    with pytest.raises(GuardrailViolation):
        await box.call("audit_all")


async def test_budget_overrun_marks_run_partial(factory, monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setattr(build, "Budget", lambda: Budget(max_tool_calls=1))
    run_id = await build.run_graph(factory, None, "test")
    with factory() as s:
        run = s.get(PipelineRun, run_id)
        assert run.status == "partial" and run.error.endswith("tool_call_budget")
