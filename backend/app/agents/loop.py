from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.guardrails import Budget, Verdict
from app.observability import record_verdict


@dataclass
class LoopResult:
    summary: str
    steps: int
    verdicts: list[Verdict] = field(default_factory=list)
    ok: bool = True


async def act_verify_retry(
    budget: Budget,
    act: Callable[[int], Awaitable[str]],
    verify: Callable[[], Verdict],
    max_steps: int = 2,
) -> LoopResult:
    """Act, check the result against an output guardrail, and retry a bounded number of times.

    A failed final check does not raise: the verdict is returned so the graph can mark the run
    partial and say why. Budget overruns do raise.
    """
    verdicts: list[Verdict] = []
    summary = ""
    for step in range(1, max_steps + 1):
        budget.check_steps(step)
        summary = await act(step)
        verdict = record_verdict(verify())
        verdicts.append(verdict)
        if not verdict.blocked:
            return LoopResult(summary, step, verdicts, True)
    return LoopResult(summary, max_steps, verdicts, False)
