# Judge scorecard

Weights are the published Flip the Switch weights. Scores are for the verified state on 8 November 2026. Planned work gets no points.

## Use of Switch — 20 / 30

Evidence: seven agents on the live agent protocol, a real room, and run `8611aed0` whose stages moved only when Switch delivered a task and the next agent returned a result. An admin account then posted through the official gateway and a specialist answered in that room.

Deductions: the human exchange was this session using the seeded admin, not a person in Switch Console. The Console window was not verified because Computer Use lacks Accessibility and Screen Recording. The room has no Mattermost bridge. A local pipeline still exists when Switch is down, so Switch is required for the collaborative mode and not for every code path.

What would raise it: a person joins the room in Console, mentions the orchestrator, and the reply is visible there.

## Technical execution — 16 / 25

Evidence: API, Postgres, 13 passing unit tests, one live run, Crawl4AI returning one page, OpenRouter used during research, Telegram API accepting the report, exports on disk.

Deductions: the first collaborative attempt timed out on a handler bug. Screened was miscounted by one until flushed. Many company names in the saved run are headline fragments. Qualification marked 22 of 22 researched rows qualified, then capped high priority at 15. Agent-Reach is not integrated.

## Creativity and impact — 15 / 25

The job is a real one: prepare an evidence-backed reason to contact a company, and stop before sending. The Tencent reply does that split correctly. The same run also promotes weak Show HN titles, so a freelancer would still have to discard a large part of the list by hand.

## Presentation — 12 / 20

README, this directory, and the run ids are honest about shortfalls. There is no Console screenshot, no dashboard screenshot, no demo video, and no compiled technical paper.

## Total — 63 / 100

| Criterion | Score |
|---|---:|
| Switch | 20 |
| Technical execution | 16 |
| Creativity and impact | 15 |
| Presentation | 12 |
| Total | 63 |

A higher score after more verification is possible if the Console exchange and the name-quality fix are shown on a new run. That number is not estimated here, because it has not happened.
