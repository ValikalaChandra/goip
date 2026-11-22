# Final audit

9 November 2026, after a read-only database query and a test run. Nothing was written to PostgreSQL. No Switch message was sent. The API on port 8001 was not started.

## Complete

- Seven agents are named in `AGENT_SPECS` and join one room.
- FastAPI serves the static page and runs the stages. Switch carries `GOIP-TASK` and `GOIP-RESULT` on a websocket. OpenRouter is a separate HTTPS call.
- Mattermost answers on port 50991. Switch health on port 50990 returned ok. GOIP has no Mattermost client.
- Stitch.ai remains the case: historical 76, business 70, technical 25, freelance fit 0, QA reject, company kept.
- 34 backend tests passed again, in 0.47s, on in-memory SQLite.
- A silent 1080p film already existed. This pass replaces its architecture section with three full-frame plates.
- An earlier console recording shows a human sentence and a strategy reply. It is labeled as earlier. It was not retyped.

## Current data

| Measure | Value |
| --- | --- |
| Companies | 27 |
| Signals | 92 |
| Unlinked signals | 65 |
| High priority | 14 |
| Qualified | 7 |
| Needs review | 6 |
| Evaluation versions | 12 |
| Agent messages | 118 |

The 26-company / 58-unlinked snapshot is older than this table. The overview in the film matches this table. The GOIP process itself was down, so the site was not re-recorded.

## Incorrect or weak before this pass

- The TikZ overview let the operator bar cover the source and model cards, and some arrows rode the edges of boxes.
- The root README said there was no Mattermost bridge and that 13 tests had passed. Both were already corrected in the previous pass.
- `SYSTEM.md` drew agents as a direct chain and drew Telegram as an output. A warning was added. The new plates replace it for the film.
- The first film's architecture section was a set of smaller plates. The new section is three 1920×1080 drawings.

## Missing, and why it stays missing

- `Devarabisanahalli Road.m4a` is not on this Mac. Spotlight, Downloads, Documents, Desktop, Voice Memos, and the project tree were searched. No `.m4a` with that name exists. Narration was not synthesized. A different ElevenLabs file in `Documents/Personal_exp/video_1/` was not used.
- A new human message in Switch was not sent.
- The website was not re-recorded, because starting the API can fire the 18:00 Asia/Kolkata job inside its one-hour grace window.

## Needs you

Put `Devarabisanahalli Road.m4a` in `goip/docs/final_submission/video/voiceover/source/` if you want it cloned. I will not upload it to a remote voice API unless you say so in the same message. Local cloning is the default I will try.

If you want a new Console reply from the orchestrator, approve one sentence that does not contain "send outreach". The current guard treats that phrase as a substring, including inside "do not send outreach".
