import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.agents.specialists as sp
from app.agents import memory
from app.db import AgentStep, Base, Company, EvaluationVersion, Opportunity, PipelineRun, Signal, SourceHealth, utcnow
from app.discovery.extract import RawItem
from app.guardrails import Budget
from tests.support import ScriptedLLM, final, step


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
    session.add(PipelineRun(id="r1", status="running", counts={}, started_at=utcnow()))
    session.commit()
    yield session
    session.close()


def team(db, llm, http=None):
    return SimpleNamespace(session=db, http=http, settings=SimpleNamespace(), run_id="r1", budget=Budget(), llm=llm,
                           run=db.get(PipelineRun, "r1"))


def add_company(db, cid, name, domain=None, text="", category="hiring", sig_type="hiring", url=None):
    db.add(Company(id=cid, identity_key=f"name:{cid}", name=name, normalized_name=name.lower(), domain=domain, created_at=utcnow()))
    db.add(Opportunity(id=f"o-{cid}", public_id=f"G{cid.upper():0>8}"[:9], run_id="r1", company_id=cid, status="researching"))
    db.add(Signal(id=f"s-{cid}", company_id=cid, run_id="r1", identity_hint=cid, source_name="HN: Who is hiring", source_url=url or f"https://news.ycombinator.com/item?id={abs(hash(cid)) % 9999}",
                  category=category, title=f"{name} | Backend", evidence=text, signal_type=sig_type, discovered_at=utcnow()))
    db.commit()


# ============================================================ discovery agent
class FakeGatherer:
    def __init__(self, *a, **k):
        self.sector = k.get("sector")
        self.ran = []

    def available(self):
        return {"hn_hiring": "x", "job_boards": "y", "hn_search": "z", "news_feeds": "n", "web_search": "w"}

    async def run_source(self, name):
        self.ran.append(name)
        n = {"hn_hiring": 2, "job_boards": 3, "hn_search": 4}.get(name, 1)
        return [RawItem(source_name=name, source_url=f"https://x.example/{name}/{i}", title=f"Co{i} | Backend | Contract", excerpt="contract role", company_name=f"Co{i}", category="hiring") for i in range(n)]


async def test_the_discovery_agent_picks_sources_from_what_it_learns(db, monkeypatch):
    monkeypatch.setattr(sp, "Gatherer", FakeGatherer)
    llm = ScriptedLLM([step("list_sources"), step("source_stats"), step("fetch_source", {"source": "job_boards"}), step("fetch_source", {"source": "hn_hiring"}),
                       final({"sources_used": ["job_boards", "hn_hiring"], "stop_reason": "both explicit-demand sources fetched"})])
    out = await sp.agentic_discovery(team(db, llm), "find freelance jobs", None)
    assert out.result.used_model and out.used == ["job_boards", "hn_hiring"] and len(out.pool) == 5
    assert "hn_search" not in out.used  # it skipped the news source: the agent chose, nothing ran by default
    assert "explicit_contract_postings" in out.result.steps[2].observation


async def test_the_discovery_agent_cannot_claim_sources_it_never_fetched(db, monkeypatch):
    monkeypatch.setattr(sp, "Gatherer", FakeGatherer)
    llm = ScriptedLLM([step("fetch_source", {"source": "hn_hiring"}), final({"sources_used": ["hn_hiring", "job_boards"], "stop_reason": "x"}),
                       final({"sources_used": ["hn_hiring"], "stop_reason": "fixed it"})])
    out = await sp.agentic_discovery(team(db, llm), "g", None)
    assert out.result.final["sources_used"] == ["hn_hiring"] and "sources_not_fetched" in out.result.steps[1].observation


async def test_an_unknown_source_is_an_error_the_agent_sees_and_recovers_from(db, monkeypatch):
    monkeypatch.setattr(sp, "Gatherer", FakeGatherer)
    llm = ScriptedLLM([step("fetch_source", {"source": "dark_web"}), step("fetch_source", {"source": "hn_hiring"}), final({"sources_used": ["hn_hiring"], "stop_reason": "ok"})])
    out = await sp.agentic_discovery(team(db, llm), "g", None)
    assert "unknown or unavailable source" in out.result.steps[0].observation and out.used == ["hn_hiring"]


async def test_exclude_prevents_refetching_on_a_retry(db, monkeypatch):
    monkeypatch.setattr(sp, "Gatherer", FakeGatherer)
    llm = ScriptedLLM([step("fetch_source", {"source": "hn_hiring"}), step("fetch_source", {"source": "job_boards"}), final({"sources_used": ["job_boards"], "stop_reason": "x"})])
    out = await sp.agentic_discovery(team(db, llm), "g", None, exclude=("hn_hiring",))
    assert out.used == ["job_boards"] and "already fetched" in out.result.steps[0].observation


# ============================================================== research agent
async def test_the_research_agent_may_open_only_pages_stored_for_the_company(db, monkeypatch):
    add_company(db, "c1", "Acme", text="Acme | Backend. We need a contractor to build our ledger API.", url="https://news.ycombinator.com/item?id=11")
    opened = []

    async def fake_get(http, url, **k):
        opened.append(url)
        return httpx.Response(200, text="<html><script>x()</script><p>Acme builds payment ledgers for banks.</p></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(sp, "get_capped", fake_get)
    sigs = list(db.scalars(select(Signal)))
    company = db.get(Company, "c1")
    llm = ScriptedLLM([step("fetch_stored_page", {"url": "https://evil.example/steal"}), step("fetch_stored_page", {"url": "https://news.ycombinator.com/item?id=11"}),
                       final({"evidence_quote": "Acme builds payment ledgers for banks.", "industry": "FinTech", "description": "Ledger software.", "inferred_need": "Possibly API work."})])
    r = await sp.agentic_research(team(db, llm), company, sigs, "Acme | Backend. We need a contractor to build our ledger API.")
    assert r.used_model and r.final["industry"] == "FinTech"
    assert opened == ["https://news.ycombinator.com/item?id=11"]  # the evil URL was refused before any request
    assert "may only open a page that is already stored" in r.steps[0].observation


async def test_a_research_quote_must_come_from_text_the_agent_saw(db):
    add_company(db, "c1", "Acme", text="Acme | Backend. We need a contractor to build our ledger API.")
    sigs = list(db.scalars(select(Signal)))
    llm = ScriptedLLM([final({"evidence_quote": "Acme raised a huge Series B", "inferred_need": "some need"}),
                       final({"evidence_quote": "We need a contractor to build our ledger API", "inferred_need": "API work."})])
    r = await sp.agentic_research(team(db, llm), db.get(Company, "c1"), sigs, "Acme | Backend. We need a contractor to build our ledger API.")
    assert r.final["evidence_quote"].startswith("We need a contractor") and "quote_not_in_source" in r.steps[0].observation


# ==================================================================== judge
POSTING_OK = "Acme Payments | Backend | We are looking for an experienced engineer to build our new ledger API over a three month engagement."
POSTING_SEEKER = "Location: Estonia Willing to relocate: No Technologies: React Part-time/Freelance: Yes available for contract work."


def verdict_args(sid, **kw):
    base = {"signal_id": sid, "is_freelance_opportunity": True, "poster": "company", "engagement": "contract", "work": "engineering",
            "confidence": "high", "quote": "over a three month engagement", "reasoning": "fixed-length build"}
    base.update(kw)
    return base


async def test_the_judge_stores_a_verdict_only_when_the_quote_is_in_the_posting(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    add_company(db, "c2", "Seeker", text=POSTING_SEEKER)
    llm = ScriptedLLM([
        step("list_postings"),
        step("submit_verdicts", {"verdicts": [
            verdict_args("s-c1"),                                                    # grounded: stored
            verdict_args("s-c2", is_freelance_opportunity=False, poster="individual_seeker", engagement="freelance", quote="", reasoning="a person offering their own work"),
            verdict_args("s-nope"),                                                  # not a posting it was given
        ]}),
        final({"summary": "judged two", "judged": 2}),
    ])
    r, stored = await sp.agentic_judge(team(db, llm))
    assert r.used_model and stored == 2
    ok, seeker = db.get(Signal, "s-c1"), db.get(Signal, "s-c2")
    assert ok.classification["is_freelance_opportunity"] and ok.classification["quote"] == "over a three month engagement" and ok.classification["by"] == "goip-qualification"
    assert seeker.classification["poster"] == "individual_seeker"
    assert "not one of the postings you were given" in r.steps[1].observation


async def test_an_invented_quote_is_rejected_by_the_tool_and_the_agent_is_told(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    llm = ScriptedLLM([step("list_postings"), step("submit_verdicts", {"verdicts": [verdict_args("s-c1", quote="a six month retainer")]}),
                       step("submit_verdicts", {"verdicts": [verdict_args("s-c1")]}), final({"summary": "ok", "judged": 1})])
    r, stored = await sp.agentic_judge(team(db, llm))
    assert stored == 1 and "must quote the posting word for word" in r.steps[1].observation
    assert db.get(Signal, "s-c1").classification["quote"] == "over a three month engagement"


async def test_the_judge_cannot_claim_more_verdicts_than_were_stored(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    llm = ScriptedLLM([step("list_postings"), final({"summary": "did it all", "judged": 5}), step("submit_verdicts", {"verdicts": [verdict_args("s-c1")]}), final({"summary": "ok", "judged": 1})])
    r, stored = await sp.agentic_judge(team(db, llm))
    assert stored == 1 and "judged_more_than_stored" in r.steps[1].observation


async def test_the_judge_sees_what_the_reviewer_approved_and_rejected_before(db):
    from app.db import HumanDecision

    add_company(db, "c1", "Acme", text=POSTING_OK)
    add_company(db, "c9", "Old", text="Old | Backend | Contract. Long ago.")
    db.add(HumanDecision(id="d1", opportunity_id="o-c9", action="reject", note="a recruiter", actor="operator", channel="dashboard", created_at=utcnow()))
    db.commit()
    llm = ScriptedLLM([step("reviewer_examples"), final({"summary": "calibrated", "judged": 0})])
    r, _ = await sp.agentic_judge(team(db, llm))
    assert "rejected" in r.steps[0].observation and "a recruiter" in r.steps[0].observation


async def test_the_judge_skips_postings_that_already_have_a_verdict(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    db.get(Signal, "s-c1").classification = {"is_freelance_opportunity": False}
    db.commit()
    r, stored = await sp.agentic_judge(team(db, ScriptedLLM([])))
    assert stored == 0 and r.mode == "fallback" and r.reason == "no postings to judge"


# ================================================================== technical
class Repo:
    def __init__(self, full, url, desc, topics=(), lic="MIT"):
        self.d = {"full_name": full, "html_url": url, "description": desc, "topics": list(topics), "license": {"spdx_id": lic}, "stargazers_count": 10}


def gh(monkeypatch, search=None, repos=None, readme=""):
    async def fake(t, url, accept="application/vnd.github+json"):
        if "/search/repositories" in url:
            return httpx.Response(200, json={"items": [r.d for r in (search or [])]}, request=httpx.Request("GET", url))
        if url.endswith("/readme"):
            return httpx.Response(200, text=readme, request=httpx.Request("GET", url))
        name = url.split("/repos/")[1]
        for r in repos or []:
            if r.d["full_name"] == name:
                return httpx.Response(200, json=r.d, request=httpx.Request("GET", url))
        raise ValueError("not found")

    monkeypatch.setattr(sp, "_github_json", fake)


async def test_the_technical_agent_matches_only_repositories_it_saw_that_mention_the_company(db, monkeypatch):
    add_company(db, "c1", "Acme Ledger", domain="acmeledger.io", text=POSTING_OK)
    gh(monkeypatch, search=[Repo("acme/acme-ledger", "https://github.com/acme/acme-ledger", "Acme Ledger core")])
    cands = sp.technical_candidates(team(db, None))
    llm = ScriptedLLM([
        step("github_search", {"query": "Acme Ledger"}),
        final({"matches": [{"company_id": "c1", "repo_url": "https://github.com/someone/invented", "why": "x"}]}),  # never seen
        final({"matches": [{"company_id": "c1", "repo_url": "https://github.com/acme/acme-ledger", "why": "its product repo"}]}),
    ])
    r, seen = await sp.agentic_technical(team(db, llm), cands)
    assert r.final["matches"][0]["repo_url"] == "https://github.com/acme/acme-ledger" and "repo_not_seen" in r.steps[1].observation


async def test_a_repository_that_does_not_mention_the_company_is_rejected(db, monkeypatch):
    add_company(db, "c1", "Acme Ledger", domain="acmeledger.io", text=POSTING_OK)
    gh(monkeypatch, search=[Repo("x/ledger-lib", "https://github.com/x/ledger-lib", "A generic accounting ledger library")])
    cands = sp.technical_candidates(team(db, None))
    llm = ScriptedLLM([step("github_search", {"query": "ledger"}), final({"matches": [{"company_id": "c1", "repo_url": "https://github.com/x/ledger-lib", "why": "a ledger"}]}),
                       final({"matches": [{"company_id": "c1", "repo_url": None, "why": "nothing belongs to them"}]})])
    r, _ = await sp.agentic_technical(team(db, llm), cands)
    assert r.final["matches"][0]["repo_url"] is None and "repo_not_about_company" in r.steps[1].observation


async def test_a_github_failure_is_information_not_a_crash(db, monkeypatch):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    gh(monkeypatch)
    cands = sp.technical_candidates(team(db, None))
    llm = ScriptedLLM([step("github_repo", {"full_name": "acme/missing"}), final({"matches": [{"company_id": "c1", "repo_url": None, "why": "not found"}]})])
    r, _ = await sp.agentic_technical(team(db, llm), cands)
    assert "tool error" in r.steps[0].observation and r.used_model


# =================================================================== strategy
def add_eval(db, opp_id, qualification="freelance_evidence"):
    db.add(EvaluationVersion(id=f"e-{opp_id}", opportunity_id=opp_id, version=1, method="v2_dimensions", business_signal_score=60, technical_evidence_score=70,
                             freelance_fit_score=85, confidence="medium", qualification=qualification, qa_verdict="flag", findings=[], services=[], detail={}, created_at=utcnow()))
    db.commit()


async def test_a_service_recommendation_needs_an_allowed_service_and_a_quote_from_the_posting(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    opp = db.get(Opportunity, "o-c1")
    opp.status = "high_priority"
    add_eval(db, "o-c1")
    pid = opp.public_id
    good = {"opportunity_id": pid, "service": "Backend and API development", "requirement_quote": "build our new ledger API", "rationale": "an API build"}
    llm = ScriptedLLM([
        step("list_services"),
        final({"recommendations": [{**good, "service": "Blockchain astrology"}]}),                 # not allowed
        final({"recommendations": [{**good, "requirement_quote": "migrate your data lake"}]}),     # not in the posting
        final({"recommendations": [good]}),
    ])
    r = await sp.agentic_strategy(team(db, llm), sp.reviewable(team(db, None)))
    assert r.final["recommendations"][0]["service"] == "Backend and API development"
    assert "service_not_allowed" in r.steps[1].observation and "quote_not_in_posting" in r.steps[2].observation


# ========================================================================= QA
async def test_the_qa_agent_can_recheck_the_original_page(db, monkeypatch):
    add_company(db, "c1", "Acme", text=POSTING_OK, url="https://news.ycombinator.com/item?id=5")
    opp = db.get(Opportunity, "o-c1")
    opp.status = "high_priority"
    add_eval(db, "o-c1")
    seen_urls = []

    async def fake_get(http, url, **k):
        seen_urls.append(url)
        return httpx.Response(200, text="<p>Acme Payments | Backend | We are looking for an experienced engineer to build our new ledger API over a three month engagement.</p>", request=httpx.Request("GET", url))

    monkeypatch.setattr(sp, "get_capped", fake_get)
    pid = opp.public_id
    llm = ScriptedLLM([step("recheck_source", {"opportunity_id": pid}), final({"reviews": [{"opportunity_id": pid, "verdict": "pass", "reasons": []}]})])
    r = await sp.agentic_qa(team(db, llm), sp.reviewable(team(db, None)))
    assert r.used_model and seen_urls == ["https://news.ycombinator.com/item?id=5"] and '"stored_text_still_on_page": true' in r.steps[0].observation


async def test_a_qa_flag_or_reject_needs_a_reason(db):
    add_company(db, "c1", "Acme", text=POSTING_OK)
    opp = db.get(Opportunity, "o-c1")
    opp.status = "high_priority"
    db.commit()
    pid = opp.public_id
    llm = ScriptedLLM([final({"reviews": [{"opportunity_id": pid, "verdict": "reject", "reasons": []}]}), final({"reviews": [{"opportunity_id": pid, "verdict": "reject", "reasons": ["the text offers full-time employment"]}]})])
    r = await sp.agentic_qa(team(db, llm), sp.reviewable(team(db, None)))
    assert r.final["reviews"][0]["reasons"] and "no_reason" in r.steps[0].observation


# ===================================================================== memory
def test_source_stats_remember_which_sources_produced_leads(db):
    for i in range(3):
        db.add(SourceHealth(id=f"h{i}", run_id="r1", name="Remotive", status="ok" if i < 2 else "failed", records=4, fetched_at=utcnow()))
    add_company(db, "c1", "Acme", text=POSTING_OK)
    db.get(Opportunity, "o-c1").status = "high_priority"
    db.get(Signal, "s-c1").source_name = "Remotive"
    db.commit()
    stats = {s["source"]: s for s in memory.source_stats(db)}
    assert stats["Remotive"]["fetches"] == 3 and stats["Remotive"]["ok_rate"] == 0.67 and stats["Remotive"]["qualified_leads"] == 1


def test_memory_upserts_and_the_trace_records_steps(db):
    memory.remember(db, "goip-orchestrator", "lesson", "k", {"a": 1})
    memory.remember(db, "goip-orchestrator", "lesson", "k", {"a": 2})
    assert memory.recall(db, "goip-orchestrator", "lesson") == [{"key": "k", "a": 2}]
    from app.agents.runtime import Step

    memory.record_steps(db, "r1", "goip-discovery", "discover", [Step(1, "think a@b.io", "fetch_source", {"source": "x", "key": "sk-abcdefghijklmnopqrstu"}, "saw 3 items")], "llm")
    memory.note_decision(db, "r1", "goip-qualification", "qualify", "fallback", "Ran the fixed policy (model unavailable).")
    trace = memory.trace_for(db, "r1")
    assert [t["mode"] for t in trace] == ["llm", "fallback"]
    assert "a@b.io" not in trace[0]["thought"] and "sk-abc" not in json.dumps(trace[0]["args"])


async def test_the_judge_pages_through_every_posting_so_none_is_cut_off(db):
    for i in range(6):
        add_company(db, f"c{i}", f"Co{i}", text=f"Co{i} | Backend | We need an engineer for a three month engagement number {i}.")
    seen_pages = []

    def policy(system, user):
        hist = json.loads(user)["steps_so_far"]
        last = hist[-1] if hist else None
        if last is None:
            return step("list_postings", {"offset": 0})
        if last["tool"] == "list_postings":
            body = json.loads(last["observation"].split("-----\n", 1)[1].rsplit("\n-----", 1)[0])
            seen_pages.append([p["company"] for p in body["postings"]])
            sids = [p["signal_id"] for p in body["postings"]]
            return step("submit_verdicts", {"verdicts": [verdict_args(sid, quote="three month engagement") for sid in sids]})
        pages = sum(1 for h in hist if h["tool"] == "list_postings")
        if len(seen_pages) < 2:
            return step("list_postings", {"offset": 4 * pages})
        return final({"summary": "done", "judged": 6})

    r, stored = await sp.agentic_judge(team(db, ScriptedLLM(policy)))
    assert stored == 6 and len(seen_pages) == 2 and len(seen_pages[0]) == 4 and len(seen_pages[1]) == 2
