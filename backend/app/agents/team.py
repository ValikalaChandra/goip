"""The six specialist agents. Each one acts through its ToolBox and verifies its own output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.agents.loop import LoopResult, act_verify_retry
from app.agents.toolbox import ToolBox
from app.config import load_runtime
from app.db import Opportunity, OutreachDraft, PipelineRun
from app.guardrails import Verdict, check_source_url


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


class Team:
    """Holds the per-run context the agents share: a session, http client, settings and toolboxes."""

    def __init__(self, *, session, http, settings, run_id: str, boxes: dict[str, ToolBox], budget):
        self.session = session
        self.http = http
        self.settings = settings
        self.run_id = run_id
        self.boxes = boxes
        self.budget = budget

    def _run(self) -> PipelineRun:
        run = self.session.get(PipelineRun, self.run_id)
        assert run is not None
        return run

    # ------------------------------------------------------------ discovery
    async def discover(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["discover"]
        holder: dict[str, Any] = {}

        async def act(_step: int) -> str:
            result = await box.call("fetch_and_group", self.session, self.http, self.settings, self._run())
            holder.update(result)
            return json.dumps(result["counts"])

        def verify() -> Verdict:
            counts = holder.get("counts") or {}
            if int(counts.get("raw_items") or 0) == 0:
                return _fail("no_sources_returned", "every source returned nothing; refusing to continue on empty data")
            return _ok("sources_returned", f"{counts.get('raw_items')} raw items")

        result = await act_verify_retry(self.budget, act, verify, max_steps=2)
        return result, {"company_ids": holder.get("company_ids", [])}

    # ------------------------------------------------------------- research
    async def research(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["research"]
        ids = list(state.get("company_ids") or [])
        limit = int(load_runtime()["targets"]["researched"])
        self.budget.reserve_llm(min(len(ids), limit))

        async def act(_step: int) -> str:
            result = await box.call("llm_extract_all", self.session, self.http, self.settings, self._run(), ids)
            return f"researched {len(result['company_ids'])}"

        def verify() -> Verdict:
            rows = self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id)).all()
            ungrounded = [
                row.public_id
                for row in rows
                if not any(str(f.get("source_url", "")).startswith("http") for f in (row.facts or []))
                or row.technical_need_kind != "inference"
            ]
            if ungrounded:
                return _fail("ungrounded_findings", f"no http source or inference label on: {', '.join(ungrounded[:5])}")
            return _ok("grounded", f"{len(rows)} opportunities carry a source URL and an inference label")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ------------------------------------------------------------ technical
    async def technical(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["technical"]

        async def act(_step: int) -> str:
            result = await box.call("search_and_attach", self.session, self.http, self._run())
            return json.dumps(result)

        def verify() -> Verdict:
            rows = self.session.scalars(select(Opportunity).where(Opportunity.run_id == self.run_id)).all()
            bad = [r.public_id for r in rows if r.oss_url and not str(r.oss_url).startswith("https://github.com/")]
            return _fail("non_github_repo", ", ".join(bad[:5])) if bad else _ok("repos_are_github")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # ---------------------------------------------------------- qualification
    async def qualify(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["qualify"]

        async def act(_step: int) -> str:
            return json.dumps(await box.call("score_all", self.session, self._run()))

        def verify() -> Verdict:
            from app.review import latest_evaluation

            rows = self.session.scalars(
                select(Opportunity).where(Opportunity.run_id == self.run_id, Opportunity.status == "high_priority")
            ).all()
            weak = []
            for row in rows:
                evaluation = latest_evaluation(self.session, row.id)
                if evaluation is None or evaluation.qualification != "freelance_evidence":
                    weak.append(row.public_id)
            return _fail("priority_without_evidence", ", ".join(weak[:5])) if weak else _ok("priority_backed_by_evidence")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # -------------------------------------------------------------- strategy
    async def strategy(self, state: dict) -> tuple[LoopResult, dict]:
        async def act(_step: int) -> str:
            return "strategy notes are on the opportunity records; no external message was sent"

        def verify() -> Verdict:
            drafts = self.session.scalar(
                select(func.count())
                .select_from(OutreachDraft)
                .join(Opportunity, Opportunity.id == OutreachDraft.opportunity_id)
                .where(Opportunity.run_id == self.run_id)
            )
            return _fail("draft_created_by_agent", f"{drafts} drafts exist") if drafts else _ok("no_drafts", "no outreach draft exists")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}

    # -------------------------------------------------------------------- qa
    async def qa(self, state: dict) -> tuple[LoopResult, dict]:
        box = self.boxes["qa"]

        async def act(_step: int) -> str:
            return json.dumps(await box.call("audit_all", self.session, self._run()))

        def verify() -> Verdict:
            sent = self.session.scalar(
                select(func.count()).select_from(OutreachDraft).where(OutreachDraft.sent.is_(True))
            )
            return _fail("outreach_marked_sent", f"{sent} drafts are marked sent") if sent else _ok("nothing_sent")

        return await act_verify_retry(self.budget, act, verify, max_steps=1), {}
