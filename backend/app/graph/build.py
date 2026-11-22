"""LangGraph orchestrator. The graph, not the chat room, is the control plane.

Switch receives a plain room post for every step (so the transcript stays readable) but is never
asked to run a stage. If Switch is down the run still completes.
"""

from __future__ import annotations

import asyncio
import logging
import operator
import uuid
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from app.agents.team import SPECS, Team
from app.agents.toolbox import ToolBox
from app.config import Settings, get_settings, load_runtime
from app.db import PipelineRun, utcnow
from app.discovery.sources import fetch_github
from app.guardrails import AGENT_TOOLS, Budget, BudgetExceeded, GuardrailViolation
from app.observability import traced
from app.pipeline import attach_github, discover, qualify, quality_check, research

log = logging.getLogger("goip.graph")

STAGES = ["discover", "research", "technical", "qualify", "strategy", "qa"]
STAGE_TIMEOUTS = {"discover": 300, "research": 900, "technical": 180, "qualify": 120, "strategy": 60, "qa": 120}


class RunState(TypedDict, total=False):
    run_id: str
    company_ids: list[str]
    halted: str
    log: Annotated[list[dict], operator.add]


class _Context:
    def __init__(self, team: Team, runtime: Any, session: Any):
        self.team = team
        self.runtime = runtime
        self.session = session


_CONTEXTS: dict[str, _Context] = {}


async def _search_and_attach(session, http, run) -> dict:
    repos, error = await fetch_github(http, int(load_runtime()["fetch_caps"]["github_hits"]))
    return {**attach_github(session, run, repos), "error": error}


def _boxes(budget: Budget) -> dict[str, ToolBox]:
    def box(stage: str, tools: dict) -> ToolBox:
        return ToolBox(SPECS[stage].name, budget, tools)

    return {
        "discover": box("discover", {"fetch_and_group": discover}),
        "research": box("research", {"llm_extract_all": research}),
        "technical": box("technical", {"search_and_attach": _search_and_attach}),
        "qualify": box("qualify", {"score_all": qualify}),
        "strategy": box("strategy", {}),
        "qa": box("qa", {"audit_all": quality_check}),
    }


async def _mirror(ctx: _Context, agent: str, text: str) -> None:
    runtime = ctx.runtime
    if runtime is None or not runtime.connected or not runtime.room.get("id"):
        return
    try:
        await runtime._broadcast(agent, text)
    except Exception:  # noqa: BLE001 - the room is a mirror, never a dependency
        log.warning("room mirror failed for %s", agent)


def _node(stage: str):
    spec = SPECS[stage]

    @traced(f"agent:{spec.name}", run_type="chain", stage=stage)
    async def node(state: RunState) -> dict:
        if state.get("halted"):
            return {}
        ctx = _CONTEXTS[state["run_id"]]
        try:
            result, update = await asyncio.wait_for(getattr(ctx.team, stage)(dict(state)), STAGE_TIMEOUTS[stage])
        except asyncio.TimeoutError:
            await _mirror(ctx, spec.name, f"{stage} timed out. The run is partial.")
            return {"halted": f"{stage}:stage_timeout", "log": [{"stage": stage, "ok": False, "why": "stage_timeout"}]}
        except GuardrailViolation as exc:
            v = exc.verdict
            await _mirror(ctx, spec.name, f"Guardrail stopped {stage}: {v.layer}/{v.rule}. {v.detail[:200]}")
            return {"halted": f"{stage}:{v.rule}", "log": [{"stage": stage, "ok": False, "why": f"{v.layer}/{v.rule}"}]}
        entry = {"stage": stage, "ok": result.ok, "steps": result.steps, "summary": result.summary[:300]}
        await _mirror(ctx, spec.name, f"{stage}: {result.summary[:500]}")
        if not result.ok:
            failed = next((v for v in result.verdicts if v.blocked), None)
            rule = failed.rule if failed else "verify_failed"
            await _mirror(ctx, spec.name, f"Self-check failed for {stage}: {rule}. {(failed.detail if failed else '')[:200]}")
            entry["why"] = rule
            return {"halted": f"{stage}:{rule}", "log": [entry]}
        return {**update, "log": [entry]}

    return node


async def _halt(state: RunState) -> dict:
    ctx = _CONTEXTS[state["run_id"]]
    run = ctx.session.get(PipelineRun, state["run_id"])
    run.status = "partial"
    run.switch_status = "connected" if ctx.runtime and ctx.runtime.connected else "offline"
    run.error = state.get("halted", "halted")[:500]
    run.finished_at = utcnow()
    ctx.session.commit()
    await _mirror(ctx, "goip-orchestrator", f"Run {state['run_id']} stopped as partial: {run.error}. Nothing was padded or sent.")
    return {}


async def _finish(state: RunState) -> dict:
    ctx = _CONTEXTS[state["run_id"]]
    if ctx.runtime is not None and ctx.runtime.connected:
        await ctx.runtime._finish(state["run_id"])
    else:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from app.exports import write_report

        zone = ZoneInfo(load_runtime()["schedule"]["timezone"])
        write_report(ctx.session, state["run_id"], datetime.now(zone).date().isoformat())
        run = ctx.session.get(PipelineRun, state["run_id"])
        run.status = "completed"
        run.switch_status = "offline"
        run.finished_at = utcnow()
        ctx.session.commit()
    return {}


def _route(next_stage: str):
    def route(state: RunState) -> str:
        return "halt" if state.get("halted") else next_stage

    return route


def build_graph(checkpointer=None):
    graph = StateGraph(RunState)
    for stage in STAGES:
        graph.add_node(stage, _node(stage))
    graph.add_node("finish", _finish)
    graph.add_node("halt", _halt)
    graph.add_edge(START, STAGES[0])
    order = [*STAGES[1:], "finish"]
    for current, nxt in zip(STAGES, order):
        graph.add_conditional_edges(current, _route(nxt), {nxt: nxt, "halt": "halt"})
    graph.add_edge("finish", END)
    graph.add_edge("halt", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


def _pg_url(url: str) -> str | None:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return url
    return None


@traced("goip-run", run_type="chain")
async def run_graph(session_factory, runtime=None, trigger: str = "manual", settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    cfg = load_runtime()
    run_id = str(uuid.uuid4())
    session = session_factory()
    session.add(
        PipelineRun(
            id=run_id,
            status="running",
            trigger=trigger,
            targets=cfg["targets"],
            counts={},
            switch_status="connected" if runtime and runtime.connected else "offline",
            started_at=utcnow(),
        )
    )
    session.commit()
    budget = Budget()
    async with httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": "GOIP/0.1"}) as http:
        team = Team(session=session, http=http, settings=settings, run_id=run_id, boxes=_boxes(budget), budget=budget)
        _CONTEXTS[run_id] = _Context(team, runtime, session)
        config = {"configurable": {"thread_id": run_id}, "tags": [f"run:{run_id}"], "metadata": {"trigger": trigger}}
        try:
            pg = _pg_url(settings.goip_database_url)
            if pg:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                async with AsyncPostgresSaver.from_conn_string(pg) as saver:
                    await saver.setup()
                    await build_graph(saver).ainvoke({"run_id": run_id, "log": []}, config)
            else:
                await build_graph().ainvoke({"run_id": run_id, "log": []}, config)
        except BudgetExceeded as exc:
            run = session.get(PipelineRun, run_id)
            run.status = "partial"
            run.error = f"budget:{exc.verdict.rule}"
            run.finished_at = utcnow()
            session.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("graph run failed")
            run = session.get(PipelineRun, run_id)
            run.status = "partial"
            run.error = f"{exc.__class__.__name__}"[:200]
            run.finished_at = utcnow()
            session.commit()
        finally:
            _CONTEXTS.pop(run_id, None)
            session.close()
    return run_id
