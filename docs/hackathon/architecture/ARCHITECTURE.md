# Architecture

This is the diagram compiled from `architecture.tex`. It includes only paths that the repository actually implements. Telegram is omitted because this demonstration does not use it.

## Layers

**Human operator.** The browser loads the static GOIP page from FastAPI. Overview, the opportunity list, the lead page, the Switch message screen, and Settings are views of that page. Review buttons call the review API. This recording does not press them.

**FastAPI.** One process on `127.0.0.1:8001` serves the page and the API. The workflow that fetches sources, calls the model, scores a lead, and posts stage messages lives here, in `app/pipeline.py` and `app/switch_runtime.py`.

**Public sources.** Discovery code fetches Hacker News, the TechCrunch RSS feed, a GitHub name search, and one Crawl4AI query. Product Hunt, careers pages, and procurement portals are not connectors, so they are not on the diagram.

**OpenRouter.** Research and qualification call it for a JSON completion. Switch is not the model provider. The dotted arrow is that outbound call.

**Seven agents.** They are members of one Switch room: discovery, company research, technical intelligence, qualification, strategy, quality assurance, and the orchestrator. The runtime posts stage text into the room and reads replies over the Switch agent API and its websocket. The agents do not open their own database connections.

**Switch.** The room is the collaboration layer. Mattermost is attached to that room by Switch as the human composer. GOIP does not call the Mattermost API. A message already in the room can record a review if it contains an approve, reject, or research phrase. This video does not send a message.

**PostgreSQL.** FastAPI writes companies, signals, opportunities, evaluation versions, human decisions, pipeline runs, and the agent messages it stored. Switch does not write those tables.

## Legend

A solid arrow is HTTP the backend performs. A dashed arrow is a message in the Switch room. A brown arrow is a database write. The long brown path from FastAPI down the right side is the SQL write, routed around the agent box so it is not mistaken for a message.
