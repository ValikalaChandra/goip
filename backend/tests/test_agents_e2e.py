"""The whole graph with a scripted model playing every agent: plan, discover, research, technical, judge, strategy, QA, reflect."""

import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import json
import re

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.specialists as sp
import app.exports as exports
import app.graph.build as build
from app.agents import memory
from app.config import get_settings
from app.db import Base, Company, EvaluationVersion, Opportunity, OutreachDraft, PipelineRun, Signal
from app.discovery.extract import RawItem
from app.discovery.gather import Gatherer
from tests.support import ScriptedLLM, final, step

ACME = "Acme Payments | Backend | We are looking for an experienced engineer to build our new ledger API over a three month engagement."
MAYA = "Maya Dev | Location: Estonia Willing to relocate: No Technologies: React Part-time/Freelance: Yes available for contract work."
BLACKBIRD = "Blackbird | Dev Shop | Remote | Contract Blackbird builds web and mobile products. We work with lots of freelancers."
ATEAM = "A.Team | Senior Independent Developer | contract role Engagement type: contract role. Build APIs for our clients."
BETA = "Beta raises $5M to build payments software"


def items(source):
    def raw(name, text, url, category="hiring", sig="hiring"):
        title = text.split(" Contract ")[0][:90] if name == "Blackbird" else text[:90]
        return RawItem(source_name=source, source_url=url, title=title, excerpt=text, category=category, company_name=name, signal_type=sig).prepare()

    return {
        "hn_hiring": [raw("Acme Payments", ACME, "https://news.ycombinator.com/item?id=101"), raw("Maya Dev", MAYA, "https://news.ycombinator.com/item?id=102"),
                      raw("Blackbird", BLACKBIRD, "https://news.ycombinator.com/item?id=103")],
        "job_boards": [raw("A.Team", ATEAM, "https://remotive.com/remote-jobs/1")],
        "hn_search": [raw("Beta", BETA, "https://beta.example.com/news", category="news", sig="funding")],
    }.get(source, [])


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    asked = []

    async def run_source(self, name):
        asked.append(name)
        return items(name)

    monkeypatch.setattr(Gatherer, "run_source", run_source)

    async def page(http, url, **k):
        return httpx.Response(200, text=f"<p>{ACME}</p>", request=httpx.Request("GET", url))

    monkeypatch.setattr(sp, "get_capped", page)

    async def github(t, url, accept="application/vnd.github+json"):
        repo = {"full_name": "acme/ledger", "html_url": "https://github.com/acme/ledger", "description": "Acme Payments ledger service", "topics": [], "license": {"spdx_id": "MIT"}, "stargazers_count": 7}
        return httpx.Response(200, json={"items": [repo]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(sp, "_github_json", github)

    async def no_repos(http, hits):
        return [], None

    monkeypatch.setattr(build, "fetch_github", no_repos)
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False), asked


# ---------------------------------------------------------------- the scripted "model"
def vargs(sid, **kw):
    base = {"signal_id": sid, "is_freelance_opportunity": True, "poster": "company", "engagement": "contract", "work": "engineering", "confidence": "high", "quote": "", "reasoning": "states the engagement"}
    base.update(kw)
    return base


def obs(h):
    return json.loads(re.search(r"UNTRUSTED SOURCE DATA -----\n(.*)\n----- END", h["observation"], re.S).group(1))


def model(system, user):
    u = json.loads(user) if user.lstrip().startswith("{") else {}
    h = u.get("steps_so_far", [])
    n = len(h)
    ctx = u.get("context", {})
    if "You are the orchestrator of GOIP" in system:
        return {"focus": None, "sources_to_prefer": ["hn_hiring", "job_boards"], "notes": "Explicit-demand sources first."}
    if "You review the output of the discovery agent" in system:
        return {"action": "proceed", "reason": "enough postings state a contract", "sources": []}
    if "writing a two-sentence assessment" in system:
        return {"assessment": "Two strong leads were found.", "next_suggestion": "Review the high-priority leads."}
    if "the Discovery agent" in system:
        plan = [step("list_sources"), step("fetch_source", {"source": "hn_hiring"}, "Companies asking for contractors are the strongest evidence."),
                step("fetch_source", {"source": "job_boards"}, "Job boards state the engagement type."),
                final({"sources_used": ["hn_hiring", "job_boards"], "stop_reason": "both demand sources fetched; news sources add no demand"})]
        return plan[n]
    if "the Company research agent" in system:
        return final({"evidence_quote": ctx["signals_preview"][:28], "industry": "FinTech", "description": "A software company.", "inferred_need": "An engineering build may follow."})
    if "the Freelance opportunity judge agent" in system:
        last = h[-1] if h else None
        if last is None:
            return step("list_postings", {"offset": 0})
        if last["tool"] == "list_postings":
            verdicts = []
            for p in obs(last)["postings"]:
                if "Willing to relocate" in p["posting"]:
                    verdicts.append(vargs(p["signal_id"], is_freelance_opportunity=False, poster="individual_seeker", engagement="freelance", reasoning="a person offering their own work"))
                else:
                    m = re.search(r"(over a three month engagement|contract role|Dev Shop \| Remote \| Contract)", p["posting"])
                    verdicts.append(vargs(p["signal_id"], quote=m.group(1)) if m else vargs(p["signal_id"], is_freelance_opportunity=False, engagement="unclear"))
            return step("submit_verdicts", {"verdicts": verdicts})
        listed = [x for x in h if x["tool"] == "list_postings"][-1]
        if obs(listed)["next_offset"] is not None:
            return step("list_postings", {"offset": obs(listed)["next_offset"]})
        return final({"summary": "judged every page", "judged": sum(obs(x)["accepted"] for x in h if x["tool"] == "submit_verdicts")})
    if "the Technical intelligence agent" in system:
        if n == 0:
            return step("read_company")
        if n == 1:
            return step("github_search", {"query": "Acme Payments"})
        companies, repos = obs(h[0]), obs(h[1])
        return final({"matches": [{"company_id": c["company_id"], "repo_url": repos[0]["url"] if c["name"] == "Acme Payments" else None, "why": "its ledger service"} for c in companies]})
    if "the Strategy agent" in system:
        leads = ctx["leads"]
        if n < len(leads):
            return step("read_evaluation", {"opportunity_id": leads[n]})
        recs = [{"opportunity_id": o["opportunity_id"], "service": "Backend and API development", "requirement_quote": "build our new ledger API", "rationale": "an API build"}
                for o in (obs(x) for x in h if x["tool"] == "read_evaluation") if "ledger API" in o["posting"]]
        return final({"recommendations": recs})
    if "the Quality assurance agent" in system:
        leads = ctx["leads"]
        if n < len(leads):
            return step("read_opportunity", {"opportunity_id": leads[n]})
        reviews = []
        for o in (obs(x) for x in h if x["tool"] == "read_opportunity"):
            if o["company"] == "A.Team":
                reviews.append({"opportunity_id": o["opportunity_id"], "verdict": "reject", "reasons": ["a marketplace profile for a talent network, not a client project"]})
            else:
                reviews.append({"opportunity_id": o["opportunity_id"], "verdict": "pass", "reasons": []})
        return final({"reviews": reviews})
    raise AssertionError("an agent prompt the script does not know: " + system[:80])


def status_of(factory, name):
    with factory() as s:
        company = s.scalar(select(Company).where(Company.name == name))
        return s.scalar(select(Opportunity).where(Opportunity.company_id == company.id)) if company else None


async def run(factory, llm, goal="find freelance engineering jobs"):
    return await build.run_graph(factory, None, "test", get_settings(), goal, llm)


# ======================================================================= the tests
async def test_the_agents_run_the_pipeline_by_their_own_decisions(world):
    factory, asked = world
    llm = ScriptedLLM(model)
    run_id = await run(factory, llm)
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.status == "completed", r.error
        modes = r.counts["agent_modes"]
        assert set(modes) == {"discover", "research", "technical", "qualify", "strategy", "qa"} and set(modes.values()) == {"llm"}
        assert r.counts["sources"] == ["hn_hiring", "job_boards"] and "hn_search" not in asked  # the agent never fetched the news source
        assert r.counts["judged"] == 4
        trace = memory.trace_for(s, run_id)
        tools = {t["tool"] for t in trace if t["tool"]}
        assert {"list_sources", "fetch_source", "read_company", "github_search", "list_postings", "submit_verdicts", "read_evaluation", "read_opportunity"} <= tools
        assert {"goip-orchestrator", "goip-discovery", "goip-company-research", "goip-technical-intelligence", "goip-qualification", "goip-strategy", "goip-quality-assurance"} == {t["agent"] for t in trace}
        assert {t["stage"] for t in trace if t["agent"] == "goip-orchestrator"} == {"plan", "discover", "reflect"}
        assert s.scalar(select(OutreachDraft)) is None


async def test_the_judge_finds_demand_the_keywords_miss_and_rejects_the_job_seeker(world):
    factory, _ = world
    await run(factory, ScriptedLLM(model))
    with factory() as s:
        acme, maya = status_of(factory, "Acme Payments"), status_of(factory, "Maya Dev")
        assert acme.status == "high_priority"  # no keyword anywhere in its posting: only the judge saw the demand
        assert maya.status != "high_priority"  # the keywords match ("contract work"), but the judge saw a person offering their own work
        ev = lambda o: s.scalars(select(EvaluationVersion).where(EvaluationVersion.opportunity_id == o.id, EvaluationVersion.method == "v2_dimensions").order_by(EvaluationVersion.version.desc())).first()
        assert ev(acme).qualification == "freelance_evidence" and ev(maya).qualification != "freelance_evidence"
        assert any("reviewer model" in f["claim"] for f in ev(maya).findings)
        verdict = s.scalar(select(Signal).where(Signal.id == s.scalar(select(Signal.id).where(Signal.company_id == acme.company_id)))).classification
        assert verdict["quote"] == "over a three month engagement" and verdict["poster"] == "company"


async def test_specialists_use_their_own_tools_to_enrich_the_leads(world):
    factory, _ = world
    await run(factory, ScriptedLLM(model))
    acme = status_of(factory, "Acme Payments")
    assert acme.oss_url == "https://github.com/acme/ledger" and "technical agent matched" in acme.oss_relevance
    assert acme.recommendations[0]["service"] == "Backend and API development" and acme.recommendations[0]["requirement_quote"] == "build our new ledger API"
    assert acme.recommended_service in ("", None) or isinstance(acme.recommended_service, str)  # the evaluation's own field is untouched by the agent
    assert status_of(factory, "Blackbird").oss_url is None


async def test_the_qa_agent_can_lower_trust_in_a_lead_and_the_run_reflects_it(world):
    factory, _ = world
    run_id = await run(factory, ScriptedLLM(model))
    ateam = status_of(factory, "A.Team")
    assert ateam.status == "needs_review" and "QA agent rejected" in ateam.status_reason and "QA agent (reject)" in ateam.qa_notes
    assert status_of(factory, "Blackbird").status == "high_priority"
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.counts["qa_agent_rejected"] == 1 and r.counts["high_priority"] == 2  # recounted after the demotion


async def test_without_a_model_every_stage_runs_its_fixed_policy_and_says_so(world):
    factory, asked = world
    run_id = await run(factory, ScriptedLLM([], available=False))
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.status == "completed"
        assert set(r.counts["agent_modes"].values()) == {"fallback"}
        assert set(asked) >= {"hn_search", "hn_hiring", "job_boards"}  # the fixed policy fetches everything
        trace = memory.trace_for(s, run_id)
        assert all(t["mode"] == "fallback" for t in trace) and any("fixed policy" in t["thought"] for t in trace)
        assert any("model unavailable" in t["thought"] for t in trace)  # the trace says WHY, not just that no call was made
        assert {t["agent"] for t in trace} >= {"goip-discovery", "goip-qualification", "goip-quality-assurance", "goip-orchestrator"}
    # and the keywords alone are fooled in both directions: they miss Acme and they accept the job-seeker
    assert status_of(factory, "Acme Payments").status != "high_priority"
    assert status_of(factory, "Maya Dev").status == "high_priority"


async def test_a_failing_model_degrades_only_the_stage_it_failed_in(world):
    factory, _ = world

    def flaky(system, user):
        return None if "Freelance opportunity judge" in system else model(system, user)

    run_id = await run(factory, ScriptedLLM(flaky))
    with factory() as s:
        modes = s.get(PipelineRun, run_id).counts["agent_modes"]
    assert modes["qualify"] == "fallback" and modes["discover"] == modes["research"] == modes["strategy"] == "llm"


async def test_the_orchestrator_plans_from_the_request_and_cannot_invent_sources(world):
    factory, asked = world

    def planner(system, user):
        if "You are the orchestrator of GOIP" in system:
            return {"focus": "banking", "sources_to_prefer": ["hn_hiring", "dark_web", "job_boards"], "notes": "x" * 900}
        return model(system, user)

    run_id = await run(factory, ScriptedLLM(planner), goal="find freelance banking engineering jobs")
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.status == "completed" and r.counts["focus"] == "banking"  # the operator's word, not a wider category
        plan = [t for t in memory.trace_for(s, run_id) if t["stage"] == "plan"][0]
        assert "banking" in plan["thought"] and "fintech" not in plan["thought"] and "dark_web" not in plan["thought"] and len(plan["thought"]) <= 400


async def test_a_thin_first_pass_makes_the_orchestrator_broaden_the_search_once_even_if_the_model_says_proceed(world):
    factory, asked = world

    def thin(system, user):
        if "the Discovery agent" in system and json.loads(user)["steps_so_far"] == [] and "Fetch:" not in user:
            return step("fetch_source", {"source": "hn_search"})  # a weak first choice: only a news source
        if "the Discovery agent" in system:
            h = json.loads(user)["steps_so_far"]
            ctx = json.loads(user)["context"]
            if "Fetch:" in (ctx.get("hint_from_orchestrator") or ""):  # the retry pass, told which sources to use
                seq = [step("fetch_source", {"source": "hn_hiring"}), step("fetch_source", {"source": "job_boards"}), final({"sources_used": ["hn_hiring", "job_boards"], "stop_reason": "broadened"})]
                return seq[len(h)]
            return final({"sources_used": ["hn_search"], "stop_reason": "got news"})
        return model(system, user)

    run_id = await run(factory, ScriptedLLM(thin))
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.counts["sources"] == ["hn_search", "hn_hiring", "job_boards"]
        review = [t for t in memory.trace_for(s, run_id) if t["agent"] == "goip-orchestrator" and "Review of discovery" in t["thought"]][0]
        assert "retry" in review["thought"]
    assert status_of(factory, "Acme Payments").status == "high_priority"  # the retry is what made the real lead reachable


async def test_every_run_writes_a_lesson_to_memory(world):
    factory, _ = world
    run_id = await run(factory, ScriptedLLM(model))
    with factory() as s:
        lessons = memory.recall(s, "goip-orchestrator", "lesson")
        assert lessons and lessons[0]["sources"] == ["hn_hiring", "job_boards"] and lessons[0]["high_priority"] == 2


async def test_a_review_cannot_stop_the_run_or_retry_with_invented_sources(world):
    factory, _ = world

    def reviewer(system, user):
        if "You review the output of the discovery agent" in system:
            return {"action": "stop", "reason": "give up", "sources": ["dark_web"]}
        return model(system, user)

    run_id = await run(factory, ScriptedLLM(reviewer))
    with factory() as s:
        r = s.get(PipelineRun, run_id)
        assert r.status == "completed"  # a stop while there are items is overruled
        review = [t for t in memory.trace_for(s, run_id) if "Review of discovery" in t["thought"]][0]
        assert "proceed" in review["thought"] and "dark_web" not in json.dumps(review)


@pytest.mark.parametrize("reply", [None, {}, [], "text", {"focus": ["not", "a", "string"]}, {"focus_sector": "fintech"}])
async def test_a_failed_or_empty_model_reply_is_never_reported_as_a_plan(reply):
    from types import SimpleNamespace

    from app.agents.orchestrator import plan_run

    t = SimpleNamespace(llm=ScriptedLLM([reply]), session=None)
    t.session = type("S", (), {"scalars": lambda *a, **k: type("R", (), {"all": lambda s: []})(), "execute": lambda *a, **k: type("R", (), {"all": lambda s: []})()})()
    plan = await plan_run(t, "find freelance fintech jobs")
    assert plan.mode == "fallback" and plan.reason and plan.focus == "fintech"  # the request still names the focus; the model did not plan
