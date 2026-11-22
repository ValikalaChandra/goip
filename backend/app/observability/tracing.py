from __future__ import annotations

import inspect
import os
from functools import wraps
from typing import Any, Callable

from app.guardrails import Verdict, redact_pii

_client = None


def tracing_enabled() -> bool:
    flag = (os.environ.get("LANGSMITH_TRACING") or "").lower() == "true"
    return flag and bool(os.environ.get("LANGSMITH_API_KEY"))


def _scrub(value: Any, depth: int = 0) -> Any:
    """Remove contact data and cap size before anything leaves this machine."""
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        return redact_pii(value)[:4000]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in ("key", "token", "secret", "password", "authorization")):
                out[key] = "[redacted]"
            else:
                out[key] = _scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item, depth + 1) for item in list(value)[:50]]
    return value


def configure_tracing(settings=None) -> bool:
    """Export .env values to the process and build a redacting client. Returns whether tracing is on."""
    global _client
    from app.config import get_settings

    settings = settings or get_settings()
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
        os.environ.setdefault("LANGSMITH_TRACING", "true" if settings.langsmith_tracing else "false")
    if not tracing_enabled():
        return False
    from langsmith import Client

    _client = Client(hide_inputs=_scrub, hide_outputs=_scrub)
    return True


def traced(name: str, run_type: str = "chain", **tags: str) -> Callable:
    """Decorate an async or sync function as a LangSmith span. A no-op when tracing is off."""

    def decorator(fn: Callable) -> Callable:
        from langsmith import traceable

        wrapped = traceable(
            name=name,
            run_type=run_type,
            tags=[f"{k}:{v}" for k, v in tags.items()],
            client=_client,
        )(fn)

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def adispatch(*args, **kwargs):
                return await (wrapped if tracing_enabled() else fn)(*args, **kwargs)

            return adispatch

        @wraps(fn)
        def dispatch(*args, **kwargs):
            return (wrapped if tracing_enabled() else fn)(*args, **kwargs)

        return dispatch

    return decorator


def record_verdict(verdict: Verdict) -> Verdict:
    """Attach a guardrail verdict to the current span, if there is one."""
    if tracing_enabled():
        try:
            from langsmith.run_helpers import get_current_run_tree

            tree = get_current_run_tree()
            if tree is not None:
                tree.add_metadata({f"guardrail.{verdict.layer}.{verdict.rule}": verdict.as_metadata()})
        except Exception:  # noqa: BLE001  - tracing must never break a run
            pass
    return verdict
