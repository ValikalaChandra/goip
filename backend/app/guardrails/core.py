from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.integrations.openrouter import quote_supported
from app.security.text import injection_flags
from app.security.url_safety import UnsafeURL, check_url


class GuardrailViolation(RuntimeError):
    def __init__(self, verdict: "Verdict"):
        super().__init__(f"{verdict.layer}:{verdict.rule}: {verdict.detail}")
        self.verdict = verdict


class BudgetExceeded(GuardrailViolation):
    pass


@dataclass(frozen=True)
class Verdict:
    layer: str  # input | tool | output | state | run | outreach
    rule: str
    ok: bool
    detail: str = ""
    block: bool = True  # a failed non-blocking verdict is a warning only

    @property
    def blocked(self) -> bool:
        return (not self.ok) and self.block

    def as_metadata(self) -> dict:
        return {"layer": self.layer, "rule": self.rule, "ok": self.ok, "detail": self.detail[:300]}


def require(verdict: Verdict) -> Verdict:
    if verdict.blocked:
        raise GuardrailViolation(verdict)
    return verdict


# ---------------------------------------------------------------- input layer

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")
MAX_INPUT_CHARS = 20_000


_SECRET_VALUES = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|lsv2_[A-Za-z0-9_]{10,}|\b\d{8,10}:AA[\w-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"Bearer\s+\S+|\b[A-Za-z0-9_-]{40,}\b)"
)


def _is_url_slug(token: str) -> bool:
    """A long lowercase-hyphen word run like an article slug is not a credential."""
    return token.count("-") >= 3 and re.fullmatch(r"[a-z0-9-]+", token) is not None


def redact_secrets(text: str) -> str:
    """Remove token-shaped strings. Long opaque tokens are redacted even if their vendor is unknown,
    except readable URL slugs, which would otherwise corrupt every long article link."""
    return _SECRET_VALUES.sub(lambda m: m.group(0) if _is_url_slug(m.group(0)) else "[redacted]", text or "")


def redact_pii(text: str) -> str:
    """Remove personal contact data before text reaches a model or a trace."""
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text or ""))


def check_input_text(text: str, *, limit: int = MAX_INPUT_CHARS) -> Verdict:
    if len(text or "") > limit:
        return Verdict("input", "size_limit", False, f"{len(text)} chars exceeds {limit}")
    flags = injection_flags(text or "")
    if flags:
        # Not blocking: the text is fenced and flagged, never obeyed.
        return Verdict("input", "injection_phrases", False, "; ".join(flags[:5]), block=False)
    return Verdict("input", "clean", True)


def check_source_url(url: str, *, resolve=None) -> Verdict:
    try:
        kwargs = {"resolve": resolve} if resolve else {}
        check_url(url, **kwargs)
    except UnsafeURL as exc:
        return Verdict("input", "unsafe_url", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        return Verdict("input", "unsafe_url", False, exc.__class__.__name__)
    return Verdict("input", "safe_url", True)


# ----------------------------------------------------------------- tool layer

AGENT_TOOLS: dict[str, frozenset[str]] = {
    # Perception tools only read. `submit_verdicts` is the single narrow write an agent has: it validates every
    # verdict against the posting's own text before storing it, and a verdict is never a score.
    "goip-discovery": frozenset({"fetch_and_group", "read_store", "list_sources", "fetch_source", "source_stats"}),
    "goip-company-research": frozenset({"llm_extract_all", "read_store", "read_signals", "fetch_stored_page", "quote_check"}),
    "goip-technical-intelligence": frozenset({"search_and_attach", "read_store", "github_search", "github_repo", "read_company"}),
    "goip-qualification": frozenset({"score_all", "read_store", "list_postings", "reviewer_examples", "submit_verdicts"}),
    "goip-strategy": frozenset({"read_store", "read_evaluation", "list_services"}),
    "goip-quality-assurance": frozenset({"audit_all", "read_store", "read_evaluation", "read_opportunity", "recheck_source"}),
    "goip-orchestrator": frozenset({"post_room_message", "write_report", "send_report_to_operator", "read_store", "source_stats", "read_trace"}),
}

# No agent, under any prompt, may hold a tool that contacts a third party.
FORBIDDEN_TOOLS = frozenset(
    {"send_email", "send_message_external", "linkedin_message", "post_public", "submit_form", "shell", "write_score"}
)


def check_tool_call(agent: str, tool: str) -> Verdict:
    if tool in FORBIDDEN_TOOLS:
        return Verdict("tool", "forbidden_tool", False, f"{tool} is never available")
    allowed = AGENT_TOOLS.get(agent)
    if allowed is None:
        return Verdict("tool", "unknown_agent", False, agent)
    if tool not in allowed:
        return Verdict("tool", "not_in_allowlist", False, f"{agent} may not call {tool}")
    return Verdict("tool", "allowed", True)


# --------------------------------------------------------------- output layer

CLAIM_KINDS = {"observed", "inference", "hypothesis", "unknown"}


def check_grounded_output(claim_kind: str, quote: str, source_text: str) -> Verdict:
    """An observed claim must quote its source; everything else must say it is not observed."""
    if claim_kind not in CLAIM_KINDS:
        return Verdict("output", "claim_kind", False, f"unknown kind {claim_kind!r}")
    if claim_kind == "observed":
        if not quote or not quote_supported(quote, source_text):
            return Verdict("output", "quote_not_in_source", False, "observed claim has no verbatim support")
    return Verdict("output", "grounded", True)


# ---------------------------------------------------------------- state layer

ALLOWED_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"screening", "discovered"}),
    "discovered": frozenset({"screening"}),
    "screening": frozenset({"researching", "needs_review"}),
    "researching": frozenset({"researching", "qualified", "needs_review"}),
    "qualified": frozenset({"high_priority", "needs_review", "approved", "rejected", "research_requested"}),
    "high_priority": frozenset({"needs_review", "approved", "rejected", "research_requested"}),
    "needs_review": frozenset({"approved", "rejected", "research_requested", "qualified", "researching"}),
    "research_requested": frozenset({"researching", "needs_review", "approved", "rejected"}),
    "approved": frozenset({"outreach_drafted", "rejected", "needs_review"}),
    "outreach_drafted": frozenset({"rejected", "approved"}),
    "rejected": frozenset({"needs_review"}),
}

# Only a person may move a lead into these.
HUMAN_ONLY = frozenset({"approved", "rejected", "outreach_drafted"})


def check_status_transition(current: str | None, target: str, actor: str) -> Verdict:
    if current == target:
        return Verdict("state", "no_change", True)
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return Verdict("state", "illegal_transition", False, f"{current} -> {target}")
    if target in HUMAN_ONLY and actor.startswith("goip-"):
        return Verdict("state", "human_only_status", False, f"{actor} cannot set {target}")
    return Verdict("state", "legal_transition", True)


# -------------------------------------------------------------- outreach layer

_OUTREACH = re.compile(
    r"(send (the |an? |a )?(email|mail|message|dm|note)|(e-?mail|dm|ping|text|call|write to|get in touch with|reach out to|reach out) (them|the (ceo|founder|company|team))|"
    r"message them|send outreach|linkedin|cold (email|call)|contact (them|the company))",
    re.I,
)


def check_outreach_request(text: str) -> Verdict:
    if _OUTREACH.search(text or ""):
        return Verdict("outreach", "send_refused", False, "GOIP has no capability to contact companies")
    return Verdict("outreach", "no_send_request", True)


# ------------------------------------------------------------------ run budget


@dataclass
class Budget:
    """Hard limits for one run. Exceeding any limit ends the run as partial."""

    max_llm_calls: int = 120
    max_tool_calls: int = 600
    max_seconds: float = 3600.0
    max_agent_steps: int = 6
    llm_calls: int = 0
    tool_calls: int = 0
    started: float = field(default_factory=time.monotonic)

    def _fail(self, rule: str, detail: str) -> None:
        raise BudgetExceeded(Verdict("run", rule, False, detail))

    def tick_llm(self) -> None:
        self.llm_calls += 1
        if self.llm_calls > self.max_llm_calls:
            self._fail("llm_call_budget", f"more than {self.max_llm_calls} model calls")
        self._clock()

    def reserve_llm(self, n: int) -> None:
        """Check the budget before a stage that will make n model calls."""
        if self.llm_calls + n > self.max_llm_calls:
            self._fail("llm_call_budget", f"{n} more calls would exceed {self.max_llm_calls}")
        self.llm_calls += n
        self._clock()

    def tick_tool(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            self._fail("tool_call_budget", f"more than {self.max_tool_calls} tool calls")
        self._clock()

    def check_steps(self, steps: int) -> None:
        if steps > self.max_agent_steps:
            self._fail("agent_step_budget", f"agent looped {steps} times, limit {self.max_agent_steps}")

    def _clock(self) -> None:
        if time.monotonic() - self.started > self.max_seconds:
            self._fail("time_budget", f"run exceeded {self.max_seconds:.0f}s")
