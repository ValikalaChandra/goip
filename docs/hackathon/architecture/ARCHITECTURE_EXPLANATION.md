# Architecture explanation

Checked against the code on 9 November 2026. Every arrow below is a path I can point at in the repository. If a box is missing, it is missing because that path is not implemented.

## What each file is

`architecture.tex` is the editable diagram. It compiles to six pages: the full map, then a readable plate for the human and FastAPI, the seven agents, Switch, PostgreSQL, and the sources. `architecture.pdf` is that compile. `architecture.png` and `architecture.svg` are the first page. `layer-1.png` through `layer-5.png` are the later pages, used full-screen in the film so the labels are large enough to read.

`execution-flow.tex` is a separate diagram of one stage. `execution-flow.pdf` and `execution-flow.png` are the compile and the raster.

The previous single-page diagram is kept as `architecture-v1.tex`.

## Layer by layer

**Human and frontend.** The browser loads a static page. FastAPI serves that page and the API on `127.0.0.1:8001`. Overview, the lead list, the Switch message table, and Settings are views of that page. Review buttons call the review API. The film does not press them.

**FastAPI.** One process owns the workflow. Discovery fetches, company research, technical attachment, qualification, strategy notes, and quality checks run in `app/pipeline.py`, called from `app/switch_runtime.py`. When Switch is connected, `POST /api/runs` starts `collaborative_run`. When it is not, the same route takes a local path and returns `local_switch_offline`. That local path does not write the room transcript.

**Seven agents.** They are members of one Switch room, named in `AGENT_SPECS` in `app/integrations/switch_client.py`: discovery, company research, technical intelligence, qualification, strategy, quality assurance, and the orchestrator. The orchestrator posts a `GOIP-TASK`. The specialist's websocket receives it. The specialist runs the matching stage in GOIP code and posts `GOIP-RESULT`. The agents do not open their own database connections.

**Switch.** The agent API on this machine is `http://127.0.0.1:50990`. Each agent opens a websocket at `/agents/{id}/connection/ws` with the room id. Switch is not the model provider. A human sentence typed in the Mattermost composer reaches that same websocket if the message is addressed to the agent. GOIP has no Mattermost client. The bridge is Switch's.

**PostgreSQL.** FastAPI writes companies, signals, opportunities, pipeline runs, evaluation versions, human decisions, and the agent-message rows it stored. Evaluation versions are insert-only at the ORM layer. Switch does not write these tables.

**Sources and the model.** Connected connectors, from `app/discovery/connectors.py`: Hacker News, TechCrunch RSS, GitHub search by name, and one Crawl4AI query. Product Hunt, careers pages, and procurement portals are listed there as not connected. Research and qualification call OpenRouter over HTTPS for a JSON completion. Discovery does not.

## How a human message moves

1. The person types in the Switch Console composer for the room GOIP Opportunity Intelligence.
2. Switch delivers the message on the agent websocket.
3. `TeamRuntime._human` handles it when the sender is a user.
4. Some phrases record a review or broadcast a refusal. The match is a substring, which is brittle: the sentence "Do not send outreach" contains "send outreach", so the strategy agent replies with the no-outreach sentence.
5. GOIP stores its own copy of the message. That row is not, by itself, proof the room delivered it.

## What disappears without Switch

The pipeline can still run. What you lose is the shared thread: stage messages between agents, a place to type, and an agent reply in the same room. That is the collaboration. It is not a claim that the scorer is inside Switch.
