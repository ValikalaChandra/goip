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

## Human interaction
Every agent replies to humans (`app/agents/chat.py`), read-only, deterministic, no model call. The orchestrator additionally handles
`run`, `status`, `focus`, and the exact-grammar lead commands; ambiguous free text goes through `app/agents/router.py`, where a model picks one
of `run | status | focus | clear_focus | lead_question | help` and its output is validated against that enum.
State-changing commands need the command first, an explicit lead id, a legal status transition, and (if configured) an allowlisted approver.

## Agents, not functions

Every stage is an agent with a goal, tools it can choose from, a bounded loop, memory, and an answer that must be
checked. `app/agents/runtime.py` is the one loop they all run through:

```text
perceive -> the model proposes ONE step: a tool call or a final answer
check    -> tool in the allowlist? arguments valid? repeated call? step budget? model budget?
act      -> the runtime runs the tool (read-only) and fences the result as untrusted text
repeat   -> up to a hard step limit
answer   -> must match the agent's schema AND pass its grounding check, or it is sent back
remember -> every step is stored; lessons are written to memory
```

| Agent | Goal | Tools it chooses from | Its answer must |
|---|---|---|---|
| Orchestrator | Plan the run from the request; review discovery; reflect | source stats, trace | name only known sectors and sources; retry at most once; never stop while there is something to work with |
| Discovery | Collect postings that show a company wants freelance help | `list_sources`, `source_stats`, `fetch_source` | name only sources it actually fetched |
| Research | Understand one company | `read_signals`, `fetch_stored_page` (only pages already stored for that company) | quote text it was actually shown |
| Technical | Find the company's own repository | `read_company`, `github_search`, `github_repo` | cite only repositories it saw, whose text mentions the company |
| **Freelance judge** (qualification) | Decide whether a posting is a company offering paid contract engineering work | `list_postings` (paged), `reviewer_examples`, `submit_verdicts` | quote the posting word for word; the tool rejects any quote that is not in it |
| Strategy | Name the service a posting supports | `read_evaluation`, `list_services` | choose from the allowed list and quote the requirement |
| QA | Try to disprove each strong lead | `read_opportunity`, `recheck_source` (re-opens the stored page) | give a reason for every flag or reject; it can only lower trust |

### The freelance judge
A keyword match is not proof of demand, and demand does not always use the keywords. The judge decides who is posting
(company, individual seeker, recruiter), the engagement (contract, freelance, part-time, full-time) and the kind of work.
It can **confirm** demand the keywords miss (a three-month engagement for a named build) and **veto** a keyword match that is
really a person offering their own work. It learns from what the reviewer approved or rejected before. Its verdict is
evidence, never a score: the evaluator re-checks the quote against the posting every time and the numbers still come from the
fixed rules (`scoring/v2.py`).

### The orchestrator
It turns the operator's words ("find freelance fintech jobs") into a plan, reviews discovery (a run that found no posting
stating a contract must broaden to the demand sources once, even if the model says proceed), and writes a short assessment
and a lesson to memory after the run. Each decision is the model's when available, a plain rule otherwise, and validated either way.

### Memory
`agent_memory` holds lessons and source performance; reviewer decisions feed the judge; `agent_steps` stores every decision
and is shown in the dashboard's Agents view and via `GET /api/runs/{id}/trace`.

### Honest modes
If the model is unavailable (no key, no credit, a bad answer), the stage runs its **fixed policy** and the trace, the room
message and the dashboard all say `fixed policy` and why. A failed model call is never reported as the model deciding.

### What the model can never do
Set a score, approve or reject a lead, send or draft outreach, open a page that is not already stored for the lead, name a
service or source outside the allowed lists, or have an answer accepted that quotes text it was not shown. These are
properties of the tools and checks, not of the prompt, and each has a test.

## Verification status
- Agent behaviour is tested with a scripted model through the whole graph (`tests/test_agents_e2e.py`): tool choice, grounding,
  vetoes, retries, fallbacks, the trace and memory. 274 tests pass.
- The **real model has not been run against these agents**: the OpenRouter account has no credit (HTTP 402). Once credit is
  added, `PYTHONPATH=. uv run python scripts/agent_smoke.py` runs the real model through the planner, the judge and the research
  agent on sample postings without touching your data. Prompt quality (does the real model choose well?) is unverified until then.

## Known limits
- Human approval is still a dashboard or Switch action, not a LangGraph `interrupt()`.
- A halted run is not resumed automatically; checkpoints exist but no resume endpoint is exposed.
- Model calls cost money. A run is capped (default 120 calls); the research agent covers the first 12 companies and the judge
  the first 16 candidate postings per run.
