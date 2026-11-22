from __future__ import annotations

import inspect
from typing import Any, Callable

from app.guardrails import Budget, check_tool_call, require
from app.observability import record_verdict, traced


class ToolBox:
    """The only way an agent reaches a tool. Enforces the allowlist and the run budget on every call."""

    def __init__(self, agent: str, budget: Budget, tools: dict[str, Callable]):
        self.agent = agent
        self.budget = budget
        self._tools = tools

    async def call(self, tool: str, *args: Any, **kwargs: Any) -> Any:
        require(record_verdict(check_tool_call(self.agent, tool)))
        if tool not in self._tools:
            raise KeyError(f"{self.agent}: tool {tool} is allowed but not wired")
        self.budget.tick_tool()

        @traced(f"tool:{tool}", run_type="tool", agent=self.agent)
        async def _run() -> Any:
            result = self._tools[tool](*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return await _run()
