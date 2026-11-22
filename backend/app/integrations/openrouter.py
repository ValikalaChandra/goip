from __future__ import annotations

import json
from typing import Any

import httpx

from app.security.text import fence_untrusted


class OpenRouterError(RuntimeError):
    pass


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
) -> tuple[dict[str, Any] | None, dict]:
    if not api_key:
        return None, {"status": "unconfigured"}
    models = [model, *fallbacks]
    usage: dict[str, Any] = {"status": "failed", "attempts": []}
    for candidate in models:
        body = {
            "model": candidate,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": fence_untrusted(user)},
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
        return parsed, usage
    return None, usage


def quote_supported(quote: str, source: str) -> bool:
    if not quote or not source:
        return False
    return " ".join(quote.split()).lower() in " ".join(source.split()).lower()
