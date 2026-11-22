"""The model as an agent sees it: ask a question, get a JSON object or nothing.

`available` is false when the key is missing or the last call said the account is out of credit, so an agent can
fall back to its fixed policy at once instead of waiting for a call that will fail.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import Settings, load_runtime
from app.guardrails import Budget
from app.integrations.openrouter import complete_json, llm_health
from app.observability import traced


class LLM(Protocol):
    @property
    def available(self) -> bool: ...

    async def ask(self, system: str, user: str, *, role: str = "agent") -> dict | None: ...


class OpenRouterLLM:
    def __init__(self, http: httpx.AsyncClient, settings: Settings, budget: Budget):
        self.http, self.settings, self.budget = http, settings, budget

    @property
    def available(self) -> bool:
        return bool(self.settings.openrouter_api_key) and llm_health().get("ok") is not False

    async def ask(self, system: str, user: str, *, role: str = "agent") -> dict | None:
        if not self.available:
            return None
        self.budget.tick_llm()  # raises BudgetExceeded when the run's model budget is spent
        runtime = load_runtime()
        models = runtime["models"]
        model = models.get(role) or models.get("agent") or models["research"]
        return await self._call(model, runtime["model_fallbacks"], system, user)

    @traced("agent-llm-call", run_type="llm")
    async def _call(self, model: str, fallbacks: list[str], system: str, user: str) -> dict | None:
        parsed, _usage = await complete_json(
            self.http,
            api_key=self.settings.openrouter_api_key,
            model=model,
            fallbacks=fallbacks,
            site_url=self.settings.openrouter_site_url,
            app_name=self.settings.openrouter_app_name,
            system=system,
            user=user,
            max_user_chars=24000,
        )
        return parsed if isinstance(parsed, dict) else None


def unavailable_reason() -> str:
    from app.integrations.openrouter import LLM_MESSAGES

    state = llm_health()
    return state.get("reason") if state.get("ok") is False else ("no key" if state.get("reason") == "unconfigured" else "unknown")
