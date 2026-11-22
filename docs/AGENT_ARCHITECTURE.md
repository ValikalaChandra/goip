# Agent architecture (LangGraph)

The graph in `backend/app/graph/build.py` is the control plane. Switch is a mirror and a human channel.

```text
START -> discover -> research -> technical -> qualify -> strategy -> qa -> finish -> END
              any node with a guardrail failure, timeout or failed self-check -> halt -> END (run = partial)
```

- **Agents** (`app/agents/team.py`): each has a role, a toolbox, and a bounded act -> verify -> retry loop (`agents/loop.py`).
- **Toolbox** (`agents/toolbox.py`): the only route to a tool. Checks the per-agent allowlist and run budget on every call.
- **Guardrails** (`app/guardrails/core.py`): input (size, injection flags, URL safety, PII scrub), tool (allowlist, forbidden tools),
  output (verbatim quote support, claim kind), state (legal status transitions, human-only statuses), run budget
  (model calls, tool calls, steps, time), outreach (send requests refused). Every check returns a `Verdict`.
- **State guard** is enforced in `pipeline._set_status`: an agent cannot set `approved`, `rejected` or `outreach_drafted`.
- **Observability** (`app/observability`): LangSmith spans for the run, each agent and each tool call. Inputs and outputs
  are scrubbed (emails, phone numbers, key-like fields) before upload. Off when no key is set.
- **Checkpointing**: Postgres (`langgraph-checkpoint-postgres`) when the database is Postgres, memory otherwise.
- **Switch**: each step is posted to the room as a plain message. No targeted `GOIP-TASK` is sent, so the legacy socket
  handlers do not run a stage twice. `GOIP_GRAPH_ENABLED=false` restores the legacy chat-driven pipeline.

## Known limits
- Model calls inside `research` are not separate LangSmith spans yet; they appear under `tool:llm_extract_all`.
- Human approval is still a dashboard or Switch action, not a LangGraph `interrupt()`.
- A halted run is not resumed automatically; checkpoints exist but no resume endpoint is exposed.
- The containerised API (`docker compose --profile container up --build`) needs a network where the build can reach PyPI.
  On a TLS-inspecting proxy it fails until the proxy CA is supplied. The default setup runs the API on the host and Postgres in Docker.
