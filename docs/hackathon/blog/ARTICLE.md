# Building a desk that can refuse a lead

I was hunting freelance work in browser tabs. A Hacker News launch, a funding note, a company name in a headline, and then a guess about whether they might hire someone like me. A week later I could not show why I had believed it.

I built Global Opportunity Intelligence, GOIP, for that job. It is a local desk. It stores the public source next to the claim, asks seven agents to work a stage at a time in one Switch room, and keeps three scores apart so a notable launch is not automatically a freelance opportunity. The company I use as the example still has its old score of 76. The later reading says the freelance fit is 0. Nothing was sent.

This article is the build, including the parts I would warn a first-time Switch user about. It is not a product I have sold.

## What I wanted instead of another tab

The useful question is not "who was mentioned today?" It is "what was published, what can I actually support from that text, and what should I review before I write to anyone?"

I wanted five things the tabs never gave me.

A business signal is the event: a launch, a funding note, a product sentence. A technical opportunity is a requirement written down, not an AI badge on the homepage. Freelance fit is whether an outsider is a fair reading of that text. Commercial intent is a separate label for whether the text shows an external purchase, and it is not added into the three scores. The next action stays human. Approval in the app records a decision. A draft is a second action, and it stays unsent.

The intended user is me, doing this research on my own machine.

## What Switch is, in the sense I use it

Switch is the collaboration layer. On this machine the Switch Console app serves an agent API at `http://127.0.0.1:50990` and a local Mattermost at `http://127.0.0.1:50991`. Agents join a room. A person can type in that same room. Messages move over the agent API and a websocket.

Switch is not the model. OpenRouter is a separate HTTPS call from the research and qualification code. Switch does not replace Mattermost. Mattermost is the composer. Switch is what attaches that composer to the agent room. GOIP never calls the Mattermost API. If you are wiring your first workflow, draw those three boxes before you write a prompt. I mixed them up early, and the root README still said the room had no Mattermost bridge after the bridge was already visible in the Console. That sentence was wrong. I have corrected it.

A shared room is valuable because I can interrupt. Seven Python functions can pass work to each other in a log file. They cannot show me the sentence they just accepted, and they cannot hear me say "do not send that." The room can.

The project does not stop if Switch is down. `POST /api/runs` checks the runtime. If the sockets are up it starts a collaborative run. If they are not, it takes a local path and returns `local_switch_offline`. That path does not write the room transcript. What you lose without Switch is the thread, not the scorer.

## The shape of the system

The browser is a static page. FastAPI serves it and the API on `127.0.0.1:8001`. PostgreSQL holds the companies, signals, runs, evaluation versions, and the agent messages GOIP chose to store. The seven agents are members of one room named GOIP Opportunity Intelligence.

```text
Browser  --HTTP-->  FastAPI  --SQL-->  PostgreSQL
                      |
                      | GOIP-TASK / GOIP-RESULT
                      v
                   Switch room  <--websocket--  the seven agents
                      ^
                      | Switch's bridge, not a GOIP call
                   Mattermost composer
```

The diagram with the real side doors, public sources and OpenRouter, is [architecture.pdf](../architecture/architecture.pdf). The stage-by-stage picture is [execution-flow.pdf](../architecture/execution-flow.pdf). I explain both below so the picture is not the only documentation.

Public sources that are actually connected: Hacker News, the TechCrunch RSS feed, a GitHub search that only name-matches, and one Crawl4AI query. Product Hunt, careers pages, and procurement portals are not connectors. They are listed in `app/discovery/connectors.py` as `not_connected` so I do not have to remember the absence.

## The seven agents

The names live in `AGENT_SPECS` in `app/integrations/switch_client.py`. Specialization is a boundary, not a claim that the model got smarter.

| Agent | Responsibility | Input | Output |
| --- | --- | --- | --- |
| goip-discovery | Collect public signals and keep the original URL | A `GOIP-TASK` whose stage is `discover` | Counts from the discovery code, posted back as `GOIP-RESULT` |
| goip-company-research | Read what the stored sources say about the company | Stage `research`, plus company ids | A count of companies researched. Quotes stay tied to stored text |
| goip-technical-intelligence | Look for a stated engineering need and a name-matched public repository | Stage `technical` | The GitHub attach result |
| goip-qualification | Score business signal, technical evidence, and freelance fit separately | Stage `qualify` | The qualification summary. The score is not a probability of hiring |
| goip-strategy | Name a service only as a note | Stage `strategy`, or a human sentence that trips the outreach guard | "No external message was sent." It does not contact the company |
| goip-quality-assurance | Challenge claims the source does not support | Stage `qa` | A verdict. On Stitch.ai that verdict is reject |
| goip-orchestrator | Assign the stage and collect the result. This is the agent I address | The run, or a human mention | The next `GOIP-TASK`, or a reply in the room |

The orchestrator coordinates. It does not secretly do the other six jobs.

## A first Switch setup, from this repository

I am not going to invent a Switch install command. This machine already has Switch Console at `/Applications/Switch Console.app`. Yours may differ. What I can document is how GOIP attaches to a Console that is already serving the local agent API.

1. You need Docker Desktop, Python 3.12, `uv`, and a running Switch Console. PostgreSQL for GOIP is the Compose file in `goip/docker-compose.yml`, bound to `127.0.0.1:5433`.
2. Copy `goip/.env.example` to `goip/.env`. Fill the placeholders locally. Do not commit that file. The keys that matter here are `GOIP_API_TOKEN`, `GOIP_DATABASE_URL`, `OPENROUTER_API_KEY`, `SWITCH_BASE_URL` (`http://127.0.0.1:50990`), and `SWITCH_REGISTRATION_KEY`. Model keys and the Switch registration key are different secrets.
3. Start Postgres from the `goip` directory with Docker Compose, or the equivalent `docker run` in the root README. I use the Compose file so the volume is named and I do not have to remember a one-off container.
4. From `goip/backend`, `uv sync`, then `PYTHONPATH=. uv run python -m pytest tests -q`, then `PYTHONPATH=. uv run python -m app.main`. The API binds to `127.0.0.1:8001`.
5. On startup, `TeamRuntime.bootstrap` checks Switch `/health`, registers any missing agent from `AGENT_SPECS`, and reuses the room id stored in `goip/data/secrets/switch-room.json`. That file is gitignored. The room id I am using is `8b33bb27-9fb9-4b9a-8b47-592b0df0a956`. Creating a second room would be a mistake. The code only creates a room when that file has no id.
6. `connect` opens one websocket per agent: `/agents/{id}/connection/ws`, with the room id, a connection id, and the agent bearer token. Health in GOIP is "connected" only when all seven sockets have reached `connection_state`.
7. Mattermost on this machine answers `http://127.0.0.1:50991/api/v4/system/ping`. The composer you see in Switch Console is that bridge. There is no GOIP setting that "turns Mattermost on." If the Console shows the channel, the bridge is already attached.
8. Open `http://127.0.0.1:8001` and sign in with `GOIP_API_TOKEN`. The token is not in the page.
9. To see a human reply, type in the existing room. Address `@GOIP Orchestrator`. Do not include the words "send outreach" unless you want the outreach refusal. I explain why below.
10. Verify with `GET /health` on port 8001, Switch `/health` on port 50990, the Mattermost ping, and a row in the GOIP Switch screen. A row there is a message GOIP stored. Delivery to the room is the Switch operation result, not the row by itself.

One caution. The daily job is 18:00 Asia/Kolkata, with a one-hour misfire grace. Starting the process inside that window can launch a research run. I did not start the API during this write-up, because port 8001 was already down and I did not want a surprise run to change the counts in the film.

## The round trip I can actually show

I have two different human exchanges, and they are not the same kind of evidence.

The earlier one was not typed in the Console. An automated admin session posted through the Switch gateway into the room and asked for a follow-up on a stored Tencent lead, with an explicit instruction not to send outreach. goip-company-research replied in the room with the stored source, an inference, and a statement that nothing was sent. That proves the agent API path. It does not prove a person used the composer.

The later one was typed in the composer. The screenshot is `goip/docs/final-sprint/gui-roundtrip.png`. The human message, at 10:53 PM in that recording, is:

> @GOIP Orchestrator Confirm you can see this human message in the GOIP room. Reply with one sentence naming this room. Do not send outreach.

The reply on screen is from GOIP Business Strategy Agent, not from the orchestrator:

> No external outreach was sent. A draft can be prepared only after the lead is approved, and sending stays a separate human action outside GOIP.

That is a real round trip. It is also a bug I should not dress up. In `TeamRuntime._human`, the outreach guard looks for the substring "send outreach". The sentence "Do not send outreach" contains that substring, so the strategy agent answers the guard instead of letting the orchestrator name the room. If you are building your first room, test the phrase you think is safe. I thought "do not send" was safe. The code saw "send".

The film includes that screenshot as a labeled still. It is not footage from the final recording. The final recording did not type anything. The Console clip in the film is the existing room, showing stage messages that were already stored.

## How a run moves

When Switch is connected, a dashboard run calls `collaborative_run`. The orchestrator posts a `GOIP-TASK` for a stage. Switch delivers it on that specialist's websocket. The specialist runs the stage inside GOIP: discovery fetches, research calls the model when a company is actually being read, technical intelligence queries GitHub, qualification scores, strategy writes a note, quality assurance checks the claims. The specialist posts `GOIP-RESULT`. GOIP writes the message row itself. Switch does not insert into PostgreSQL.

Research and qualification call `complete_json` in `app/integrations/openrouter.py`. The model is configured in `config/runtime.json` and the key is in the environment. Switch never sees that key.

There are four stored pipeline runs. One is partial, with empty counts, Switch `stage_timeout`. The first completed run stored the original companies and reported 22 qualified and 15 high priority on its own counter. The next completed run qualified 0. A later scheduled run added one more company and also qualified 0. I am not going to narrate the partial run as a success, and I am not going to pretend the later zeros are a failure of the room. They are the scorer refusing to promote weak evidence.

## Stitch.ai, the lead I would not pitch

Stitch.ai is public id `G900BE3A9`. The first scorer mixed a launch, a guessed need, and a service into one number and stored 76. The service line said "LLM integration and RAG" because the signal was a product launch and the post mentioned an assistant. The sentence describes a workspace. It does not say the company needs retrieval, a model integration, or a contractor.

The repair is three scores, stored as a new evaluation version. The ORM refuses updates and deletes on `evaluation_versions`, so version 2 cannot overwrite version 1.

Business signal strength asks how notable the event is. A launch can score 70 and still be a weak lead. Technical opportunity evidence asks whether a requirement is written down. An assistant mention is capped, and it is a hypothesis, so this one sits at 25. Freelance fit asks whether an outsider could be a real reading. A hypothesis adds nothing, so the fit is 0. Confidence sits beside the scores. One source is not corroboration, so confidence is medium. The qualification is research candidate. Quality assurance rejects the service. The company row stays in needs review. Rejecting the claim is not the same as rejecting the company.

The signup page was fetched again. The launch sentence was not on it, so the live page was not treated as a second source. Commercial intent on the page is indirect: business activity, not an external purchase. That label is computed when you read the lead. It is not added into the 70, the 25, or the 0.

Evidence is labeled observed fact, derived fact, inference, hypothesis, or unknown. A quote counts only when it is in the stored text. HTML escapes are decoded for the check. The raw text stays raw.

Six opportunities now have a version pair. Twelve versions in total. Stitch.ai is the one whose second version is a QA reject. The other versioned leads are research candidates with freelance fit 0 and a QA flag. The original 14 high-priority rows and 7 qualified rows do not have this three-score version. A preview of a migration exists. I have not approved the write, and this pass did not run it. Those 21 labels are the first scorer. They are not 21 confirmed freelance jobs.

## What broke, and what I changed

**The single score.** A launch looked like a job. The dashboard would have pointed me at Stitch.ai with a service the source does not support. I kept the 76, appended a second version, and let QA reject the service. The old labels are still on the other rows. That is unresolved on purpose.

**One source, high confidence.** A single page can feel conclusive when the model writes smoothly. Confidence is now separate, and one domain does not count as corroboration.

**Unlinked signals.** Sixty-five signals have no company. The title was a sentence, or the site was a publisher, or a name in a headline was not the domain. One headline mentions Meta and was left unassigned on purpose, because the host was not the company domain. Confirm is the only action that links an ambiguous row. I did not press it.

**History.** I wanted the dashboard to look consistent. Overwriting 76 would have made the lesson disappear. Insert-only versions are the fix, and they are enforced in the model, not as a comment.

**Phrase matching in the room.** The console reply taught me that a guard written as `if phrase in message` will fire on a negation. The human asked the orchestrator to name the room. Strategy answered the outreach rule. I have not loosened that guard in this pass, because changing it is a behavior change and the safe demo is to document it.

**The room without a bridge.** The first time I created the room, Docker was down and the room had no Mattermost channel. Humans could post through the gateway and still not have a composer. The bridge was attached later in Switch, without creating a replacement room. GOIP's code never grew a Mattermost client, which is what I want. The chat product stays the chat product.

## What I ran, and what I did not

On 9 November 2026 the database read was 27 companies, 92 signals, 65 unlinked, 14 high priority, 7 qualified, 6 needs review, 12 evaluation versions, 118 agent messages, 0 human decisions, and 0 drafts.

`PYTHONPATH=. uv run python -m pytest tests -q` from `goip/backend` passed 34 tests in 0.93 seconds. Those tests use an in-memory SQLite database. They do not prove Switch, OpenRouter, or Crawl4AI are reachable. Switch `/health` returned ok, and Mattermost's ping returned 200, in this same pass. The GOIP API on port 8001 was not running, so I did not click through the site again. The film uses the earlier recording, whose overview cards still match these counts.

The frontend is static. There is no production build. An earlier pass ran `node --check` on `app.js` and the evidence-format test. I did not re-run those in this pass.

I did not click Approve, Reject, Confirm, or Draft. I did not send a new Switch message.

## What you can reproduce, and what you should not copy blindly

Clone the repository. Start Postgres from `goip/docker-compose.yml`. Create `goip/.env` from the example. Run the tests. Start `app.main` only when you are ready for the process to own the scheduler. Sign in. Confirm `/health` says Switch connected before you trust a collaborative run.

Do not copy my room id into a fresh Console and expect it to resolve. Register through the application's bootstrap so the agent keys and the room file are created on your machine. Do not commit `goip/.env` or `goip/data/secrets/`.

The film is `goip/docs/hackathon/demo-video/FINAL_DEMO.mp4`. It has no voice. The captions are the explanation. The earlier cut is `final-demo-v1.mp4`.

## Limits I do not want a judge to discover later

Sixty-five signals are still unlinked. The source list is four connectors, not a survey of the market. The original high-priority and qualified labels have not been migrated. Industry and country are often Unknown or Not specified, and I did not invent values to fill the cards. The Switch screen shows the latest 80 stored messages, not all 118. The GOIP process was down when I wrote this, so the film is not a same-hour screen recording of a process I started for the article. Telegram is configured, and report rows exist, but I did not open the chat for this demonstration. It is not the Switch integration. A configured token is not a chat I have read.

## What I learned

More agents do not create better judgment. They create a place to put a rejection. Switch provides that place. It does not provide the judgment. A high business signal is not commercial intent. A QA rejection is not a rejection of the company. Historical rows should not be rewritten to make a dashboard agree with a newer rule. And a safety phrase that matches a substring will fire on the sentence that was trying to be careful.

The desk can research a company and still refuse to pitch it. Switch is the room where that argument is visible. The email still waits for me.
