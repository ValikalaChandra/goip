"""The six specialist agents and how a stage runs.

For every stage the agent runs first: it gets a goal and tools, and the model decides what to do next
(app/agents/specialists.py). If the model is unavailable or gives nothing valid, the stage runs its fixed policy instead,
and the trace says so. After either path the deterministic self-check runs as the floor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.agents import memory
from app.agents import specialists as sp
from app.agents.llm import OpenRouterLLM
from app.agents.loop import LoopResult, act_verify_retry
from app.agents.orchestrator import Plan, review_discovery
from app.agents.runtime import AgentResult
from app.agents.toolbox import ToolBox
from app.config import load_runtime
from app.db import Opportunity, OutreachDraft, PipelineRun, Signal
from app.discovery.sources import _CONTRACT
from app.guardrails import Verdict, check_source_url
from app.pipeline import _set_status, apply_research, prepare_research
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    goal: str


SPECS = {
    "discover": AgentSpec("goip-discovery", "Source collector", "Collect public business signals and group them by company."),
    "research": AgentSpec("goip-company-research", "Evidence analyst", "Separate observed quotes from inferred needs."),
    "technical": AgentSpec("goip-technical-intelligence", "Repository scout", "Attach a name-matching public repository."),
    "qualify": AgentSpec("goip-qualification", "Scorer", "Apply the deterministic v2 evidence rules."),
    "strategy": AgentSpec("goip-strategy", "Service strategist", "Name a service only when a stored requirement supports it."),
    "qa": AgentSpec("goip-quality-assurance", "Auditor", "Check source URL, fact/inference split and the no-outreach invariant."),
}


def _ok(rule: str, detail: str = "") -> Verdict:
    return Verdict("output", rule, True, detail)


def _fail(rule: str, detail: str) -> Verdict:
    return Verdict("output", rule, False, detail)


AGENT_RESEARCH_LIMIT = 12  # companies researched by an agent loop per run; the rest use the stored text


class Team:
    """The per-run context the agents share, and the six stages."""

    def __init__(self, *, session, http, settings, run_id: str, boxes: dict[str, ToolBox], budget, llm=None, goal: str = "", plan: Plan | None = None):
        self.session = session
        self.http = http
        self.settings = settings
        self.run_id = run_id
        self.boxes = boxes
        self.budget = budget
        self.llm = llm or OpenRouterLLM(http, settings, budget)
        self.goal = goal
        self.plan = plan
        self.modes: dict[str, str] = {}  # stage -> "llm" | "fallback"
        self.notes: dict[str, str] = {}  # stage -> one line for the room
        self.judged = 0

    @property
    def run(self) -> PipelineRun:
        run = self.session.get(PipelineRun, self.run_id)
        assert run is not None
        return run

    _run = run

    # ------------------------------------------------------------------ tracing
    def _trace(self, stage: str, result: AgentResult | None, fixed_note: str = "") -> None:
        """Record what the agent did, or honestly that the fixed policy ran and why."""
        agent = SPECS[stage].name
        if result is not None and result.steps:
            memory.record_steps(self.session, self.run_id, agent, stage, result.steps, "llm")
        if result is not None and result.used_model:
            self.modes[stage] = "llm"
            thoughts = [s.thought for s in result.steps if s.thought][:2]
            self.notes[stage] = " ".join(thoughts)[:300]
            return
        self.modes[stage] = "fallback"
        if result is not None and result.reason:
            reason = result.reason
        else:
            from app.agents.llm import unavailable_reason

            reason = f"model unavailable ({unavailable_reason().replace('_', ' ')})"
        memory.note_decision(self.session, self.run_id, agent, stage, "fallback", f"Ran the fixed policy ({reason}). {fixed_note}".strip())
        self.notes[stage] = f"fixed policy: {reason}"

    def _counts(self, **extra) -> dict:
        run = self.run
        counts = dict(run.counts or {})
        counts.update(extra)
        counts["agent_modes"] = dict(self.modes)
        run.counts = counts
        self.session.commit()
        return counts

    # ---------------------------------------------------------------- discovery
    async def discover(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["discover"]
        holder: dict[str, Any] = {}
        focus = self.plan.focus if self.plan else None

        async def act(_step: int) -> str:
            pool, used = None, []
            if self.llm.available:
                outcome = await sp.agentic_discovery(self, self.goal, focus, hint=self.plan.hint() if self.plan else "")
                self._trace("discover", outcome.result, "All sources were fetched.")
                if outcome.result.used_model and outcome.pool:
                    pool, used = list(outcome.pool), list(outcome.used)
                    explicit = sum(1 for i in pool if _CONTRACT.search(f"{i.title} {i.excerpt}"))
                    review = await review_discovery(self, self.plan or Plan(self.goal, focus), used, explicit, len(pool), retried=False)
                    memory.note_decision(self.session, self.run_id, "goip-orchestrator", "discover", review.mode,
                                         f"Review of discovery: {review.action}. {review.reason}", observation=f"postings stating a contract: {explicit}; items: {len(pool)}")
                    self.notes["review"] = f"{review.action}: {review.reason}"
                    if review.action == "retry":
                        more = await sp.agentic_discovery(self, self.goal, focus, exclude=tuple(used), hint="Fetch: " + ", ".join(review.sources))
                        self._trace("discover", more.result, "")
                        pool += more.pool
                        used += more.used
                else:
                    pool = None
            else:
                self._trace("discover", None, "All sources were fetched.")
            result = await box.call("fetch_and_group", self.session, self.http, self.settings, self.run, pool=pool, used=used or None, focus=focus)
            holder.update(result)
            counts = self._counts()
            return json.dumps({**result["counts"], "agent_mode": self.modes.get("discover")})

        def verify() -> Verdict:
            counts = holder.get("counts") or {}
            if int(counts.get("raw_items") or 0) == 0:
                return _fail("no_sources_returned", "every source returned nothing; refusing to continue on empty data")
            return _ok("sources_returned", f"{counts.get('raw_items')} raw items")

        result = await act_verify_retry(self.budget, act, verify, max_steps=2)
        return result, {"company_ids": holder.get("company_ids", [])}

    # ----------------------------------------------------------------- research
    async def research(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["research"]
        ids = list(state.get("company_ids") or [])
        limit = int(load_runtime()["targets"]["researched"])

        async def act(_step: int) -> str:
            if self.llm.available and ids:
                chosen = ids[:limit]
                used_model = 0
                for i, company_id in enumerate(chosen):
                    prepared = prepare_research(self.session, self.run, company_id)
                    if prepared is None:
                        continue
                    company, opportunity, signals, evidence = prepared
                    parsed = None
                    if i < AGENT_RESEARCH_LIMIT and self.llm.available:
                        result = await sp.agentic_research(self, company, signals, evidence)
                        self._trace("research", result, "")
                        if result.used_model:
                            parsed, used_model = result.final, used_model + 1
                    apply_research(self.session, company, opportunity, signals, evidence, parsed)
                self.modes["research"] = "llm" if used_model else "fallback"
                self._counts(researched=len(chosen))
                return f"researched {len(chosen)}"
            self._trace("research", None, "Each company was researched from its stored text.")
            result = await box.call("llm_extract_all", self.session, self.http, self.settings, self.run, ids)
            self._counts()
            return f"researched {len(result['company_ids'])}"

        def verify() -> Verdict:
            rows = self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id)).all()
            ungrounded = [
                row.public_id
                for row in rows
                if not any(str(f.get("source_url", "")).startswith("http") for f in (row.facts or [])) or row.technical_need_kind != "inference"
            ]
            if ungrounded:
                return _fail("ungrounded_findings", f"no http source or inference label on: {', '.join(ungrounded[:5])}")
            return _ok("grounded", f"{len(rows)} opportunities carry a source URL and an inference label")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ---------------------------------------------------------------- technical
    async def technical(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["technical"]

        async def act(_step: int) -> str:
            candidates = sp.technical_candidates(self)
            if self.llm.available and candidates:
                result, seen = await sp.agentic_technical(self, candidates)
                self._trace("technical", result, "")
                if result.used_model:
                    by_company = {m["company_id"]: m for m in result.final["matches"]}
                    attached = 0
                    for opp in self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id)).all():
                        match = by_company.get(opp.company_id)
                        repo = seen.get(match["repo_url"]) if match and match.get("repo_url") else None
                        if repo:
                            opp.oss_name, opp.oss_url, opp.oss_license = repo["full_name"], repo["url"], repo["license"]
                            opp.oss_relevance = f"The technical agent matched this repository: {match['why']} Licence: {repo['license']}. Use it as a starting point only if that licence fits the engagement."
                            attached += 1
                        elif opp.company_id in by_company:
                            opp.oss_relevance = "The technical agent searched GitHub and found no repository that belongs to this company."
                        _set_status(self.session, opp, "researching", "Technical repository search completed.", "goip-technical-intelligence")
                    self.session.commit()
                    self._counts()
                    return json.dumps({"repositories_seen": len(seen), "attached": attached, "error": None})
            else:
                self._trace("technical", None, "Repositories were matched by company name.")
            out = await box.call("search_and_attach", self.session, self.http, self.run)
            self._counts()
            return json.dumps(out)

        def verify() -> Verdict:
            rows = self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id)).all()
            bad = [r.public_id for r in rows if r.oss_url and not str(r.oss_url).startswith("https://github.com/")]
            return _fail("non_github_repo", ", ".join(bad[:5])) if bad else _ok("repos_are_github")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ------------------------------------------------------------ qualification
    async def qualify(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["qualify"]

        async def act(_step: int) -> str:
            judged = 0
            if self.llm.available:
                result, judged = await sp.agentic_judge(self)
                self._trace("qualify", result, "")
                self.judged = judged
            else:
                self._trace("qualify", None, "Freelance evidence was found by keyword rules only.")
            counts = await box.call("score_all", self.session, self.run)
            self._counts(judged=judged)
            return json.dumps({**counts, "judged": judged, "agent_mode": self.modes.get("qualify")})

        def verify() -> Verdict:
            from app.review import latest_evaluation

            rows = self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id, Opportunity.status == "high_priority")).all()
            weak = []
            for row in rows:
                evaluation = latest_evaluation(self.session, row.id)
                if evaluation is None or evaluation.qualification != "freelance_evidence":
                    weak.append(row.public_id)
            return _fail("priority_without_evidence", ", ".join(weak[:5])) if weak else _ok("priority_backed_by_evidence")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ----------------------------------------------------------------- strategy
    async def strategy(self, state: dict) -> tuple[LoopResult, dict]:
        async def act(_step: int) -> str:
            candidates = sp.reviewable(self)
            if self.llm.available and candidates:
                result = await sp.agentic_strategy(self, candidates)
                self._trace("strategy", result, "")
                if result.used_model:
                    by_pid = {o.public_id: o for o in candidates}
                    for rec in result.final["recommendations"]:
                        by_pid[rec["opportunity_id"]].recommendations = [{
                            "service": rec["service"], "requirement_quote": rec["requirement_quote"], "rationale": rec["rationale"],
                            "by": "goip-strategy", "grounded": True,
                        }]
                    self.session.commit()
                    self._counts()
                    return f"recommended a service for {len(result.final['recommendations'])} of {len(candidates)} leads; nothing was drafted or sent"
            else:
                self._trace("strategy", None, "Service notes come from the evaluation.")
            self._counts()
            return "strategy notes are on the opportunity records; no external message was sent"

        def verify() -> Verdict:
            drafts = self.session.scalar(
                select(func.count()).select_from(OutreachDraft).join(Opportunity, Opportunity.id == OutreachDraft.opportunity_id).where(Opportunity.run_id == self.run_id)
            )
            return _fail("draft_created_by_agent", f"{drafts} drafts exist") if drafts else _ok("no_drafts", "no outreach draft exists")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ----------------------------------------------------------------------- qa
    async def qa(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["qa"]

        async def act(_step: int) -> str:
            counts = await box.call("audit_all", self.session, self.run)  # the deterministic floor always runs
            candidates = sp.reviewable(self)
            rejected = flagged = 0
            if self.llm.available and candidates:
                result = await sp.agentic_qa(self, candidates)
                self._trace("qa", result, "")
                if result.used_model:
                    by_pid = {o.public_id: o for o in candidates}
                    for review in result.final["reviews"]:
                        opp = by_pid[review["opportunity_id"]]
                        line = f"QA agent ({review['verdict']}): " + ("; ".join(review["reasons"]) or "no concerns found.")
                        opp.qa_notes = f"{opp.qa_notes}\n{line}".strip()
                        if review["verdict"] == "reject":
                            rejected += 1
                            if opp.status in ("qualified", "high_priority"):  # QA can only lower trust, never raise it
                                _set_status(self.session, opp, "needs_review", "QA agent rejected: " + "; ".join(review["reasons"])[:300], "goip-quality-assurance")
                        elif review["verdict"] == "flag":
                            flagged += 1
                    self.session.commit()
            else:
                self._trace("qa", None, "Only the deterministic checks ran.")
            high = self.session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.run_id == self.run_id, Opportunity.status == "high_priority")) or 0
            counts = self._counts(high_priority=high, qa_agent_rejected=rejected, qa_agent_flagged=flagged)
            return json.dumps({**counts, "agent_mode": self.modes.get("qa")})

        def verify() -> Verdict:
            sent = self.session.scalar(select(func.count()).select_from(OutreachDraft).where(OutreachDraft.sent.is_(True)))
            return _fail("outreach_marked_sent", f"{sent} drafts are marked sent") if sent else _ok("nothing_sent")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}
