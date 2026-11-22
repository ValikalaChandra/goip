# Capability inventory

Checked 8 November 2026 against the process on port 8001, PostgreSQL in `goip-postgres`, and the files in this repo. Counts are stored rows, not targets.

A later scheduled run, already finished before the demonstration was recorded, moved the live counts. Read again on 9 November 2026: 27 companies, 92 signals, 65 unlinked, 6 needs review. The film uses those figures. Stitch.ai is unchanged: historical 76, business 70, technical 25, freelance fit 0, quality assurance reject. The table below is the earlier audit.

## Live checks

| Check | Result |
| --- | --- |
| `GET /health` | `ok`, Switch `connected` |
| Switch agent API `127.0.0.1:50990` | Listening. `GET /gateway/auth/login` returned 405, which means the route exists and expects another method |
| Mattermost `127.0.0.1:50991/api/v4/system/ping` | 200 |
| Backend tests | 34 passed |
| Frontend | `node --check` passed. `evidence-format.test.js` passed. There is no production build |

## Database

| Measure | Value |
| --- | --- |
| Companies | 26 |
| Signals | 84 |
| Signals with no company | 58 |
| Opportunities | 26 |
| Status `high_priority` | 14 |
| Status `qualified` | 7 |
| Status `needs_review` | 5 |
| Qualified, including priority | 21. That is 14 + 7. No row is `approved` |
| Evaluation versions | 10. Five companies have a version 1 and a version 2 |
| Pipeline runs | 3 |
| Agent messages | 92. The Switch screen shows the latest 80 |
| Telegram reports | 2, both `delivered` |

### Runs

| Run | Status | What it counted | Switch | Telegram |
| --- | --- | --- | --- | --- |
| `3698f77a-5eeb-44f3-9795-b5a05bb479b4` | partial | empty counts | `stage_timeout` | `not_started` |
| `8611aed0-4395-4b7c-bc61-fde51cabd8b9` | completed | 65 raw, 22 discovered, 22 researched, 22 qualified, 15 high priority | delivered | delivered |
| `a3c388a5-0e42-487b-b558-1392373ea987` | completed | 65 raw, 44 duplicates, 14 discovered, 4 researched, 0 qualified, 0 high priority | delivered | delivered |

The first completed run’s counter said 15 high priority. Stitch.ai was later moved from `high_priority` to `needs_review` by `goip-orchestrator`, with the reason that it was awaiting human review and that no outreach was sent. The table now shows 14.

### Stitch.ai `G900BE3A9`

Status `needs_review`. Opportunity score still 76. Version 2 is business 70, technical 25, freelance fit 0, confidence medium, qualification `research_candidate`, QA `reject`. Commercial intent on the page is `indirect_indicator`. The stored service “LLM integration and RAG” is labeled historical, not validated.

The other four versioned leads are also `needs_review`, with empty historical scores, the same 70 / 25 / 0 reading, and QA `flag`. One of those company names should not be read aloud.

## Classification

| Capability | Class |
| --- | --- |
| Local FastAPI app and static frontend | Implemented and verified |
| PostgreSQL storage of companies, signals, runs, evaluations | Implemented and verified |
| Three separate scores, stored on five leads | Implemented and verified |
| Historical composite score kept | Implemented and verified |
| QA can reject an unsupported service | Implemented and verified on Stitch.ai |
| Human review actions in the lead page | Implemented. Not clicked in this pass, so the live click was not re-verified. Unit tests cover the decision rules |
| Approval does not send outreach | Implemented in the API and stated in the UI. Not re-clicked |
| Switch room connected, seven agent names, stored messages | Implemented and verified |
| Mattermost bridge from earlier GUI work | Implemented. This pass pinged Mattermost. It did not retype a GUI message |
| Telegram report delivery | Implemented and verified by two `delivered` report rows and two completed runs. The Telegram chat was not opened in this pass |
| Hacker News, TechCrunch RSS, GitHub name search, one Crawl4AI query | Implemented in the connector list as connected |
| Product Hunt, careers pages, procurement and RFP portals | Not implemented |
| Qualification rewrite of the original 21 statuses | Planned. Not run |
| Rendered demo video | `demo-video/FINAL_DEMO.mp4`, 1920×1080, 5:12, silent. An earlier 4:30 cut is `final-demo-v1.mp4` |
| React, Vite, or a production frontend build | Not implemented. The app is static HTML, CSS, and JavaScript |

## Do not say

- 34 opportunities, 9 high-priority leads, or 64 tests.
- That 21 qualified leads are confirmed freelance work.
- That a configured key is the same as a delivered message. Delivery is the report row.
- That Switch is the model provider.
- That a video file exists. It does. Use `demo-video/FINAL_DEMO.mp4`.
