# Submission audit

Read on 9 November 2026, before the architecture-led film and the rewritten article. Nothing in this pass wrote to PostgreSQL, pressed a review button, or sent a Switch message.

## Live snapshot

| Check | Result |
| --- | --- |
| PostgreSQL `goip-postgres` | 27 companies, 92 signals, 65 unlinked, 27 opportunities, 14 high priority, 7 qualified, 6 needs review, 12 evaluation versions across 6 opportunities, 118 agent messages, 4 pipeline runs, 3 report rows, 0 human decisions, 0 outreach drafts |
| `GET http://127.0.0.1:8001/health` | Connection refused. The API process was not listening. I did not start it. The scheduler's grace window can fire a missed daily run, and a run would change these counts |
| Switch `GET http://127.0.0.1:50990/health` | `{"status":"ok"}` |
| Mattermost `127.0.0.1:50991/api/v4/system/ping` | 200 |
| Backend tests | 34 passed in 0.93s, in-memory SQLite, after this audit |

The overview in the existing recording shows 27, 21 qualified including priority, 14 high priority, Switch connected, 65 unlinked, and 6 needs review. Those cards match the database. The prompt's snapshot of 26 companies, 84 signals, 58 unlinked, and 5 needs review is the earlier inventory, not the live table.

## Discrepancies found

| Item | What the old material said | What is true now |
| --- | --- | --- |
| Company and signal counts in `ARTICLE-v1.md` and the inventory table | 26 companies, 84 signals, 58 unlinked, 5 needs review, 10 versions across 5 leads | 27, 92, 65, 6, 12 versions across 6 leads. A scheduled run added Recto before the first film |
| "No video was rendered" in the inventory | Still in the classification table | `final-demo-v1.mp4` exists, and `FINAL_DEMO.mp4` is the later cut |
| Root `README.md` tests | "13 tests passed" | 34 passed on this pass |
| Root `README.md` limits | "No Mattermost bridge is attached" | Switch Console shows the room as a Mattermost channel with a composer. GOIP code still does not call Mattermost |
| Root `README.md` human exchange | Describes only a gateway admin post about Tencent | A later console recording exists: a person addressed the orchestrator, and the strategy agent replied that no outreach was sent. See `docs/final-sprint/gui-roundtrip.png` |
| `SYSTEM.md` mermaid | Draws discovery as if it talked to the other agents directly, and draws Telegram as the exit | Discovery runs inside the FastAPI workflow. The room carries `GOIP-TASK` and `GOIP-RESULT`. Telegram is not part of the film |
| Agent messages | "latest 80 of 92" | 118 stored messages. The Switch screen still caps the table at 80. The film does not quote 92 |
| First film bitrate | About 6 MB at roughly 185 kb/s | Readable on the frames I checked, because the picture is mostly still. The new cut is encoded at CRF 16 from the same source footage. The source is the quality ceiling |
| Stitch.ai | Unchanged, and the old article was right about this | Historical 76, business 70, technical 25, freelance fit 0, QA reject. The 14 and the 7 were not rewritten |

## What the first film already had

Real overview, a needs-review filter narrowed to Stitch.ai, the three scores, the QA reject, the Switch Console room, the GOIP message table, Settings without secret values, and a diagram. Telegram text had been removed from the captured page only.

## What it did not explain well enough for a judge

The diagram was one small plate. Agent responsibilities were a caption, not a screen. The console clip shows stage messages, not the human sentence. A viewer could leave thinking Switch is the model, or that the product cannot run without it. The article taught the Stitch lesson and then spent its Switch section too thin for someone who has never opened the Console.

## What this pass did not do

It did not re-record the website, because the API was down and the cards already match the database. It did not type in Switch. It did not treat `gui-roundtrip.png` as new footage. The film labels that still as an earlier recording.
