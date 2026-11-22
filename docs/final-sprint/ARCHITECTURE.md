# Architecture that is actually running

```text
Hacker News Algolia
Hacker News RSS
TechCrunch RSS
Crawl4AI Cloud (one page)
        |
        v
goip-discovery
        |  GOIP-TASK / GOIP-RESULT on Switch websockets
        v
goip-company-research ---- OpenRouter JSON extraction
        v
goip-technical-intelligence ---- GitHub search API
        v
goip-qualification ---- deterministic score in scoring/engine.py
        v
goip-strategy
        v
goip-quality-assurance
        v
goip-orchestrator ---- writes CSV and JSON, then Telegram
        |
        +---- Switch room (gateway on the agent port)
        |         ^
        |         |
        |       Admin user, or a Console user who has joined the room
        |
        +---- PostgreSQL (companies, signals, opportunities, agent_messages, reports)
        |
        +---- FastAPI on 127.0.0.1:8001 and the static page in frontend/
```

The orchestrator does not advance a stage until the addressed specialist returns `GOIP-RESULT` or the stage times out. Timeouts are 300s for discovery and 900s for research.

Scoring weights live in `config/runtime.json` and sum to 100. The model is not allowed to write the score. `service_match` is still passed as true for every researched company, so the relevance component does not yet separate a funding event from a weak product headline. That is a known scoring limit of this build.

Company identity is the registrable domain when one is found, otherwise the normalized name. Publisher domains are not stored as the company website. Signals are unique on source URL plus identity hint.

Switch create-room, targeted message, and read-context calls use the operations in switch-core 0.31.0. Targeted messages arrive with an `@name` prefix. The runtime strips that prefix before it reads `GOIP-TASK`.
