from __future__ import annotations

import asyncio
import logging

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api import SessionFactory, app, handle_telegram_text
from app.config import get_settings, load_runtime
from app.db import upgrade, make_engine
from app.integrations.telegram_api import authorized, authorized_message
from app.switch_runtime import build_runtime, set_runtime

log = logging.getLogger("goip")


async def _telegram_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    if not settings.goip_telegram_polling or not settings.telegram_bot_token:
        return
    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while not stop.is_set():
            try:
                response = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates",
                    params={"timeout": 20, "offset": offset},
                )
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                log.warning("telegram poll failed: %s", exc.__class__.__name__)
                await asyncio.sleep(5)
                continue
            if not payload.get("ok"):
                await asyncio.sleep(5)
                continue
            for update in payload.get("result") or []:
                try:
                    offset = int(update["update_id"]) + 1
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    if not authorized_message(message, settings.telegram_chat_id, settings.telegram_allowed_user_ids):
                        continue
                    text = await handle_telegram_text(message.get("text") or "", str(chat.get("id")))
                    if text:
                        await client.post(
                            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                            json={"chat_id": settings.telegram_chat_id, "text": text[:4000]},
                        )
                except Exception as exc:  # noqa: BLE001 - one bad update must not stop the bot
                    log.warning("telegram update failed: %s", exc.__class__.__name__)
                    if isinstance(update, dict) and "update_id" in update:
                        offset = max(offset, int(update["update_id"]) + 1)


async def _probe_llm() -> None:
    """One tiny model call at startup so an empty balance or a bad key shows up immediately, not after a run."""
    from app.config import load_runtime
    from app.integrations.openrouter import complete_json

    settings = get_settings()
    try:
        runtime = load_runtime()
        async with httpx.AsyncClient() as client:
            await complete_json(
                client,
                api_key=settings.openrouter_api_key,
                model=runtime["models"]["extraction"],
                fallbacks=[],
                site_url=settings.openrouter_site_url,
                app_name=settings.openrouter_app_name,
                system='Reply with exactly {"ok": true}',
                user="ping",
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("model probe failed: %s", exc.__class__.__name__)
    from app.integrations.openrouter import llm_health

    state = llm_health()
    log.info("model probe: ok=%s reason=%s http=%s", state["ok"], state["reason"], state["http"])


async def _scheduled_run() -> None:
    runtime = None
    from app.switch_runtime import get_runtime

    runtime = get_runtime()
    if runtime and runtime.connected:
        await runtime.collaborative_run("schedule")
        return
    from app.api import _local_run

    with SessionFactory() as session:
        await _local_run(session)


@app.on_event("startup")
async def startup() -> None:
    import app.api as api_module

    if api_module.server_started:
        return
    api_module.server_started = True
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    upgrade(make_engine())
    settings = get_settings()
    if 0 < len(settings.goip_api_token) < 24:
        log.warning("GOIP_API_TOKEN is shorter than 24 characters; use a long random token")
    if settings.goip_use_system_certs:
        import truststore

        truststore.inject_into_ssl()
    from app.observability import configure_tracing

    log.info("langsmith tracing %s", "on" if configure_tracing(settings) else "off")
    stop = asyncio.Event()
    app.state.stop = stop
    if settings.goip_switch_enabled:
        runtime = build_runtime(SessionFactory)
        set_runtime(runtime)
        try:
            await runtime.bootstrap()
            await runtime.connect()
            log.info("switch runtime connected room=%s", runtime.room.get("id"))
        except Exception as exc:  # noqa: BLE001
            runtime.last_error = exc.__class__.__name__
            runtime.connected = False
            log.warning("switch runtime unavailable: %s", runtime.last_error)
    if settings.goip_scheduler_enabled:
        schedule = load_runtime()["schedule"]
        scheduler = AsyncIOScheduler(timezone=schedule["timezone"])
        scheduler.add_job(
            _scheduled_run,
            CronTrigger(hour=int(schedule["hour"]), minute=int(schedule["minute"]), timezone=schedule["timezone"]),
            id="goip-daily-report",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
        scheduler.start()
        app.state.scheduler = scheduler
    app.state.telegram = asyncio.create_task(_telegram_loop(stop))
    app.state.llm_probe = asyncio.create_task(_probe_llm())


@app.on_event("shutdown")
async def shutdown() -> None:
    stop = getattr(app.state, "stop", None)
    if stop:
        stop.set()
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    from app.switch_runtime import get_runtime

    runtime = get_runtime()
    if runtime:
        await runtime.close()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.goip_bind_host,
        port=settings.goip_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
