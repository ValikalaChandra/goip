# Baseline after the live run

Recorded 8 November 2026, after run `8611aed0-4395-4b7c-bc61-fde51cabd8b9`.

| Item | Observed |
|---|---|
| Machine | macOS, Docker Desktop, Switch Console 0.40.1, bundled switch-core 0.31.0 |
| Agent API | `127.0.0.1:50990` healthy |
| Gateway | Mounted at `http://127.0.0.1:50990/gateway`. Nothing listens on 50989 |
| Mattermost | Not listening |
| GOIP API | `127.0.0.1:8001` |
| Database | Postgres 16 in container `goip-postgres`, host port 5433 |
| Tests | 13 passed (`pytest tests -q`) |
| Latest run | completed, Switch `delivered`, Telegram `delivered` |
| Counts | raw 65, discovered 22, screened 22, researched 22, high priority 15 |
| Screened correction | The run first stored screened 21 because the last signal was not flushed. The distinct screened company count is 22. The row was updated to 22. The Telegram text was already sent with 21 |
| Switch messages for that run | Task and result pairs for discover, research, technical, qualify, strategy, qa, plus the completion note |
| Human exchange | Local admin via the gateway. Agent reply stored. Outreach drafts: 0 |
| Earlier run | `3698f77a-5eeb-44f3-9795-b5a05bb479b4` partial, stage timeout on discover, because the message handler called a missing method |

The workspace was empty at the start of this project. GOIP was built in `goip/`. Switch source was not cloned. The running protocol was read from the Console bundle.
