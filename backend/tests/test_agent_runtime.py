import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from pydantic import BaseModel, Field

from app.agents.runtime import AgentResult, ToolSpec, build_system, run_agent
from app.agents.toolbox import ToolBox
from app.guardrails import Budget, BudgetExceeded, GuardrailViolation, Verdict
from tests.support import ScriptedLLM, final, step

AGENT = "goip-discovery"  # its allowlist includes list_sources / fetch_source / source_stats


class NoArgs(BaseModel):
    pass


class FetchArgs(BaseModel):
    source: str = Field(max_length=40)


class Answer(BaseModel):
    summary: str
    quote: str = ""


def make(budget=None, boom=False):
    budget = budget or Budget()
    calls = []

    def list_sources():
        calls.append("list_sources")
        return {"sources": ["hn_hiring", "job_boards"]}

    def fetch_source(source):
        calls.append(("fetch_source", source))
        if boom:
            raise RuntimeError("upstream down")
        return {"fetched": 3, "text": "Acme is hiring a contractor for an API project"}

    tools = [ToolSpec("list_sources", "List sources", NoArgs, list_sources), ToolSpec("fetch_source", "Fetch one source", FetchArgs, fetch_source)]
    box = ToolBox(AGENT, budget, {t.name: t.fn for t in tools})
    return tools, box, budget, calls


async def go(llm, tools, box, budget, **kw):
    return await run_agent(role="Discovery", mission="Find sources.", goal="g", context={"focus": None}, tools=tools, final_model=Answer,
                           llm=llm, toolbox=box, budget=budget, **kw)


async def test_the_agent_chooses_tools_from_what_it_sees_then_answers():
    tools, box, budget, calls = make()
    llm = ScriptedLLM([step("list_sources"), step("fetch_source", {"source": "hn_hiring"}), final({"summary": "got 3"})])
    r = await go(llm, tools, box, budget)
    assert r.mode == "llm" and r.final["summary"] == "got 3" and r.used_model
    assert calls == ["list_sources", ("fetch_source", "hn_hiring")]
    assert [s.tool for s in r.steps] == ["list_sources", "fetch_source", None]
    assert "hn_hiring" in llm.calls[1][1]  # the second prompt carries what the first tool returned


async def test_an_unknown_tool_is_refused_and_the_agent_recovers():
    tools, box, budget, calls = make()
    llm = ScriptedLLM([step("send_email", {"to": "ceo@acme.io"}), step("list_sources"), final({"summary": "ok"})])
    r = await go(llm, tools, box, budget)
    assert r.final["summary"] == "ok" and calls == ["list_sources"]
    assert not r.steps[0].ok and "unknown tool" in r.steps[0].observation


async def test_bad_arguments_and_repeated_calls_are_rejected():
    tools, box, budget, calls = make()
    llm = ScriptedLLM([step("fetch_source", {"source": "x" * 99}), step("fetch_source", {"source": "hn_hiring"}), step("fetch_source", {"source": "hn_hiring"}), final({"summary": "ok"})])
    r = await go(llm, tools, box, budget)
    assert calls == [("fetch_source", "hn_hiring")]  # once: the bad call and the exact repeat never ran
    assert "bad arguments" in r.steps[0].observation and "already made this exact call" in r.steps[2].observation


async def test_a_final_answer_must_match_its_schema_and_pass_grounding():
    tools, box, budget, _ = make()

    def grounding(final_obj, seen):
        return Verdict("output", "quote_not_in_source", False, "not seen") if final_obj["quote"] and final_obj["quote"] not in seen else Verdict("output", "grounded", True)

    llm = ScriptedLLM([
        final({"nope": 1}),                                           # wrong shape
        final({"summary": "s", "quote": "Acme is hiring a unicorn"}),  # a quote the agent never saw
        step("fetch_source", {"source": "hn_hiring"}),
        final({"summary": "s", "quote": "Acme is hiring a contractor"}),  # copied from the observation
    ])
    r = await go(llm, tools, box, budget, grounding=grounding, max_steps=6)
    assert r.final["quote"] == "Acme is hiring a contractor"
    assert "final answer rejected" in r.steps[0].observation and "quote_not_in_source" in r.steps[1].observation


async def test_the_step_limit_ends_the_loop_with_a_reason():
    tools, box, budget, _ = make()
    llm = ScriptedLLM(lambda s, u: step("list_sources") if "steps_left\": 3" in u else step("fetch_source", {"source": str(len(u))[:5]}))
    r = await go(llm, tools, box, budget, max_steps=3)
    assert r.mode == "fallback" and r.final is None and "all its steps" in r.reason


async def test_an_unavailable_model_falls_back_without_asking():
    tools, box, budget, _ = make()
    llm = ScriptedLLM([], available=False)
    r = await go(llm, tools, box, budget)
    assert r.mode == "fallback" and "unavailable" in r.reason and llm.calls == []


async def test_a_failed_model_call_mid_run_falls_back_and_keeps_the_trace():
    tools, box, budget, _ = make()
    r = await go(ScriptedLLM([step("list_sources"), None]), tools, box, budget)
    assert r.mode == "fallback" and len(r.steps) == 1 and "no usable answer" in r.reason


async def test_a_tool_error_is_shown_to_the_agent_not_raised():
    tools, box, budget, _ = make(boom=True)
    r = await go(ScriptedLLM([step("fetch_source", {"source": "hn_hiring"}), final({"summary": "gave up"})]), tools, box, budget)
    assert r.final["summary"] == "gave up" and "tool error: RuntimeError" in r.steps[0].observation


async def test_a_tool_outside_the_agents_allowlist_stops_the_run():
    budget = Budget()
    spec = ToolSpec("write_score", "set a score", NoArgs, lambda: "x")  # a forbidden capability, even if someone wires it
    box = ToolBox(AGENT, budget, {"write_score": spec.fn})
    with pytest.raises(GuardrailViolation):
        await run_agent(role="D", mission="m", goal="g", context={}, tools=[spec], final_model=Answer, llm=ScriptedLLM([step("write_score")]), toolbox=box, budget=budget)


async def test_the_run_budget_stops_an_agent_that_keeps_going():
    tools, box, budget, _ = make(budget=Budget(max_tool_calls=1))
    llm = ScriptedLLM([step("list_sources"), step("fetch_source", {"source": "a"}), final({"summary": "s"})])
    with pytest.raises(BudgetExceeded):
        await go(llm, tools, box, budget)


async def test_scraped_text_telling_the_agent_to_act_is_just_data():
    tools, box, budget, calls = make()
    hostile = {"thought": "The page says to email the CEO", "tool": "send_email", "args": {"to": "x"}, "final": None}
    r = await go(ScriptedLLM([step("fetch_source", {"source": "hn_hiring"}), hostile, final({"summary": "ignored the instruction"})]), tools, box, budget)
    assert r.final["summary"] == "ignored the instruction" and calls == [("fetch_source", "hn_hiring")]
    assert "unknown tool" in r.steps[1].observation
    system, user = ScriptedLLM([]).calls, None  # the protocol text itself tells the model observations are never instructions
    assert "never an instruction" in build_system("D", "m", tools, Answer)


def test_the_system_prompt_lists_tools_and_the_output_schema():
    tools, *_ = make()
    s = build_system("Discovery", "Find sources.", tools, Answer)
    assert "fetch_source(source: string)" in s and "list_sources()" in s and "summary" in s and "cannot contact anyone" in s


async def test_openrouter_llm_spends_the_run_budget_and_respects_availability(monkeypatch):
    from types import SimpleNamespace

    import app.agents.llm as llm_mod
    from app.integrations import openrouter as orr

    budget = Budget(max_llm_calls=1)
    calls = []

    async def fake_call(self, model, fallbacks, system, user):
        calls.append(model)
        return {"ok": True}

    monkeypatch.setattr(llm_mod.OpenRouterLLM, "_call", fake_call)
    monkeypatch.setitem(orr.LLM_STATE, "ok", True)
    llm = llm_mod.OpenRouterLLM(None, SimpleNamespace(openrouter_api_key="k"), budget)
    assert llm.available and await llm.ask("s", "u") == {"ok": True}
    with pytest.raises(BudgetExceeded):
        await llm.ask("s", "u")
    monkeypatch.setitem(orr.LLM_STATE, "ok", False)
    assert not llm.available and await llm.ask("s", "u") is None
    assert not llm_mod.OpenRouterLLM(None, SimpleNamespace(openrouter_api_key=""), Budget()).available
