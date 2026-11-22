# Demo script

Use one real record from run `8611aed0-4395-4b7c-bc61-fde51cabd8b9`. Tencent / Hy4 is the record the agents already answered. Say that other rows in the same run include weak Show HN titles, and that the list was not padded to 200.

1. Problem. A freelancer cannot read every funding note and product launch. GOIP keeps the source URL attached to the claim.
2. Start Switch Console and the GOIP API (`python -m app.main` in `goip/backend`).
3. Open the room `GOIP Opportunity Intelligence`.
4. Show the dashboard overview: 22 discovered, 22 screened, 22 researched, 15 marked high priority, targets 200 / 100 / 50 / 15.
5. Open lead `GB22DD4B0`. The observed line is the Hy4 launch. The technical need is labelled as an inference.
6. In the room, show the earlier agent handoffs for this run (`GOIP-TASK` / `GOIP-RESULT`) and the admin message `sw_fd267860d3db4fc691c9e8b595775e5b` with the research reply.
7. As the person at the keyboard, mention `@goip-orchestrator` and ask it to approve or reject `GB22DD4B0`. That typed exchange has not been done yet. The admin exchange above was sent through the gateway by the setup session.
8. Confirm no email or LinkedIn message exists. The drafts table was empty after the investigation reply.
9. Show the CSV and JSON under `goip/data/exports/` for this run, and the Telegram status `delivered` on the run row.

Do not show `.env`, agent keys, or the bot token.
