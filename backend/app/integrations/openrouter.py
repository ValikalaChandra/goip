from __future__ import annotations

import json
from typing import Any

import httpx

from app.security.text import fence_untrusted


class OpenRouterError(RuntimeError):
    pass


# What the last model call said, so a dead key or an empty balance is visible instead of silently degrading features.
LLM_STATE: dict = {"ok": None, "reason": "not_checked", "http": None, "at": None, "model": None}

_REASONS = {402: "out_of_credit", 401: "key_rejected", 403: "key_rejected", 429: "rate_limited"}


def _record(ok: bool | None, usage: dict) -> None:
    from datetime import datetime, timezone

    reason = "ok" if ok else "unavailable"
    http = None
    if ok is None:
        reason = "unconfigured"
    elif not ok:
        statuses = [a.get("status") for a in usage.get("attempts", []) if isinstance(a.get("status"), int)]
        for code in (402, 401, 403, 429):  # the most actionable cause wins
            if code in statuses:
                reason, http = _REASONS[code], code
                break
    LLM_STATE.update({"ok": ok, "reason": reason, "http": http, "at": datetime.now(timezone.utc).isoformat(), "model": usage.get("model")})


def llm_health() -> dict:
    return dict(LLM_STATE)


LLM_MESSAGES = {
    "out_of_credit": "OpenRouter reports no credit (HTTP 402). Add credit at openrouter.ai/credits.",
    "key_rejected": "OpenRouter rejected the API key. Check OPENROUTER_API_KEY.",
    "rate_limited": "OpenRouter is rate limiting this key. Try again shortly.",
    "unavailable": "The language model did not answer.",
    "unconfigured": "No OpenRouter key is configured.",
}


async def complete_json(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    fallbacks: list[str],
    system: str,
    user: str,
    site_url: str,
    app_name: str,
    max_user_chars: int = 8000,
) -> tuple[dict[str, Any] | None, dict]:
    if not api_key:
        usage = {"status": "unconfigured"}
        _record(None, usage)
        return None, usage
    models = [model, *fallbacks]
    usage: dict[str, Any] = {"status": "failed", "attempts": []}
    for candidate in models:
        body = {
            "model": candidate,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": fence_untrusted(user, max_user_chars)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": site_url,
                    "X-Title": app_name,
                },
                content=json.dumps(body),
                timeout=60,
            )
        except httpx.HTTPError as exc:
            usage["attempts"].append({"model": candidate, "error": exc.__class__.__name__})
            continue
        if response.status_code in {404, 400}:
            usage["attempts"].append({"model": candidate, "status": response.status_code})
            continue
        if response.status_code >= 400:
            usage["attempts"].append({"model": candidate, "status": response.status_code})
            continue
        payload = response.json()
        content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            usage["attempts"].append({"model": candidate, "error": "invalid_json"})
            continue
        token_usage = payload.get("usage") or {}
        usage.update(
            {
                "status": "ok",
                "model": candidate,
                "prompt_tokens": token_usage.get("prompt_tokens"),
                "completion_tokens": token_usage.get("completion_tokens"),
                "cost": token_usage.get("cost"),
            }
        )
        _record(True, usage)
        return parsed, usage
    _record(False, usage)
    return None, usage


def quote_supported(quote: str, source: str) -> bool:
    if not quote or not source:
        return False
    return " ".join(quote.split()).lower() in " ".join(source.split()).lower()
