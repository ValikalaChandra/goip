# Architecture plates

Editable source: `render_diagrams.py`. It paints connectors before the boxes and only through the gaps.

Inspected at 1920×1080:

- `GOIP_SYSTEM_ARCHITECTURE.png` — sources, the operator, the page, FastAPI, seven agents, Switch, Mattermost, PostgreSQL, OpenRouter. The side arrows stop on the top corners of FastAPI. They do not run down its border.
- `GOIP_AGENT_COLLABORATION.png` — eight steps in order. Switch delivers the message. The specialist runs the work. A local path exists when Switch is down.
- `GOIP_EVIDENCE_QUALIFICATION.png` — 70, 25, and 0. Commercial intent has no arrow into it. QA rejects the service. The human has not approved anything.

`GOIP_ARCHITECTURE.pdf` is those three pages.

The earlier TikZ files remain in `docs/hackathon/architecture/`. They are not the plates in the new cut.
