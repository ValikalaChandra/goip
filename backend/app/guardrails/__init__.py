"""Guardrails applied at every agent boundary.

Every check returns a Verdict. A blocking verdict stops the stage and the run
becomes `partial`; nothing continues silently. Verdicts are also attached to
LangSmith spans (see app.observability).
"""

from app.guardrails.core import (
    AGENT_TOOLS,
    ALLOWED_TRANSITIONS,
    FORBIDDEN_TOOLS,
    Budget,
    BudgetExceeded,
    GuardrailViolation,
    Verdict,
    check_input_text,
    check_outreach_request,
    check_source_url,
    check_status_transition,
    check_tool_call,
    check_grounded_output,
    redact_pii,
    require,
)

__all__ = [
    "AGENT_TOOLS",
    "ALLOWED_TRANSITIONS",
    "FORBIDDEN_TOOLS",
    "Budget",
    "BudgetExceeded",
    "GuardrailViolation",
    "Verdict",
    "check_input_text",
    "check_outreach_request",
    "check_source_url",
    "check_status_transition",
    "check_tool_call",
    "check_grounded_output",
    "redact_pii",
    "require",
]
