from __future__ import annotations

import hmac
import re
import secrets
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.config import GOIP_ROOT, get_settings, load_runtime, save_runtime
from app.guardrails import GuardrailViolation, check_status_transition, require
from app.db import (
    AgentMessage,
    Company,
    EvaluationVersion,
    HumanDecision,
    Opportunity,
    OutreachDraft,
    PipelineRun,
    ResearchTask,
    Signal,
    SignalReconciliation,
    SourceHealth,
    StatusEvent,
    make_engine,
    make_session_factory,
    upgrade,
    utcnow,
)
from app.commercial import assess_commercial_intent
from app.reconciliation import apply_human_action
from app.scoring.evidence import decode_text
from app.scoring.v2 import _service_supported
from app.exports import read_export, write_report
from app.integrations.openrouter import LLM_MESSAGES, llm_health
from app.integrations.telegram_api import authorized, get_me, parse_command, send_document, send_message
from app.pipeline import discover, qualify, quality_check, research, shortfall
from app.discovery.sources import fetch_github
from app.pipeline import attach_github
from app.switch_runtime import build_runtime, get_runtime, set_runtime

engine = make_engine()
SessionFactory = make_session_factory(engine)


def db() -> Session:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


class LoginBody(BaseModel):
    token: str


class DecisionBody(BaseModel):
    action: str = Field(pattern="^(approve|reject|needs_review|request_research)$")
    note: str = Field(default="", max_length=2000)


class ReconciliationBody(BaseModel):
    action: str = Field(pattern="^(confirm|reject|duplicate|unassigned|request_research)$")
    company_id: str = ""
    note: str = Field(default="", max_length=2000)


class RunBody(BaseModel):
    goal: str = Field(default="", max_length=300)


class RuntimeBody(BaseModel):
    values: dict


SESSION_TTL = 60 * 60 * 12
_SESSIONS: dict[str, float] = {}
_MAX_SESSIONS = 50


def _new_session() -> str:
    now = time.time()
    for key in [k for k, exp in _SESSIONS.items() if exp < now]:
        _SESSIONS.pop(key, None)
    while len(_SESSIONS) >= _MAX_SESSIONS:
        _SESSIONS.pop(min(_SESSIONS, key=_SESSIONS.get), None)
    sid = secrets.token_urlsafe(32)
    _SESSIONS[sid] = now + SESSION_TTL
    return sid


def _valid_session(sid: str) -> bool:
    exp = _SESSIONS.get(sid or "")
    if exp is None:
        return False
    if exp < time.time():
        _SESSIONS.pop(sid, None)
        return False
    return True


class LoginThrottle:
    """Per-client lockout: 5 failures lock that client for 5 minutes, doubling on repeat."""

    def __init__(self, limit: int = 5, base_lock: float = 300.0, max_clients: int = 500, clock=time.monotonic):
        self.limit, self.base_lock, self.max_clients, self.clock = limit, base_lock, max_clients, clock
        self._state: dict[str, list] = {}  # client -> [failures, locked_until, lock_count]

    def retry_after(self, client: str) -> int:
        entry = self._state.get(client)
        if not entry:
            return 0
        return max(0, int(entry[1] - self.clock()))

    def failure(self, client: str) -> None:
        if client not in self._state and len(self._state) >= self.max_clients:
            self._state.pop(next(iter(self._state)), None)
        entry = self._state.setdefault(client, [0, 0.0, 0])
        entry[0] += 1
        if entry[0] >= self.limit:
            entry[2] += 1
            entry[1] = self.clock() + self.base_lock * (2 ** (entry[2] - 1))
            entry[0] = 0

    def success(self, client: str) -> None:
        self._state.pop(client, None)


_login_throttle = LoginThrottle()


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _token_ok(presented: str, expected: str) -> bool:
    # Compare digests so neither length nor content leaks through timing.
    import hashlib

    return hmac.compare_digest(hashlib.sha256(presented.encode()).digest(), hashlib.sha256(expected.encode()).digest())


def _authorized(request: Request) -> None:
    settings = get_settings()
    expected = settings.goip_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="GOIP_API_TOKEN is not configured")
    header = request.headers.get("authorization", "")
    presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if presented and _token_ok(presented, expected):
        return
    if _valid_session(request.cookies.get("goip_session", "")):
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _allowed_hosts() -> set[str]:
    return {h.strip().lower() for h in get_settings().goip_allowed_hosts.split(",") if h.strip()}


def _host_only(value: str) -> str:
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]")[0] + "]"
    return value.split(":")[0]


def _status_counts(session: Session) -> list[dict]:
    order = ["high_priority", "qualified", "needs_review", "research_requested", "approved", "rejected", "outreach_drafted", "discovered"]
    rows = session.execute(select(Opportunity.status, func.count()).group_by(Opportunity.status)).all()
    ranked = sorted(rows, key=lambda row: order.index(row[0]) if row[0] in order else len(order))
    return [{"status": status, "count": count} for status, count in ranked]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="GOIP", docs_url=None, redoc_url=None)
    upgrade(engine)

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        # DNS-rebinding defence: only answer to the hostnames we expect.
        if _host_only(request.headers.get("host", "")) not in _allowed_hosts():
            return JSONResponse({"detail": "Host not allowed"}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != "null":
                from urllib.parse import urlparse

                if (urlparse(origin).hostname or "").lower() not in {h.strip("[]") for h in _allowed_hosts()}:
                    return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
                if urlparse(origin).netloc.lower() != request.headers.get("host", "").lower():
                    return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            elif origin == "null":
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            if request.url.path.startswith("/api/") and "application/json" not in request.headers.get("content-type", "").lower():
                return JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            # Pages and assets change between versions. Revalidate (cheap 304) so a browser never mixes an old
            # script or stylesheet with a new page.
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        return response

    @app.get("/health")
    def health():
        runtime = get_runtime()
        return {
            "status": "ok",
            "switch": "connected" if runtime and all(item.is_set() for item in runtime.ready.values()) else "offline",
            "switch_error": runtime.last_error if runtime else "not_started",
        }

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response):
        settings = get_settings()
        client = _client_id(request)
        wait = _login_throttle.retry_after(client)
        if wait:
            raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
        if not settings.goip_api_token or not _token_ok(body.token, settings.goip_api_token):
            _login_throttle.failure(client)
            raise HTTPException(status_code=401, detail="Invalid token")
        _login_throttle.success(client)
        response.set_cookie("goip_session", _new_session(), httponly=True, samesite="strict", secure=False, max_age=SESSION_TTL)
        return {"ok": True}

    @app.get("/api/session")
    def session_state(request: Request):
        """Is this browser signed in? Always answers 200, so the login screen produces no console error."""
        header = request.headers.get("authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        expected = get_settings().goip_api_token
        ok = bool(expected) and ((bool(presented) and _token_ok(presented, expected)) or _valid_session(request.cookies.get("goip_session", "")))
        return {"authenticated": ok}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        _SESSIONS.pop(request.cookies.get("goip_session", ""), None)
        response.delete_cookie("goip_session")
        return {"ok": True}

    @app.get("/api/overview")
    def overview(request: Request, session: Session = Depends(db)):
        _authorized(request)
        runtime_cfg = load_runtime()
        run = session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc()))
        counts = dict(run.counts or {}) if run else {}
        funnel = shortfall(counts, (run.targets if run and run.targets else runtime_cfg["targets"])) if run else {}
        industries = session.execute(select(Company.industry, func.count()).group_by(Company.industry)).all()
        countries = session.execute(select(Company.country, func.count()).group_by(Company.country)).all()
        switch = get_runtime()
        return {
            "llm": {**llm_health(), "message": LLM_MESSAGES.get(llm_health()["reason"], "")},
            "companies": session.scalar(select(func.count()).select_from(Company)) or 0,
            "qualified": session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.status.in_(["qualified", "high_priority", "approved"]))) or 0,
            "high_priority": session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.status == "high_priority")) or 0,
            "latest_run": None
            if run is None
            else {
                "id": run.id,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "switch_status": run.switch_status,
                "telegram_status": run.telegram_status,
                "counts": counts,
                "funnel": funnel,
                "error": run.error,
            },
            "industries": [{"name": name or "Unknown", "count": count} for name, count in industries],
            "countries": [{"name": name or "Unknown", "count": count} for name, count in countries],
            "switch": {
                "connection": "connected" if switch and switch.connected else "offline",
                "room_id": (switch.room.get("id") if switch else None),
                "last_error": switch.last_error if switch else "runtime_not_started",
            },
            "unlinked_signals": session.scalar(select(func.count()).select_from(Signal).where(Signal.company_id.is_(None))) or 0,
            "needs_review": session.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.status == "needs_review")) or 0,
            "status_counts": _status_counts(session),
        }

    @app.get("/api/opportunities")
    def opportunities(
        request: Request,
        session: Session = Depends(db),
        q: str = "",
        status: str = "",
        signal: str = "",
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        _authorized(request)
        stmt = select(Opportunity).join(Company, Company.id == Opportunity.company_id)
        if q:
            stmt = stmt.where(func.lower(Company.name).contains(q.lower()))
        if status:
            stmt = stmt.where(Opportunity.status == status)
        if signal:
            stmt = stmt.where(
                exists().where(Signal.company_id == Opportunity.company_id, Signal.run_id == Opportunity.run_id, Signal.signal_type == signal)
            )
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.scalars(stmt.order_by(Opportunity.score.desc(), Opportunity.public_id).limit(limit).offset(offset)).all()
        payload = []
        for item in rows:
            company = session.get(Company, item.company_id)
            signals = session.scalars(select(Signal).where(Signal.company_id == item.company_id, Signal.run_id == item.run_id)).all()
            payload.append(_opportunity_summary(item, company, signals, session))
        return {"opportunities": payload, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/opportunities/{public_id}")
    def opportunity_detail(public_id: str, request: Request, session: Session = Depends(db)):
        _authorized(request)
        item = session.scalar(select(Opportunity).where(Opportunity.public_id == public_id))
        if item is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        company = session.get(Company, item.company_id)
        signals = session.scalars(select(Signal).where(Signal.company_id == item.company_id, Signal.run_id == item.run_id)).all()
        drafts = session.scalars(select(OutreachDraft).where(OutreachDraft.opportunity_id == item.id)).all()
        decisions = list(session.scalars(select(HumanDecision).where(HumanDecision.opportunity_id == item.id).order_by(HumanDecision.created_at)).all())
        tasks = session.scalars(select(ResearchTask).where(ResearchTask.opportunity_id == item.id).order_by(ResearchTask.created_at)).all()
        events = session.scalars(select(StatusEvent).where(StatusEvent.opportunity_id == item.id).order_by(StatusEvent.created_at)).all()
        versions = _evaluations(session, item.id)
        current = next((row for row in reversed(versions) if row.method == "v2_dimensions"), None)
        return {
            **_opportunity_summary(item, company, signals, session),
            "facts": item.facts,
            "inferences": item.inferences,
            "recommendations": item.recommendations,
            "score_detail": item.score_detail,
            "qa_notes": item.qa_notes,
            "limitations": item.limitations,
            "current_evaluation_id": current.id if current else None,
            "drafts": [{"id": draft.id, "subject": draft.subject, "body": draft.body, "sent": draft.sent} for draft in drafts],
            "decisions": [_decision_payload(row) for row in decisions],
            "research_tasks": [
                {
                    "id": task.id,
                    "status": task.status,
                    "note": task.note,
                    "agents": task.agents,
                    "evaluation_version_id": task.evaluation_version_id,
                    "actor": task.actor,
                    "at": task.created_at.isoformat() if task.created_at else None,
                }
                for task in tasks
            ],
            "status_events": [
                {
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "reason": event.reason,
                    "actor": event.actor,
                    "at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in events
            ],
            "signals": [
                {
                    "id": signal.id,
                    "title": decode_text(signal.title or ""),
                    "parent_domain": signal.parent_domain,
                    "category": signal.category,
                    "discussion_url": _discussion_url(signal),
                    "source_name": signal.source_name,
                    "source_url": signal.source_url,
                    "signal_type": signal.signal_type,
                    "evidence": decode_text(signal.evidence or ""),
                    "raw_evidence": signal.evidence,
                    "published_at": signal.published_at.isoformat() if signal.published_at else None,
                    "retrieved_at": signal.discovered_at.isoformat() if signal.discovered_at else None,
                    "claim_kind": signal.claim_kind,
                    "verification_status": signal.verification_status,
                }
                for signal in signals
            ],
            "evaluations": [_evaluation_payload(row, decisions) for row in versions],
        }

    @app.post("/api/opportunities/{public_id}/decision")
    def decide(public_id: str, body: DecisionBody, request: Request, session: Session = Depends(db)):
        _authorized(request)
        item = _lead(session, public_id)
        from app.review import apply_review

        try:
            result = apply_review(session, item, body.action, body.note, actor="operator", channel="dashboard")
        except GuardrailViolation as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"Not allowed from status {item.status}: {exc.verdict.rule.replace('_', ' ')}") from None
        return {"ok": True, "outreach_sent": False, **result}

    @app.get("/api/reconciliation")
    def reconciliation(request: Request, session: Session = Depends(db)):
        _authorized(request)
        from app.reconciliation import CLASS_MEANING, _companies, classify_signal

        rows = session.scalars(select(SignalReconciliation).order_by(SignalReconciliation.created_at.desc())).all()
        companies = _companies(session)
        linked = {}
        for sig in session.scalars(select(Signal).where(Signal.company_id.is_not(None))).all():
            if sig.source_url:
                linked.setdefault(sig.source_url, set()).add(sig.id)
        signal_counts = dict(session.execute(select(Signal.company_id, func.count()).where(Signal.company_id.is_not(None)).group_by(Signal.company_id)).all())
        lead_for = {}
        for opp in session.scalars(select(Opportunity).order_by(Opportunity.run_id)).all():
            lead_for[opp.company_id] = (opp.public_id, opp.status)
        payload = []
        for row in rows:
            signal = session.get(Signal, row.signal_id)
            company = session.get(Company, row.candidate_company_id) if row.candidate_company_id else None
            # Re-derive the reasoning from the current data. A signal's own URL does not count as "already stored".
            others = {url for url, ids in linked.items() if ids - {row.signal_id}}
            fresh = classify_signal(
                title=signal.title if signal else "",
                identity_hint=signal.identity_hint if signal else "",
                source_url=signal.source_url if signal else "",
                companies=companies,
                linked_urls=others,
            )
            reasoning = fresh["reasoning"]
            candidate = reasoning.get("candidate")
            if candidate is None and company is not None:
                candidate = {"id": company.id, "name": company.name, "domain": company.domain, "basis": "person" if row.human_action else None}
            if candidate:
                lead = lead_for.get(candidate["id"])
                candidate = {**candidate, "stored_signals": int(signal_counts.get(candidate["id"], 0)), "lead_id": lead[0] if lead else None, "lead_status": lead[1] if lead else None}
            payload.append(
                {
                    "signal_id": row.signal_id,
                    "classification": row.classification,
                    "classification_now": fresh["classification"],
                    "confidence": row.confidence,
                    "rationale": row.rationale,
                    "method": row.method,
                    "human_action": row.human_action,
                    "decided_by": row.actor if row.human_action else None,
                    "candidate_company_id": row.candidate_company_id,
                    "candidate_company": company.name if company else None,
                    "title": signal.title if signal else "",
                    "source_name": signal.source_name if signal else "",
                    "source_url": signal.source_url if signal else "",
                    "linked_company_id": signal.company_id if signal else None,
                    "signal_type": signal.signal_type if signal else "",
                    "excerpt": decode_text((signal.evidence or "")[:320]) if signal else "",
                    "published_at": signal.published_at.isoformat() if signal and signal.published_at else None,
                    "classified_at": row.created_at.isoformat() if row.created_at else None,
                    "class_meaning": CLASS_MEANING.get(row.classification, ""),
                    "reasoning": {**reasoning, "candidate": candidate},
                }
            )
        counts = {}
        for item in payload:
            counts[item["classification"]] = counts.get(item["classification"], 0) + 1
        classified_ids = {row.signal_id for row in rows}
        unclassified = sum(
            1 for sig in session.scalars(select(Signal).where(Signal.company_id.is_(None))).all() if sig.id not in classified_ids
        )
        return {
            "unclassified": unclassified,
            "signals": payload,
            "counts": counts,
            "total": len(payload),
            "stored_companies": len(companies),
            "needs_person": sum(1 for p in payload if not p["human_action"] and p["classification"] in {"probable_match", "ambiguous_match"}),
        }

    @app.post("/api/reconciliation/inspect")
    def reconciliation_inspect(request: Request, session: Session = Depends(db)):
        """Classify every unlinked signal that has no row yet. Only a domain match links a signal on its own."""
        _authorized(request)
        from app.reconciliation import record_inspection

        return record_inspection(session)

    @app.post("/api/reconciliation/{signal_id}")
    def reconcile(signal_id: str, body: ReconciliationBody, request: Request, session: Session = Depends(db)):
        _authorized(request)
        try:
            row = apply_human_action(
                session,
                signal_id,
                body.action,
                company_id=body.company_id or None,
                note=body.note,
                actor="operator",
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="Signal not found") from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"ok": True, "classification": row.classification, "company_id": row.candidate_company_id}

    @app.post("/api/opportunities/{public_id}/outreach")
    def outreach(public_id: str, request: Request, session: Session = Depends(db)):
        _authorized(request)
        item = _lead(session, public_id)
        if item.status != "approved":
            raise HTTPException(status_code=409, detail="Approve the lead before drafting outreach")
        company = session.get(Company, item.company_id)
        signal = session.scalar(select(Signal).where(Signal.company_id == item.company_id, Signal.run_id == item.run_id))
        draft = OutreachDraft(
            id=str(uuid.uuid4()),
            opportunity_id=item.id,
            subject=f"A specific note about {company.name if company else 'the company'}",
            body=(
                f"Hello,\n\nI saw a public report that {company.name if company else 'the company'} "
                f"had this development: {signal.summary if signal else 'a recent business signal'} "
                f"({signal.source_url if signal else 'source unavailable'}).\n\n"
                f"That is an observation from the source, not a statement that you are hiring. "
                f"If useful, I can help with {item.recommended_service or 'a scoped technical engagement'}.\n\n"
                "This draft was not sent.\n"
            ),
            sent=False,
        )
        try:
            require(check_status_transition(item.status, "outreach_drafted", "operator"))
        except GuardrailViolation as exc:
            raise HTTPException(status_code=409, detail=exc.verdict.rule.replace("_", " ")) from None
        item.status = "outreach_drafted"
        session.add(draft)
        session.commit()
        return {"ok": True, "sent": False, "body": draft.body}

    @app.get("/api/sources")
    def sources(request: Request, session: Session = Depends(db)):
        _authorized(request)
        rows = session.scalars(select(SourceHealth).order_by(SourceHealth.fetched_at.desc()).limit(100)).all()
        return {
            "sources": [
                {
                    "name": row.name,
                    "parent_domain": row.parent_domain,
                    "category": row.category,
                    "access_method": row.access_method,
                    "status": row.status,
                    "records": row.records,
                    "error": row.error,
                    "fetched_at": row.fetched_at.isoformat(),
                }
                for row in rows
            ]
        }

    @app.get("/api/activity")
    def activity(request: Request, session: Session = Depends(db)):
        _authorized(request)
        messages = session.scalars(select(AgentMessage).order_by(AgentMessage.created_at.desc()).limit(80)).all()
        return {
            "messages": [
                {
                    "agent": row.agent_name,
                    "direction": row.direction,
                    "delivered": row.delivered,
                    "body": row.body,
                    "error": row.error,
                    "at": row.created_at.isoformat(),
                    "event_id": row.switch_event_id,
                }
                for row in messages
            ]
        }

    @app.get("/api/settings")
    def settings_view(request: Request):
        _authorized(request)
        runtime = load_runtime()
        safe = get_settings()
        return {
            "runtime": runtime,
            "integrations": {
                "openrouter": "configured" if safe.openrouter_api_key else "missing",
                "telegram": "configured" if safe.telegram_bot_token and safe.telegram_chat_id else "missing",
                "crawl4ai": "configured" if safe.crawl4ai_api_key else "missing",
                "switch_registration": "configured" if safe.switch_registration_key or safe.switch_env_file else "missing",
            },
        }

    @app.put("/api/settings")
    def settings_update(body: RuntimeBody, request: Request):
        _authorized(request)
        try:
            return save_runtime(body.values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs")
    async def start_run(request: Request, body: RunBody | None = None, session: Session = Depends(db)):
        _authorized(request)
        goal = " ".join((body.goal if body else "").split())
        runtime = get_runtime()
        if runtime and runtime.connected and runtime.room.get("id"):
            run_id = await runtime.collaborative_run("dashboard", goal)
            return {"run_id": run_id, "mode": "switch"}
        run_id = await _local_run(session, goal)
        return {"run_id": run_id, "mode": "local_switch_offline"}

    @app.get("/api/runs/{run_id}/trace")
    def run_trace(run_id: str, request: Request, session: Session = Depends(db)):
        """How each agent decided during a run: its reasoning, the tools it chose, what it saw, and whether the model or the fixed policy did it."""
        _authorized(request)
        from app.agents import memory

        run = session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc())) if run_id == "latest" else session.get(PipelineRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        counts = dict(run.counts or {})
        return {
            "run_id": run.id, "status": run.status, "started_at": run.started_at.isoformat() if run.started_at else None,
            "modes": counts.get("agent_modes") or {}, "sources": counts.get("sources") or [], "judged": counts.get("judged"),
            "trace": memory.trace_for(session, run.id),
        }

    @app.get("/api/runs/{run_id}/export.csv")
    def export_csv(run_id: str, request: Request, session: Session = Depends(db)):
        _authorized(request)
        report = _report_for(session, run_id)
        return Response(read_export(report.csv_path), media_type="text/csv")

    @app.get("/api/runs/{run_id}/export.json")
    def export_json(run_id: str, request: Request, session: Session = Depends(db)):
        _authorized(request)
        report = _report_for(session, run_id)
        return Response(read_export(report.json_path), media_type="application/json")

    @app.get("/api/telegram/identity")
    async def telegram_identity(request: Request):
        _authorized(request)
        settings = get_settings()
        if not settings.telegram_bot_token:
            return {"status": "missing"}
        async with httpx.AsyncClient() as client:
            try:
                identity = await get_me(client, settings.telegram_bot_token)
            except Exception as exc:  # noqa: BLE001
                return {"status": "failed", "error": exc.__class__.__name__}
        return {"status": "authenticated", "username": identity.get("username")}

    frontend = GOIP_ROOT / "frontend"

    @app.get("/app", include_in_schema=False)
    def dashboard_page():
        return FileResponse(frontend / "app.html")

    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


def _lead(session: Session, public_id: str) -> Opportunity:
    item = session.scalar(select(Opportunity).where(Opportunity.public_id == public_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return item


def _report_for(session: Session, run_id: str):
    from app.db import ReportFile

    report = session.scalar(select(ReportFile).where(ReportFile.run_id == run_id))
    if report is None:
        if session.get(PipelineRun, run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        zone = ZoneInfo(load_runtime()["schedule"]["timezone"])
        report = write_report(session, run_id, datetime.now(zone).date().isoformat())
    return report


def _evaluations(session: Session, opportunity_id: str) -> list[EvaluationVersion]:
    return list(
        session.scalars(
            select(EvaluationVersion).where(EvaluationVersion.opportunity_id == opportunity_id).order_by(EvaluationVersion.version)
        ).all()
    )


def _decision_payload(row: HumanDecision) -> dict:
    return {
        "id": row.id,
        "action": row.action,
        "note": row.note,
        "actor": row.actor,
        "channel": row.channel,
        "evaluation_version_id": row.evaluation_version_id,
        "at": row.created_at.isoformat() if row.created_at else None,
    }


def _evaluation_payload(row: EvaluationVersion, decisions: list[HumanDecision] | None = None) -> dict:
    related = [item for item in (decisions or []) if item.evaluation_version_id == row.id]
    return {
        "id": row.id,
        "version": row.version,
        "previous_evaluation_id": row.previous_evaluation_id,
        "config_version": row.config_version,
        "agent_contributions": row.agent_contributions or [],
        "reviews": [_decision_payload(item) for item in related],
        "method": row.method,
        "legacy_score": row.legacy_score,
        "business_signal_score": row.business_signal_score,
        "technical_evidence_score": row.technical_evidence_score,
        "freelance_fit_score": row.freelance_fit_score,
        "confidence": row.confidence,
        "qualification": row.qualification,
        "qa_verdict": row.qa_verdict,
        "findings": row.findings,
        "services": row.services,
        "detail": row.detail,
        "limitations": row.limitations,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


_DISCUSSION = re.compile(r"https://news\.ycombinator\.com/item\?id=\d+")


def _discussion_url(signal: Signal) -> str | None:
    """The Hacker News discussion for a story, when the stored feed text links to it. Never the same as the source."""
    found = _DISCUSSION.search(decode_text(signal.evidence or ""))
    if found and found.group(0) != signal.source_url:
        return found.group(0)
    return None


def _opportunity_summary(item: Opportunity, company: Company | None, signals: list[Signal], session: Session | None = None) -> dict:
    latest = None
    if session is not None:
        versions = _evaluations(session, item.id)
        latest = next((row for row in reversed(versions) if row.method == "v2_dimensions"), None)
    return {
        "id": item.public_id,
        "company": company.name if company else "",
        "website": company.website if company else None,
        "industry": company.industry if company else None,
        "country": company.country if company else None,
        "status": item.status,
        "score": item.score,
        "confidence": latest.confidence if latest else item.confidence,
        "business_signal_score": latest.business_signal_score if latest else None,
        "technical_evidence_score": latest.technical_evidence_score if latest else None,
        "freelance_fit_score": latest.freelance_fit_score if latest else None,
        "qualification": latest.qualification if latest else None,
        "qa_verdict": latest.qa_verdict if latest else None,
        "signal": signals[0].signal_type if signals else None,
        "source_url": signals[0].source_url if signals else None,
        "source_name": signals[0].source_name if signals else None,
        "headline": decode_text(signals[0].title or "") if signals else None,
        "service": item.recommended_service,
        "service_supported": _service_supported(item.recommended_service or "", [row.evidence or "" for row in signals]),
        "commercial_intent": assess_commercial_intent([row.evidence or row.title or "" for row in signals]),
        "technical_need": item.technical_need,
        "why_now": item.why_now,
        "action": item.recommended_action,
    }


async def _local_run(session: Session, goal: str = "") -> str:
    settings = get_settings()
    if settings.goip_graph_enabled:
        from app.graph import run_graph

        return await run_graph(SessionFactory, None, "local", settings, goal)
    runtime = load_runtime()
    run = PipelineRun(
        id=str(uuid.uuid4()),
        status="running",
        trigger="local",
        targets=runtime["targets"],
        counts={},
        switch_status="offline",
        telegram_status="not_started",
        started_at=utcnow(),
    )
    session.add(run)
    session.commit()
    async with httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": "GOIP/0.1"}) as http:
        discovered = await discover(session, http, settings, run)
        await research(session, http, settings, run, discovered["company_ids"])
        repos, _error = await fetch_github(http, int(runtime["fetch_caps"]["github_hits"]))
        attach_github(session, run, repos)
        qualify(session, run)
        quality_check(session, run)
    zone = ZoneInfo(runtime["schedule"]["timezone"])
    write_report(session, run.id, datetime.now(zone).date().isoformat())
    run.status = "completed"
    run.finished_at = utcnow()
    session.commit()
    return run.id


async def handle_telegram_text(text: str, chat_id: str) -> str:
    settings = get_settings()
    if not authorized(chat_id, settings.telegram_chat_id):
        return ""
    command, argument = parse_command(text)
    with SessionFactory() as session:
        if command in {"", "/start", "/help"}:
            return "Commands: /report /top /leads /status /search name /details id /approve id /reject id /outreach id. Outreach is drafted only and never sent."
        if command == "/status":
            run = session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc()))
            if run is None:
                return "No runs yet."
            return f"Run {run.id} status {run.status}. Switch {run.switch_status}. Telegram {run.telegram_status}. Counts {run.counts}."
        if command == "/report":
            run = session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc()))
            if run is None:
                return "No report is available."
            report = _report_for(session, run.id)
            async with httpx.AsyncClient() as client:
                await send_document(client, settings.telegram_bot_token, settings.telegram_chat_id, "report.csv", read_export(report.csv_path), "Latest CSV")
            return f"Report for run {run.id} attached. Counts {run.counts}."
        if command == "/top":
            rows = session.scalars(select(Opportunity).where(Opportunity.status == "high_priority").order_by(Opportunity.score.desc()).limit(5)).all()
            if not rows:
                return "No high-priority leads in the latest stored set."
            lines = []
            for item in rows:
                company = session.get(Company, item.company_id)
                lines.append(f"{item.public_id} {company.name if company else ''} score {item.score} {item.confidence}")
            return "\n".join(lines)
        if command == "/leads":
            rows = session.scalars(select(Opportunity).order_by(Opportunity.score.desc()).limit(10)).all()
            return "\n".join(f"{item.public_id} {item.status} {item.score}" for item in rows) or "No leads."
        if command == "/search":
            rows = session.scalars(select(Company).where(Company.name.ilike(f"%{argument}%")).limit(10)).all()
            return "\n".join(row.name for row in rows) or "No matching company."
        if command == "/details":
            item = session.scalar(select(Opportunity).where(Opportunity.public_id == argument))
            if item is None:
                return "Unknown lead."
            return f"{item.public_id} status {item.status} score {item.score}. {item.why_approach}"
        if command in {"/approve", "/reject"}:
            item = session.scalar(select(Opportunity).where(Opportunity.public_id == argument))
            if item is None:
                return "Unknown lead."
            from app.review import apply_review

            action = "approve" if command == "/approve" else "reject"
            try:
                apply_review(session, item, action, "telegram", actor="operator", channel="telegram")
            except GuardrailViolation as exc:
                session.rollback()
                return f"Cannot {action} {item.public_id} from status {item.status} ({exc.verdict.rule.replace('_', ' ')}). Nothing changed."
            return f"{item.public_id} is {item.status}. Nothing was sent externally."
        if command == "/outreach":
            item = session.scalar(select(Opportunity).where(Opportunity.public_id == argument))
            if item is None:
                return "Unknown lead."
            if item.status != "approved":
                return "Approve the lead first. No draft was created and nothing was sent."
            company = session.get(Company, item.company_id)
            draft = OutreachDraft(
                id=str(uuid.uuid4()),
                opportunity_id=item.id,
                subject=f"Note for {company.name if company else 'company'}",
                body=f"Draft only. Observed context is stored on {item.public_id}. This message was not sent.",
                sent=False,
            )
            try:
                require(check_status_transition(item.status, "outreach_drafted", "operator"))
            except GuardrailViolation:
                return "That lead cannot be drafted from its current status. Nothing was created."
            item.status = "outreach_drafted"
            session.add(draft)
            session.commit()
            return draft.body
    return "Unknown command. Use /help."


app = create_app()
server_started = False
