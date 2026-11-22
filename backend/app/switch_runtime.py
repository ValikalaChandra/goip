from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import websockets
from sqlalchemy.orm import Session

from app.config import Settings, get_settings, load_runtime
from app.db import AgentMessage, PipelineRun, utcnow
from app.discovery.sources import fetch_github
from app.exports import write_report
from app.integrations.switch_client import AGENT_SPECS, SwitchClient, load_agent_keys, load_room
from app.integrations.telegram_api import send_document, send_message
from app.pipeline import (
    attach_github,
    attach_repository,
    choose_stored_company,
    discover,
    mark_awaiting_review,
    qualify,
    quality_check,
    refresh_company_research,
    research,
    review_quality,
    review_strategy,
    score_one,
    shortfall,
    _stored_signals,
)

log = logging.getLogger("goip.switch")


def _message_row(session: Session, **kwargs) -> None:
    session.add(AgentMessage(id=str(uuid.uuid4()), created_at=utcnow(), **kwargs))
    session.commit()


class TeamRuntime:
    def __init__(self, session_factory, settings: Settings):
        self.session_factory = session_factory
        self.settings = settings
        self.client = SwitchClient(settings.switch_base_url, agent_keys=load_agent_keys())
        self.room: dict = load_room()
        self.connection_ids = {name: str(uuid.uuid4()) for name, _, _ in AGENT_SPECS}
        self.cursors = {name: 0 for name, _, _ in AGENT_SPECS}
        self.ready = {name: asyncio.Event() for name, _, _ in AGENT_SPECS}
        self.connected = False
        self.stage_events: dict[str, asyncio.Event] = {}
        self.stage_results: dict[str, dict] = {}
        self.tasks: list[asyncio.Task] = []
        self.stop = asyncio.Event()
        self.last_error: str | None = None
        self.http = httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": "GOIP/0.1"})

    async def close(self) -> None:
        self.stop.set()
        for task in self.tasks:
            task.cancel()
        await self.http.aclose()

    async def bootstrap(self) -> dict:
        from app.config import registration_key

        self.client.registration_key = registration_key(self.settings)
        self.client.agent_keys = load_agent_keys()
        healthy = await self.client.health(self.http)
        if not healthy:
            self.last_error = "switch_health_failed"
            return {"ok": False, "error": self.last_error}
        await self.client.register_all(self.http)
        await self.client.allow_owner_agents(self.http)
        self.room = await self.client.ensure_room(self.http)
        self.connected = True
        self.last_error = None
        return {"ok": True, "room": self.room, "agents": list(self.client.agent_keys)}

    async def connect(self) -> None:
        if not self.room.get("id"):
            await self.bootstrap()
        for name, _, _ in AGENT_SPECS:
            self.tasks.append(asyncio.create_task(self._socket_loop(name)))
        try:
            await asyncio.wait_for(asyncio.gather(*(self.ready[name].wait() for name, _, _ in AGENT_SPECS)), timeout=20)
        except TimeoutError:
            missing = [name for name, _, _ in AGENT_SPECS if not self.ready[name].is_set()]
            self.last_error = "sockets_not_ready:" + ",".join(missing)
            self.connected = False
            return
        self.connected = True

    async def _socket_loop(self, name: str) -> None:
        agent_id = self.client.agent_keys[name]["id"]
        key = self.client.agent_keys[name]["api_key"]
        room_id = self.room["id"]
        connection_id = self.connection_ids[name]
        scheme = "wss" if self.client.base_url.startswith("https") else "ws"
        base = self.client.base_url.split("://", 1)[1]
        url = (
            f"{scheme}://{base}/agents/{agent_id}/connection/ws"
            f"?connection_id={connection_id}&rooms={room_id}&scope=single&filter=all"
            "&client=goip&client_version=0.1.0"
        )
        while not self.stop.is_set():
            try:
                async with websockets.connect(
                    url,
                    additional_headers={"Authorization": f"Bearer {key}"},
                    open_timeout=15,
                    ping_interval=None,
                ) as socket:
                    self.connected = True
                    async for raw in socket:
                        message = json.loads(raw)
                        event = message.get("event") or message.get("type")
                        if event == "ping":
                            await socket.send(json.dumps({"type": "pong", "cursor": self.cursors[name]}))
                            continue
                        data = message.get("data") or {}
                        if event == "connection_state":
                            self.cursors[name] = int(data.get("cursor") or 0)
                            self.ready[name].set()
                            if all(item.is_set() for item in self.ready.values()):
                                self.connected = True
                                self.last_error = None
                            continue
                        if event == "message":
                            sequence = data.get("sequence") or message.get("id") or 0
                            self.cursors[name] = max(self.cursors[name], int(sequence or 0))
                            payload = data.get("payload") or {}
                            asyncio.create_task(self._on_message(name, payload))
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", "")
                self.last_error = f"{exc.__class__.__name__}:{code}"
                log.warning("switch socket for %s stopped: %s %s", name, self.last_error, str(exc)[:180])
                await asyncio.sleep(3)

    async def _on_message(self, name: str, payload: dict) -> None:
        try:
            await self._handle_message(name, payload)
        except Exception:  # noqa: BLE001
            log.exception("switch message handler failed for %s", name)

    async def _handle_message(self, name: str, payload: dict) -> None:
        if not payload.get("addressed"):
            return
        sender = payload.get("sender_name") or ""
        if sender == name:
            return
        raw_body = payload.get("body") or ""
        body = protocol_body(raw_body)
        with self.session_factory() as session:
            _message_row(
                session,
                run_id=_run_from(body),
                agent_name=name,
                direction="in",
                room_id=self.room.get("id"),
                body=body[:4000],
                correlation_id=payload.get("message_id"),
                delivered="received",
            )
        if payload.get("sender_kind") == "user" or (sender and sender not in {item[0] for item in AGENT_SPECS}):
            await self._human(name, body, sender)
            return
        if not body.startswith("GOIP-TASK"):
            if body.startswith("GOIP-RESULT"):
                stage = _field(body, "stage")
                event = self.stage_events.get(stage)
                self.stage_results[stage] = {"body": body}
                if event:
                    event.set()
            return
        stage = _field(body, "stage")
        run_id = _field(body, "run_id")
        try:
            summary = await self._perform(name, stage, run_id, body)
            await self._reply(name, "goip-orchestrator", f"GOIP-RESULT v1\nrun_id: {run_id}\nstage: {stage}\nsummary: {summary}")
        except Exception as exc:  # noqa: BLE001
            await self._reply(name, "goip-orchestrator", f"GOIP-RESULT v1\nrun_id: {run_id}\nstage: {stage}\nsummary: failed {exc.__class__.__name__}")

    async def _perform(self, name: str, stage: str, run_id: str, body: str) -> str:
        if stage.startswith("review-"):
            return await self._perform_review(name, stage, body)
        with self.session_factory() as session:
            run = session.get(PipelineRun, run_id)
            if run is None:
                return "run missing"
            if stage == "discover" and name == "goip-discovery":
                result = await discover(session, self.http, self.settings, run)
                return json.dumps(result["counts"])
            if stage == "research" and name == "goip-company-research":
                ids = [item for item in _field(body, "company_ids").split(",") if item]
                result = await research(session, self.http, self.settings, run, ids)
                return f"researched {len(result['company_ids'])}"
            if stage == "technical" and name == "goip-technical-intelligence":
                repos, error = await fetch_github(self.http, int(load_runtime()["fetch_caps"]["github_hits"]))
                result = attach_github(session, run, repos)
                return json.dumps({**result, "error": error})
            if stage == "qualify" and name == "goip-qualification":
                return json.dumps(qualify(session, run))
            if stage == "strategy" and name == "goip-strategy":
                return "strategy notes are on the opportunity records; no external message was sent"
            if stage == "qa" and name == "goip-quality-assurance":
                return json.dumps(quality_check(session, run))
        return "ignored"

    async def _perform_review(self, name: str, stage: str, body: str) -> str:
        from app.db import Company, Opportunity

        company_id = _field(body, "company_id")
        opportunity_id = _field(body, "opportunity_id")
        with self.session_factory() as session:
            opportunity = session.get(Opportunity, opportunity_id)
            company = session.get(Company, company_id) if company_id else None
            if opportunity is None or company is None:
                return "stored company missing"
            signals = _stored_signals(session, company.id)
            if stage == "review-retrieve" and name == "goip-discovery":
                lines = [
                    f"{signal.signal_type}: {(signal.summary or signal.title)[:180]} ({signal.source_url})"
                    for signal in signals[:5]
                ]
                return f"{len(signals)} stored signal(s). " + " | ".join(lines)
            if stage == "review-research" and name == "goip-company-research":
                return await refresh_company_research(session, self.http, self.settings, opportunity, company, signals)
            if stage == "review-technical" and name == "goip-technical-intelligence":
                repos, error = await fetch_github(self.http, int(load_runtime()["fetch_caps"]["github_hits"]))
                note = attach_repository(opportunity, company, repos)
                session.commit()
                return note if not error else f"{note} Repository search error: {error}."
            if stage == "review-qualify" and name == "goip-qualification":
                return score_one(session, opportunity, company, signals)
            if stage == "review-strategy" and name == "goip-strategy":
                return review_strategy(session, opportunity)
            if stage == "review-qa" and name == "goip-quality-assurance":
                return review_quality(session, opportunity, signals)
        return "ignored"

    async def _reply(self, sender: str, target: str, body: str) -> dict:
        try:
            result = await self.client.operate(
                self.http,
                sender,
                "send_targeted_message",
                {"body": body, "target_names": [target]},
                self.connection_ids[sender],
            )
            inner = result.get("result") or result
            delivered = "delivered"
            event_id = str(inner.get("event_id") or "")
            error = None
            statuses = inner.get("target_statuses") or {}
        except Exception as exc:  # noqa: BLE001
            delivered = "failed"
            event_id = ""
            error = str(exc)[:300]
            statuses = {}
        with self.session_factory() as session:
            _message_row(
                session,
                agent_name=sender,
                direction="out",
                room_id=self.room.get("id"),
                body=body[:4000],
                switch_event_id=event_id or None,
                delivered=delivered,
                error=error,
            )
        return {"delivered": delivered, "error": error, "target_statuses": statuses}

    async def collaborative_run(self, trigger: str = "manual") -> str:
        if not self.connected or not self.room.get("id"):
            raise RuntimeError(self.last_error or "switch_not_connected")
        if self.settings.goip_graph_enabled:
            from app.graph import run_graph

            return await run_graph(self.session_factory, self, trigger, self.settings)
        return await self._legacy_collaborative_run(trigger)

    async def _legacy_collaborative_run(self, trigger: str = "manual") -> str:
        runtime = load_runtime()
        run_id = str(uuid.uuid4())
        with self.session_factory() as session:
            session.add(
                PipelineRun(
                    id=run_id,
                    status="running",
                    trigger=trigger,
                    targets=runtime["targets"],
                    counts={},
                    switch_status="connected",
                    started_at=utcnow(),
                )
            )
            session.commit()
        stages = [
            ("discover", "goip-discovery", ""),
            ("research", "goip-company-research", ""),
            ("technical", "goip-technical-intelligence", ""),
            ("qualify", "goip-qualification", ""),
            ("strategy", "goip-strategy", ""),
            ("qa", "goip-quality-assurance", ""),
        ]
        company_ids = ""
        for stage, agent, _extra in stages:
            event = asyncio.Event()
            self.stage_events[stage] = event
            extra = f"\ncompany_ids: {company_ids}" if stage == "research" else ""
            sent = await self._reply("goip-orchestrator", agent, f"GOIP-TASK v1\nrun_id: {run_id}\nstage: {stage}{extra}")
            target_state = (sent.get("target_statuses") or {}).get(agent)
            if sent["delivered"] != "delivered" or target_state in {"no_session", "disconnected", "not_permitted"}:
                with self.session_factory() as session:
                    run = session.get(PipelineRun, run_id)
                    run.status = "partial"
                    run.switch_status = "delivery_failed"
                    run.error = f"{stage}:{target_state or sent.get('error')}"
                    run.finished_at = utcnow()
                    session.commit()
                return run_id
            try:
                await asyncio.wait_for(event.wait(), timeout=_STAGE_TIMEOUTS.get(stage, 240))
            except TimeoutError:
                with self.session_factory() as session:
                    run = session.get(PipelineRun, run_id)
                    run.status = "partial"
                    run.switch_status = "stage_timeout"
                    run.error = stage
                    run.finished_at = utcnow()
                    session.commit()
                return run_id
            if stage == "discover":
                with self.session_factory() as session:
                    run = session.get(PipelineRun, run_id)
                    company_ids = ",".join(_screened_ids(session, run_id))
        await self._finish(run_id)
        return run_id

    async def _finish(self, run_id: str) -> None:
        zone = ZoneInfo(load_runtime()["schedule"]["timezone"])
        report_date = datetime.now(zone).date().isoformat()
        with self.session_factory() as session:
            run = session.get(PipelineRun, run_id)
            report = write_report(session, run_id, report_date)
            counts = dict(run.counts or {})
            funnel = shortfall(counts, run.targets or load_runtime()["targets"])
            text = (
                "Your Global Opportunity Intelligence Report is ready.\n"
                f"Run {run_id}\n"
                f"Discovered {funnel['discovered']['actual']} of target {funnel['discovered']['target']}. "
                f"Screened {funnel['screened']['actual']}. Researched {funnel['researched']['actual']}. "
                f"High priority {funnel['priority']['actual']}.\n"
                "Counts are actual records. Shortfalls are not padded.\n"
                "No external outreach was sent."
            )
            try:
                if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
                    await send_message(self.http, self.settings.telegram_bot_token, self.settings.telegram_chat_id, text)
                    from pathlib import Path

                    await send_document(
                        self.http,
                        self.settings.telegram_bot_token,
                        self.settings.telegram_chat_id,
                        Path(report.csv_path).name,
                        Path(report.csv_path).read_bytes(),
                        "CSV report",
                    )
                    await send_document(
                        self.http,
                        self.settings.telegram_bot_token,
                        self.settings.telegram_chat_id,
                        Path(report.json_path).name,
                        Path(report.json_path).read_bytes(),
                        "JSON report",
                    )
                    report.telegram_status = "delivered"
                    run.telegram_status = "delivered"
                else:
                    report.telegram_status = "unconfigured"
                    run.telegram_status = "unconfigured"
            except Exception as exc:  # noqa: BLE001
                report.telegram_status = "failed"
                run.telegram_status = "failed"
                run.error = exc.__class__.__name__
            run.status = "completed"
            run.switch_status = "delivered"
            run.finished_at = utcnow()
            session.commit()
        await self._reply(
            "goip-orchestrator",
            "goip-quality-assurance",
            f"GOIP-RESULT v1\nrun_id: {run_id}\nstage: complete\nsummary: Report stored. Human review is required before outreach.",
        )

    async def _human(self, name: str, body: str, sender: str) -> None:
        if name != "goip-orchestrator":
            return
        lowered = body.lower()
        if any(
            phrase in lowered
            for phrase in (
                "complete opportunity intelligence",
                "already present in our database",
                "coordinate the relevant specialist",
            )
        ):
            asyncio.create_task(self.single_company_review())
            return
        if any(phrase in lowered for phrase in ("send the email", "send an email", "message them", "send outreach", "linkedin")):
            await self._broadcast(
                "goip-strategy",
                "No external outreach was sent. A draft can be prepared only after the lead is approved, and sending stays a separate human action outside GOIP.",
            )
            return
        from sqlalchemy import select

        from app.db import Company, Opportunity, OutreachDraft, Signal

        with self.session_factory() as session:
            public_id = next((token for token in body.split() if token.startswith("G") and len(token) >= 5), "")
            lead = None
            if public_id:
                lead = session.scalar(select(Opportunity).where(Opportunity.public_id == public_id.strip(".,")))
            if lead is None:
                lead = session.scalar(select(Opportunity).order_by(Opportunity.score.desc()))
            if lead is None:
                await self._broadcast("goip-orchestrator", "I have no stored opportunity to inspect yet.")
                return
            company = session.get(Company, lead.company_id)
            signals = session.scalars(
                select(Signal).where(Signal.company_id == lead.company_id, Signal.run_id == lead.run_id)
            ).all()
            from app.review import apply_review

            if any(phrase in lowered for phrase in ("request additional research", "request research", "more research")):
                apply_review(session, lead, "request_research", body[:500], actor="switch-user", channel="switch")
                await self._broadcast(
                    "goip-orchestrator",
                    f"{lead.public_id} has an open research task for company research, technical intelligence, and discovery. Nothing was sent to the company.",
                )
                return
            if lowered.startswith("approve") or " approve " in f" {lowered} ":
                apply_review(session, lead, "approve", body[:500], actor="switch-user", channel="switch")
                await self._broadcast("goip-orchestrator", f"{lead.public_id} is approved for further consideration. Nothing was sent to the company.")
                return
            if "reject" in lowered:
                apply_review(session, lead, "reject", body[:500], actor="switch-user", channel="switch")
                await self._broadcast("goip-orchestrator", f"{lead.public_id} is rejected. Research history is retained. Nothing was sent.")
                return
            wants_draft = any(phrase in lowered for phrase in ("draft outreach", "prepare outreach", "outreach draft", "write a draft"))
            if wants_draft:
                if lead.status != "approved":
                    await self._broadcast("goip-strategy", f"{lead.public_id} is {lead.status}. I will not draft outreach until it is approved, and I will not send it.")
                    return
                draft = OutreachDraft(
                    id=str(uuid.uuid4()),
                    opportunity_id=lead.id,
                    subject=f"Draft for {company.name if company else lead.public_id}",
                    body=(
                        f"Draft only, not sent. {company.name if company else 'The company'} has this observed signal: "
                        f"{signals[0].summary if signals else 'unavailable'} ({signals[0].source_url if signals else 'no url'}). "
                        f"A possible service to discuss is {lead.recommended_service or 'a scoped technical engagement'}. "
                        "The technical need is an inference, not a published vacancy."
                    ),
                    sent=False,
                )
                lead.status = "outreach_drafted"
                session.add(draft)
                session.commit()
                await self._broadcast("goip-strategy", draft.body)
                return
            source = signals[0].source_url if signals else ""
            quote = signals[0].evidence if signals else ""
            await self._broadcast(
                "goip-company-research",
                (
                    f"Follow-up for {lead.public_id} {company.name if company else ''}. "
                    f"Observed: {quote[:500]} Source: {source}. "
                    f"Inference, not a vacancy: {lead.technical_need}. "
                    f"Recommended service: {lead.recommended_service}. "
                    f"Confidence: {lead.confidence}. Score: {lead.score}. "
                    "No external outreach was sent."
                ),
            )

    async def single_company_review(self) -> None:
        from app.db import Company, Opportunity

        with self.session_factory() as session:
            chosen = choose_stored_company(session)
            if chosen is None:
                await self._broadcast("goip-orchestrator", "No stored company has a usable source. Nothing was contacted.")
                return
            opportunity, company, _signals = chosen
            opportunity_id = opportunity.id
            company_id = company.id
            run_id = opportunity.run_id
            public_id = opportunity.public_id
            company_name = company.name
        await self._broadcast(
            "goip-orchestrator",
            f"Starting an internal review of {company_name} ({public_id}), already in the database. No one will be contacted.",
        )
        stages = [
            ("review-retrieve", "goip-discovery"),
            ("review-research", "goip-company-research"),
            ("review-technical", "goip-technical-intelligence"),
            ("review-qualify", "goip-qualification"),
            ("review-strategy", "goip-strategy"),
            ("review-qa", "goip-quality-assurance"),
        ]
        contributions: list[tuple[str, str]] = []
        for stage, agent in stages:
            event = asyncio.Event()
            self.stage_events[stage] = event
            task = (
                f"GOIP-TASK v1\nrun_id: {run_id}\nstage: {stage}\n"
                f"company_id: {company_id}\nopportunity_id: {opportunity_id}"
            )
            sent = await self._reply("goip-orchestrator", agent, task)
            target_state = (sent.get("target_statuses") or {}).get(agent)
            if sent["delivered"] != "delivered" or target_state in {"no_session", "disconnected", "not_permitted"}:
                contributions.append((agent, f"did not run ({target_state or sent.get('error') or 'not delivered'})"))
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=180 if stage == "review-research" else 90)
                summary = (self.stage_results.get(stage) or {}).get("body") or ""
                line = _field(summary, "summary") or "completed"
            except TimeoutError:
                line = "timed out"
            contributions.append((agent, line))
            await self._broadcast(agent, f"{company_name}: {line[:500]}")
        with self.session_factory() as session:
            opportunity = session.get(Opportunity, opportunity_id)
            company = session.get(Company, company_id)
            if opportunity is None or company is None:
                await self._broadcast("goip-orchestrator", "The stored company disappeared before the report was written.")
                return
            signals = _stored_signals(session, company.id)
            mark_awaiting_review(session, opportunity)
            report = _review_report(company, opportunity, signals, contributions)
        await self._broadcast("goip-orchestrator", report)

    async def _broadcast(self, agent: str, content: str) -> None:
        try:
            result = await self.client.post(self.http, agent, self.room["id"], content)
            delivered = "delivered" if result.get("ok") else "failed"
            event_id = str(result.get("event_id") or "")
            error = None
        except Exception as exc:  # noqa: BLE001
            delivered = "failed"
            event_id = ""
            error = str(exc)[:300]
        with self.session_factory() as session:
            _message_row(
                session,
                agent_name=agent,
                direction="out",
                room_id=self.room.get("id"),
                body=content[:4000],
                switch_event_id=event_id or None,
                delivered=delivered,
                error=error,
            )


_STAGE_TIMEOUTS = {
    "discover": 300,
    "research": 900,
    "technical": 180,
    "qualify": 120,
    "strategy": 60,
    "qa": 120,
}


def _review_report(company, opportunity, signals, contributions: list[tuple[str, str]]) -> str:
    evidence = []
    for signal in signals[:4]:
        quote = (signal.evidence or signal.summary or signal.title or "").replace("\n", " ").strip()
        evidence.append(f"- {signal.signal_type} ({signal.source_name}): {quote[:280]} Source: {signal.source_url}")
    if not evidence:
        evidence.append("- No stored source was linked.")
    agents = "\n".join(f"- {name}: {text[:400]}" for name, text in contributions)
    detail = opportunity.score_detail or {}
    explanation = detail.get("explanation") or []
    explained = " ".join(str(item) for item in explanation) or "No score explanation was stored."
    questions = []
    if not company.website:
        questions.append("The company website was not stored.")
    if not company.industry:
        questions.append("The sources do not state an industry.")
    if not company.country:
        questions.append("The sources do not state a country.")
    if not opportunity.oss_url:
        questions.append("No matching public repository was found in this search.")
    questions.append("The technical need is an inference. The sources do not show an open freelance contract.")
    questions.append("A human still has to decide whether the evidence is worth any later contact.")
    return (
        f"Internal review of {company.name} ({opportunity.public_id}). Awaiting human review.\n"
        "No one was contacted and no outreach was sent.\n\n"
        f"Business model and products: {company.description or 'Not stated by the stored sources.'}\n"
        f"Industry: {company.industry or 'not stated'}. Country: {company.country or 'not stated'}.\n\n"
        "Evidence\n"
        + "\n".join(evidence)
        + "\n\nAgent contributions\n"
        + agents
        + "\n\n"
        f"Opportunity score: {opportunity.score if opportunity.score is not None else 'not scored'}. "
        f"Confidence: {opportunity.confidence}.\n"
        f"{explained}\n"
        f"Recommended service: {opportunity.recommended_service or 'not assigned'}.\n"
        f"QA: {opportunity.qa_notes or 'not recorded'}\n\n"
        "Unresolved questions\n"
        + "\n".join(f"- {item}" for item in questions)
        + f"\n\nStatus: {opportunity.status}. {opportunity.status_reason}"
    )


def protocol_body(body: str) -> str:
    """Drop the @mentions Switch prepends to a targeted message."""
    for marker in ("GOIP-TASK", "GOIP-RESULT"):
        index = body.find(marker)
        if index >= 0:
            return body[index:]
    return body


def _field(body: str, name: str) -> str:
    prefix = name + ":"
    for line in body.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def _run_from(body: str) -> str | None:
    value = _field(body, "run_id")
    return value or None


def _screened_ids(session: Session, run_id: str) -> list[str]:
    from app.db import Signal

    rows = session.query(Signal.company_id).filter(Signal.run_id == run_id, Signal.company_id.is_not(None), Signal.signal_type != "other").distinct()
    return [row[0] for row in rows]


_runtime: TeamRuntime | None = None


def get_runtime() -> TeamRuntime | None:
    return _runtime


def set_runtime(runtime: TeamRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def build_runtime(session_factory) -> TeamRuntime:
    return TeamRuntime(session_factory, get_settings())
