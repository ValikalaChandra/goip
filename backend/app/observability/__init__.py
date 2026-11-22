"""LangSmith tracing for GOIP. Safe to import with no key: tracing is simply off."""

from app.observability.tracing import (
    configure_tracing,
    record_verdict,
    tracing_enabled,
    tracing_scope,
    traced,
)

__all__ = ["configure_tracing", "record_verdict", "tracing_enabled", "tracing_scope", "traced"]
