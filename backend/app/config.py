from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GOIP_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = GOIP_ROOT / "data"
EXPORT_DIR = DATA_DIR / "exports"
SECRET_DIR = DATA_DIR / "secrets"
CONFIG_PATH = GOIP_ROOT / "config" / "runtime.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(GOIP_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # `.env.example` ships empty values; an empty bool must not crash startup
    )

    goip_api_token: str = ""
    goip_bind_host: str = "127.0.0.1"
    goip_port: int = 8001
    goip_database_url: str = f"sqlite:///{DATA_DIR / 'goip.db'}"
    openrouter_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    crawl4ai_api_key: str = ""
    crawl4ai_base_url: str = "https://api.crawl4ai.com"
    switch_base_url: str = "http://127.0.0.1:50990"
    switch_gateway_url: str = "http://127.0.0.1:50989"
    switch_registration_key: str = ""
    switch_env_file: str = ""
    goip_scheduler_enabled: bool = True
    goip_switch_enabled: bool = True
    goip_telegram_polling: bool = True
    langsmith_api_key: str = ""
    langsmith_tracing: bool = True
    langsmith_project: str = "goip"
    goip_graph_enabled: bool = True
    # Opt in on networks with a TLS-inspecting proxy whose CA is in the OS trust store.
    goip_use_system_certs: bool = False
    # Hostnames (no port) the API will answer to. Blocks DNS-rebinding pages from reaching it.
    # Comma-separated Switch display names allowed to approve/reject/request research/draft from the room.
    # Empty = any room member may (the room is a public channel). Set this once you know your Switch username.
    goip_room_approvers: str = ""
    # Telegram user ids allowed to act from a GROUP chat (a private chat needs no list). Empty = nobody in a group.
    telegram_allowed_user_ids: str = ""
    goip_allowed_hosts: str = "127.0.0.1,localhost,[::1],host.docker.internal,testserver"
    openrouter_site_url: str = "http://127.0.0.1:8001"
    openrouter_app_name: str = "GOIP"


@lru_cache
def get_settings() -> Settings:
    for directory in (DATA_DIR, EXPORT_DIR, SECRET_DIR):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Settings()


def load_runtime() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
_SAVE_LOCK = threading.Lock()
_ALLOWED_KEYS = {
    "targets", "priority_floor", "qualify_score", "weights", "services", "industries", "countries",
    "schedule", "models", "model_fallbacks", "fetch_caps", "scoring_v2", "focus",
}


def _int_in(name: str, value, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(f"{name} must be a whole number")
    if not low <= int(value) <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return int(value)


def validate_runtime(current: dict) -> dict:
    """Type- and range-check the whole runtime config. Raises ValueError with a safe message."""
    if not isinstance(current, dict):
        raise ValueError("config must be an object")
    targets = current.get("targets")
    if not isinstance(targets, dict) or set(targets) - {"discovered", "screened", "researched", "priority"}:
        raise ValueError("targets must be an object with discovered, screened, researched, priority")
    for key in ("discovered", "screened", "researched", "priority"):
        _int_in(f"targets.{key}", targets.get(key, 0), 0, 1000)
    caps = current.get("fetch_caps")
    if not isinstance(caps, dict):
        raise ValueError("fetch_caps must be an object")
    for key, value in caps.items():
        _int_in(f"fetch_caps.{key}", value, 0, 200)
    weights = current.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ValueError("weights must be an object")
    for key, value in weights.items():
        _int_in(f"weights.{key}", value, 0, 100)
    total = sum(int(v) for v in weights.values())
    if total != 100:
        raise ValueError(f"Scoring weights must sum to 100, got {total}")
    _int_in("priority_floor", current.get("priority_floor", 0), 0, 100)
    _int_in("qualify_score", current.get("qualify_score", 0), 0, 100)
    schedule = current.get("schedule")
    if not isinstance(schedule, dict):
        raise ValueError("schedule must be an object")
    _int_in("schedule.hour", schedule.get("hour"), 0, 23)
    _int_in("schedule.minute", schedule.get("minute"), 0, 59)
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(str(schedule.get("timezone")))
    except Exception:  # noqa: BLE001
        raise ValueError("schedule.timezone is not a valid time zone") from None
    models = current.get("models")
    if not isinstance(models, dict):
        raise ValueError("models must be an object")
    for key, value in models.items():
        if not isinstance(value, str) or not _MODEL_ID.match(value):
            raise ValueError(f"models.{key} is not a valid model id")
    fallbacks = current.get("model_fallbacks")
    if not isinstance(fallbacks, list) or len(fallbacks) > 5 or not all(isinstance(m, str) and _MODEL_ID.match(m) for m in fallbacks):
        raise ValueError("model_fallbacks must be up to 5 valid model ids")
    for key in ("services", "industries", "countries"):
        values = current.get(key)
        if not isinstance(values, list) or len(values) > 50 or not all(isinstance(v, str) and 0 < len(v) <= 100 for v in values):
            raise ValueError(f"{key} must be a list of up to 50 short strings")
    focus = current.get("focus", {})
    if not isinstance(focus, dict) or set(focus) - {"term", "sector"}:
        raise ValueError("focus must be an object with an optional term and sector")
    term = focus.get("term")
    if term is not None and (not isinstance(term, str) or not FOCUS_TERM_RE.match(term)):
        raise ValueError("focus.term must be short plain text (letters, digits, spaces and & . , + ' # -)")
    sector = focus.get("sector")
    if sector is not None and (not isinstance(sector, str) or sector not in FOCUS_SECTORS):
        raise ValueError("focus.sector must be null or one of: " + ", ".join(sorted(FOCUS_SECTORS)))
    return current


FOCUS_TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &.,+'#-]{0,59}$")
FOCUS_SECTORS = {"fintech", "healthtech", "edtech", "cybersecurity", "logistics", "climate", "ecommerce", "saas", "ai"}


def save_runtime(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("values must be an object")
    with _SAVE_LOCK:
        current = load_runtime()
        for key, value in payload.items():
            if key in _ALLOWED_KEYS:
                current[key] = value
        validate_runtime(current)
        fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), prefix=".runtime-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(current, indent=2) + "\n")
            os.replace(tmp, CONFIG_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return current


def registration_key(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if settings.switch_registration_key.strip():
        return settings.switch_registration_key.strip()
    path = settings.switch_env_file.strip()
    secret_file = SECRET_DIR / "registration.key"
    if secret_file.is_file():
        return secret_file.read_text(encoding="utf-8").strip()
    if not path:
        return ""
    file = Path(path)
    if not file.is_file():
        return ""
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("AGENT_REGISTRATION_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""
