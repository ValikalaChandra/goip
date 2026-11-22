"""LangSmith tracing with mandatory redaction.

Nothing leaves the machine unless it has passed `_scrub`:
- objects that are not plain data (settings, runtimes, sessions, clients) become a type placeholder;
- dict keys that look secret are redacted, string values are checked for token shapes and contact data;
- redaction is applied per span (process_inputs / process_outputs), not only on a client, so a span can
  never be uploaded without it, and LangGraph's own auto-trace runs through a scrubbing client.
"""

from __future__ import annotations

import inspect
import os
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator

from app.guardrails import Verdict, redact_pii, redact_secrets

_SENSITIVE_KEY = ("key", "token", "secret", "password", "authorization", "cookie", "credential")
_PRIMITIVES = (int, float, bool, type(None))
_enabled = False
_client = None


def tracing_enabled() -> bool:
    return _enabled


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        return redact_pii(redact_secrets(value))[:4000]
    if isinstance(value, _PRIMITIVES):
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key)
            if any(word in name.lower() for word in _SENSITIVE_KEY):
                out[name] = "[redacted]"
            else:
                out[name] = _scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_scrub(item, depth + 1) for item in list(value)[:50]]
    # Anything else (Settings, TeamRuntime, Session, httpx client, pydantic models): never serialise it.
    return f"<{type(value).__name__}>"


def get_client():
    """The one client used for every upload. Built lazily so import order cannot bypass redaction."""
    global _client
    if _client is None and _enabled:
        from langsmith import Client

        _client = Client(hide_inputs=_scrub, hide_outputs=_scrub, hide_metadata=_scrub)
    return _client


def configure_tracing(settings=None) -> bool:
    """Turn tracing on only when a key and the flag are set. The key goes to the env; the flag does not."""
    global _enabled
    from app.config import get_settings

    settings = settings or get_settings()
    explicit_off = (os.environ.get("LANGSMITH_TRACING") or "").lower() == "false"
    _enabled = bool(settings.langsmith_api_key) and settings.langsmith_tracing and not explicit_off
    if not _enabled:
        return False
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    # Deliberately not exporting LANGSMITH_TRACING: with it set, any LangChain/LangGraph code outside
    # `tracing_scope()` would auto-trace through an unscrubbed default client.
    os.environ.pop("LANGSMITH_TRACING", None)
    os.environ.pop("LANGCHAIN_TRACING_V2", None)
    get_client()
    return True


@contextmanager
def tracing_scope() -> Iterator[None]:
    """Enable tracing for everything inside, through the scrubbing client. A no-op when tracing is off."""
    if not _enabled:
        yield
        return
    from langsmith import tracing_context

    with tracing_context(enabled=True, client=get_client()):
        yield


def traced(name: str, run_type: str = "chain", **tags: str) -> Callable:
    """Decorate an async or sync function as a LangSmith span. A no-op when tracing is off."""

    def decorator(fn: Callable) -> Callable:
        from langsmith import traceable

        wrapped = traceable(
            name=name,
            run_type=run_type,
            tags=[f"{k}:{v}" for k, v in tags.items()],
            process_inputs=_scrub,
            process_outputs=_scrub,
        )(fn)

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def adispatch(*args, **kwargs):
                return await (wrapped if _enabled else fn)(*args, **kwargs)

            return adispatch

        @wraps(fn)
        def dispatch(*args, **kwargs):
            return (wrapped if _enabled else fn)(*args, **kwargs)

        return dispatch

    return decorator


def record_verdict(verdict: Verdict) -> Verdict:
    """Attach a guardrail verdict to the current span, if there is one."""
    if _enabled:
        try:
            from langsmith.run_helpers import get_current_run_tree

            tree = get_current_run_tree()
            if tree is not None:
                tree.add_metadata({f"guardrail.{verdict.layer}.{verdict.rule}": _scrub(verdict.as_metadata())})
        except Exception:  # noqa: BLE001 - tracing must never break a run
            pass
    return verdict
