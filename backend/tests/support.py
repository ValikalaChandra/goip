"""Test doubles for the model. A scripted model returns canned replies, so agent behaviour is tested without a real model."""

from __future__ import annotations

from typing import Callable


class ScriptedLLM:
    """Replies are dicts (or None for a failed call) consumed in order, or a callable(system, user) -> dict | None."""

    def __init__(self, replies, available: bool = True):
        self._replies = replies
        self.available = available
        self.calls: list[tuple[str, str]] = []

    async def ask(self, system: str, user: str, *, role: str = "agent"):
        self.calls.append((system, user))
        if callable(self._replies):
            return self._replies(system, user)
        if not self._replies:
            return None
        return self._replies.pop(0)


def step(tool: str, args: dict | None = None, thought: str = "") -> dict:
    return {"thought": thought or f"use {tool}", "tool": tool, "args": args or {}, "final": None}


def final(obj: dict, thought: str = "done") -> dict:
    return {"thought": thought, "tool": None, "args": {}, "final": obj}
