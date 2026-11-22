# Global Opportunity Intelligence Platform

GOIP finds public business signals, researches the companies behind them, and asks a human to decide whether a freelance technical conversation is worth having. It does not email or message those companies.

## What changed in this version

- **Agents, not functions.** Each of the seven agents has a goal, tools it chooses from, a bounded loop, memory and a grounded answer. The orchestrator plans from your request, reviews discovery and reflects on the run. A dedicated freelance judge decides whether a posting is a company offering paid contract work (and vetoes job-seekers the keywords mistake for demand). See `docs/AGENT_ARCHITECTURE.md`. Without a model every agent runs its fixed policy and says so.
- **LangGraph orchestrator.** The graph is the control plane; Switch mirrors each step and is the human channel. See `docs/AGENT_ARCHITECTURE.md`.
- **Every agent answers humans** in its own role, from stored records only, behind the same guardrails (input size, outreach refusal, rate limit, tool allowlist, output scrub).
- **Chat commands in the Switch room** (to the orchestrator): `run` / "bring me new leads", `status`, `focus on fintech`, `clear focus`, and exact-grammar `approve G…`, `reject G…`, `request research G…`, `draft outreach G…`. Free text goes to a model that can only pick run, status, focus or help. It can never approve or reject.
- **Sector focus** (`fintech`, `healthtech`, `edtech`, `cybersecurity`, `logistics`, `climate`, `ecommerce`, `saas`, `ai`): adds sector feeds and filters the general feeds. Saved in `config/runtime.json`.
- **Job boards:** Remotive and We Work Remotely, for engineering roles that state a contract or freelance engagement. Cached for 6 hours so the boards are not polled.
- **Room replies are structured Markdown cards** (heading, labelled fields, tables, a next step), the same shape from every agent.
- **Model health is visible:** if OpenRouter has no credit (HTTP 402) or rejects the key, the dashboard shows a banner and the room's `status` says so, instead of features quietly degrading.
- **Freelance demand source:** contract/freelance requests in the latest Hacker News "Who is hiring?" thread (45-day freshness, negation filtered). These are the leads that can reach `freelance_evidence`.
- **Reconciliation shows its reasoning:** for each unlinked signal, the checks that ran, the candidate company and the basis for it, why it is not a higher class, and what would confirm it. The 'Classify them now' button runs the matcher over signals it has not seen.
- **Showcase page and a new dark desk** built with Lenis, GSAP + ScrollTrigger, Motion, AOS and a Vanta network background (all motion respects `prefers-reduced-motion`).
- **LangSmith tracing** with mandatory redaction. **Security audit:** `docs/SECURITY_AUDIT.md`.

Set `GOIP_ROOM_APPROVERS` in `.env` so only you can approve or reject from the room. If the Telegram chat is a **group**, also set `TELEGRAM_ALLOWED_USER_IDS`: in a group nobody can act unless listed.

## The problem

A freelancer looking for AI, data, or software work has to watch news, funding notes, and product launches by hand. The useful question is not "who was mentioned today?" It is "what was published, what might it imply, and what should I review before I write to anyone?"

## What this workflow does

Public pages and feeds are collected, turned into company records, scored, and checked. Seven Switch agents hand the work to each other in one room. The human reviews the result there. A Telegram report path is configured. The hackathon film does not open that chat. Outreach text is drafted only after an explicit approval, and GOIP never sends it.

```text
Public sources
  -> Discovery
  -> Company research
  -> Technical search
  -> Qualification
  -> Strategy
  -> Quality check
  -> Switch room  <->  human operator
  -> Approved opportunity stays inside GOIP
  -> CSV, JSON, and the Telegram report
```

Telegram is a notification channel. Switch is the collaboration room.

## Agents

| Agent | Work |
|---|---|
| goip-discovery | Collects Hacker News, RSS, and one Crawl4AI page |
| goip-company-research | Separates an observed quote from an inferred need |
| goip-technical-intelligence | Looks for a public GitHub repository that name-matches the company |
| goip-qualification | Scores the record. The score is a research priority, not a hire probability |
| goip-strategy | Describes a possible service. It does not contact the company |
| goip-quality-assurance | Checks that a source URL and an inference label are stored |
| goip-orchestrator | Assigns those stages in Switch and answers a human mention |

## Why Switch is in the path

A collaborative run posts `GOIP-TASK` to the specialist and waits for that specialist's `GOIP-RESULT` on the agent socket. If the socket is down, the run is recorded as partial instead of being described as delivered. A local fallback exists for when Switch is offline. That fallback does not write the room transcript.

The room used for the verified run is `GOIP Opportunity Intelligence`, id `8b33bb27-9fb9-4b9a-8b47-592b0df0a956`.

The silent hackathon film is `docs/hackathon/demo-video/FINAL_DEMO.mp4`. A database read on 9 November 2026 showed 27 companies, 92 signals, 65 unlinked, 14 high priority, 7 qualified, and 6 needs review. The article is `docs/hackathon/blog/ARTICLE.md`.

## A verified human exchange

This was an automated sign-in as the local Switch admin through the gateway, not someone typing in Switch Console.

Admin, message `sw_fd267860d3db4fc691c9e8b595775e5b`:

> Please investigate this opportunity further. Verify the original source, identify the most plausible technical service requirement, explain the supporting evidence and return your confidence level. Do not send any external outreach.

goip-company-research replied in the same room:

> Follow-up for GB22DD4B0 Tencent. Observed: Tencent launches Hy4. Source: https://www.tencent.com/tencent-launches-hy4-joining-the-ranks-of-the-worlds-leading-open-source-ai-models/. Inference, not a vacancy: there may be a need for AI and open-source work. Recommended service: LLM integration and RAG. Confidence: medium. Score: 76. No external outreach was sent.

No outreach draft was created. The drafts table count after this exchange was 0.

## Run this locally

Requirements: Docker Desktop, Python 3.12, `uv`, and the installed Switch Console. The API binds to `127.0.0.1:8001`.

```bash
cp goip/.env.example goip/.env
# Fill placeholders locally. Do not commit goip/.env.
docker run -d --name goip-postgres \
  -e POSTGRES_USER=goip -e POSTGRES_PASSWORD=goip -e POSTGRES_DB=goip \
  -p 127.0.0.1:5433:5432 postgres:16
cd goip/backend
uv sync
PYTHONPATH=. uv run python -m pytest tests -q
PYTHONPATH=. uv run python -m app.main
```

Open `http://127.0.0.1:8001` for the showcase page, then `http://127.0.0.1:8001/app` for the desk, and sign in with `GOIP_API_TOKEN`. The token is read from the environment. It is not embedded in the page.

Switch Console must already be running its local server. On this machine the agent API is `http://127.0.0.1:50990` and the gateway is `http://127.0.0.1:50990/gateway`. Agent keys are created once and stored in `goip/data/secrets/`, which is gitignored.

Start a run from the dashboard, or:

```bash
curl -X POST http://127.0.0.1:8001/api/runs \
  -H "Authorization: Bearer $GOIP_API_TOKEN" \
  -H "Content-Type: application/json" -d '{}'
```

The daily job is 18:00 `Asia/Kolkata`, coalesced, one instance.

## Run it in Docker

```bash
# Postgres already running on the host (as above)? Reuse it, do not start a second one:
GOIP_DOCKER_DB_URL="postgresql+psycopg://goip:PASSWORD@host.docker.internal:5433/goip" ./scripts/docker-up.sh
# Otherwise this starts the compose Postgres too:
./scripts/docker-up.sh
```

Stop the host process first: the host API and the container cannot both hold port 8001, the Switch sockets and Telegram polling.

**Behind a TLS-inspecting proxy** (the build fails with `UnknownIssuer`)? Export the proxy's *public* root certificate once:
`./scripts/export-corp-ca.sh <part of its name>`. It is passed to the build as a build secret (it is not stored in any image layer)
and mounted read-only at run time. `certs/*.pem` is git-ignored. The container runs as a non-root user with all capabilities dropped.

## Environment

See `goip/.env.example`. Real values belong only in `goip/.env` (mode 600) or in Switch Console's own env file. The application reads `SWITCH_REGISTRATION_KEY`, then `goip/data/secrets/registration.key`, then `AGENT_REGISTRATION_TOKEN` from `SWITCH_ENV_FILE`.

## Tests

`cd goip/backend && PYTHONPATH=. uv run python -m pytest tests -q`

139 tests pass (22 November 2026). Earlier: 13 on 8 November, 34 on 9 November. They cover extraction, scoring, prompt-injection text that must not change the score, CSV formula neutralization, private-URL rejection, Telegram chat authorization, and a mocked discovery funnel. They do not prove that Switch, Telegram, OpenRouter, or Crawl4AI are reachable.

## Security controls that are in the code

- API authentication with a bearer token or an HttpOnly cookie, loopback bind.
- Outbound fetches reject loopback, private, link-local, and cloud-metadata addresses, and re-check redirects.
- Scraped text is fenced before it is sent to a model. The model cannot set the score or send a message.
- CSV cells that start with `=`, `+`, `-`, or `@` are prefixed.
- Telegram commands are ignored unless the chat id matches `TELEGRAM_CHAT_ID`.

This is not a completed Cloudflare security-audit-skill run. See `docs/final-sprint/SECURITY-RELEASE-GATE.md`.

## Measured run

This table is the first completed run, not the current opportunity table. Later runs are described in `docs/hackathon/fact-check/FINAL_SUBMISSION_AUDIT.md`.

Run `8611aed0-4395-4b7c-bc61-fde51cabd8b9`, started 2026-11-08T14:58:36Z.

| Stage | Target | Actual |
|---|---:|---:|
| Raw items |  | 65 |
| Discovered companies | 200 | 22 |
| Screened | 100 | 22 |
| Researched | 50 | 22 |
| High priority | 15 | 15 |

Sources that returned data: Hacker News Algolia (40), Hacker News RSS (12), TechCrunch RSS (12), Crawl4AI (1). Switch status on the run row is `delivered`. Telegram status is `delivered`, meaning the Bot API accepted the message and both files. The bot username confirmed with `getMe` is `sudeshfreelancingbot`.

The stored screened count was corrected from 21 to 22 after the run. The value 21 was an unflushed last insert. The Telegram text for that run still says 21. The database and the overview now say 22. The shortfall against 200 is real. Nothing was added to fill it.

High-priority count 15 is the configured cap, not evidence that 15 companies are strong leads. Several names in this run are headline fragments from Show HN. The extractor now rejects sentence-like names. That fix applies to the next run, not retroactively to these 22 rows.

## Limits

- The room GOIP Opportunity Intelligence is visible in Switch Console as a Mattermost channel, with a human composer. GOIP does not call the Mattermost API. The bridge belongs to Switch.
- A later console exchange was typed in that composer. The screenshot is `docs/final-sprint/gui-roundtrip.png`. The strategy agent replied that no outreach was sent. The sentence contained the substring "send outreach", which is why that guard fired.
- Switch Console was recorded for the hackathon film. See `docs/hackathon/demo-video/FINAL_DEMO.mp4`.
- Agent-Reach is not installed.
- Crawl4AI was used for one public page, not as a crawler of every directory in the source catalogue.
- The Cloudflare audit skill was not executed.
- Wispr Flow was not used for this implementation.

## Layout

`backend/app` holds the API, pipeline, Switch runtime, and integrations. `frontend/` is two static pages served by FastAPI: `index.html` (showcase) and `app.html` (the desk at `/app`). Third-party libraries are vendored in `frontend/vendor/` (see `VENDOR.md` there) because the Content-Security-Policy allows scripts only from this origin. `config/runtime.json` holds targets, weights, and model names. Reports are written under `data/exports/`.
