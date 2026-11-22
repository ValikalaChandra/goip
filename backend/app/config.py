from __future__ import annotations

import json
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
    openrouter_site_url: str = "http://127.0.0.1:8001"
    openrouter_app_name: str = "GOIP"


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


def load_runtime() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_runtime(payload: dict) -> dict:
    current = load_runtime()
    allowed = {
        "targets",
        "priority_floor",
        "qualify_score",
        "weights",
        "services",
        "industries",
        "countries",
        "schedule",
        "models",
        "model_fallbacks",
        "fetch_caps",
        "scoring_v2",
    }
    for key, value in payload.items():
        if key in allowed:
            current[key] = value
    weights = current.get("weights") or {}
    total = sum(int(v) for v in weights.values())
    if total != 100:
        raise ValueError(f"Scoring weights must sum to 100, got {total}")
    CONFIG_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
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
