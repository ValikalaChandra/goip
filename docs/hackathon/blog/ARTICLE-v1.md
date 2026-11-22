# Building a desk that can refuse a lead

## Titles

1. Building Global Opportunity Intelligence with Switch: from multi-agent research to a lead I would not pitch
2. How I built a multi-agent system to discover and evaluate freelance opportunities
3. The score that stayed at zero

Use the first title if the judges are looking for Switch. Use the third if the post and the article should feel like one product.

## Excerpt

I was hunting freelance work in browser tabs. I built a local desk that stores the public source, asks seven agents to read it in a Switch room, and keeps three scores apart. The company I use as the example still has its old score of 76. The later reading says the freelance fit is 0, and nothing was sent.

## Who is writing

Add your name. I built GOIP locally for the Flip the Switch hackathon. The desk is for my own research, not a product I have sold.

## The problem

The manual version of this job is a pile of tabs. A launch on Hacker News, a funding note, a company name in a headline, and then a guess about whether they might hire a freelancer. A week later I could not show why I had believed it.

I wanted the sentence and the source in the same place, and a person in the loop before anyone was contacted.

## The product

Global Opportunity Intelligence is that desk. It is for me. It discovers public business signals, researches the company from what those sources say, and asks whether an outsider could honestly read the text as a freelance or consulting opportunity.

It does not send email. It does not apply to jobs. It does not treat a launch as a contract. Approval in the app records a decision. A draft is a second action, and it stays unsent.

## Architecture

The browser is a static page. FastAPI serves it and the API on `127.0.0.1:8001`. PostgreSQL holds the companies, signals, runs, and evaluation versions. Switch is the room the agents share. Mattermost is the composer I type into. Telegram carries the report out.

Switch is not the model provider. The model is configured separately. Switch is where the agents and I can see the same thread.

The diagram is in [SYSTEM.md](../architecture/SYSTEM.md). Product Hunt, careers pages, and procurement portals are drawn nowhere, because they are not connected.

## Why seven agents

Each name is a boundary.

Discovery brings public signals in. Company research reads what those sources say about the company. Technical intelligence looks for a stated engineering need, not an AI badge. Qualification writes the scores. Strategy may name a service. Quality assurance can reject that service. The orchestrator is who I address. It assigns the stage and brings the answer back.

Splitting them does not make the model smarter. It makes a bad recommendation traceable. On Stitch.ai I can see which stage suggested a service and which stage rejected it.

## The pipeline, as it actually ran

There are three stored runs.

The earliest is partial. Its counts are empty. Switch ended in `stage_timeout`. Telegram was `not_started`. I am not going to narrate that run as a success.

The first completed run stored 22 companies. Its own counter said 22 qualified and 15 high priority. Switch and Telegram both say delivered.

The next completed run saw 65 raw items, marked 44 as duplicates, discovered 14, researched 4, and qualified 0. High priority on that run was 0. Switch delivered. Telegram delivered.

The opportunity table today is 26 companies: 14 still labeled high priority, 7 qualified, and 5 needs review. The 14 and the 7 are the old labels. I have not run the migration that would move them. Stitch.ai is one of the five in review because the orchestrator moved it there after a single-company reading, and the note says no outreach was sent.

## Evidence, and the score that was the wrong shape

The first scorer mixed a launch, a guessed need, and a service into one number. Stitch.ai came out at 76. The service line said “LLM integration and RAG” because the signal was a product launch and the post mentioned an assistant. The sentence describes a workspace. It does not say the company needs retrieval, a model integration, or a contractor.

The repair is three scores.

Business signal strength asks how notable the event is. A launch can score 70 and still be a weak lead. Technical opportunity evidence asks whether a requirement is written down. An assistant mention is capped, and it is a hypothesis. Freelance fit asks whether an outsider could be a real reading of the text. A hypothesis adds nothing. Confidence sits beside the scores. One source is not corroboration.

Stitch.ai’s second version is business 70, technical 25, freelance fit 0, confidence medium, qualification research candidate, QA reject. The 76 is still on the row. Version 2 points at version 1. The signup page was fetched again. The launch sentence was not on it, so the live page was not treated as a second source.

Five companies now have that pair of versions. The other four are also research candidates with freelance fit 0. Their QA result is flag, not reject. The original 21 leads do not have a stored three-score version yet. A preview exists. It was not written.

Commercial intent is read from text already stored. It is not added into the three scores. On Stitch.ai the class is indirect: business activity, not an external purchase.

Evidence is labeled observed fact, derived fact, inference, hypothesis, or unknown. A quote only counts when it is in the stored text. HTML escapes are decoded for display. The raw text stays raw.

## Why Switch

I can run seven processes without a room. What I lose is the place where I can interrupt them.

The room is GOIP Opportunity Intelligence. The seven agents are members. I type in Mattermost. A reply comes back in that conversation. The earlier proof is a real composer message and a strategy reply, captured in `goip/docs/final-sprint/gui-roundtrip.png`. This submission pass confirmed the room is connected and that 92 agent messages are stored. It did not retype a new GUI message. The Switch screen shows the latest 80 of those messages, and it says so in the sense that a row is only a stored message.

That is the difference. Independent scripts would leave me with logs. The room leaves a thread a person can enter.

## Telegram

Telegram is the outbound report, not a second research agent. Two report rows are `delivered`, matching the two completed runs. The partial run never started a Telegram send. I did not open the chat while writing this. The database is the evidence I will stand on. A screenshot of the chat is still worth taking before you post, from the real app, with the token out of frame.

## What went wrong

The single score made a launch look like a job. It mattered because the dashboard would have sent me toward Stitch.ai with a service the source does not support. The fix was to keep the 76, append a second version, and let QA reject the service. The old high-priority labels are still visible. That part is unresolved until I approve a migration. I have not approved it.

A lot of headlines never became companies. 58 signals are still unlinked. The title was a sentence, or the site was a publisher, or a name in a headline was not the same as a domain. One headline mentions Meta and was left unassigned on purpose. Confirm is the only action that links it. I did not press it.

The first run’s counter said 15 high priority and the table now says 14. That is not a missing row. Stitch.ai was moved to needs review.

Industry and country are often Unknown or Not specified. I did not invent them to fill the cards.

## Tests

34 backend tests passed on this pass. The frontend check is `node --check` plus `evidence-format.test.js`. Both passed. There is no browser unit suite and no production build. Switch was connected on `/health`. Mattermost answered its ping. I did not click Approve, Reject, or Draft.

## What I learned

More agents do not create better judgment. They create a place to put a rejection. A high business signal is not commercial intent. A QA rejection is not a rejection of the company. It is a rejection of a claim. A configured token is not a delivered report. The report row is the delivery. And I should not rewrite history in the dark just to make the dashboard look consistent.

## What is next

More independent sources. A careful reconciliation of the unlinked headlines. Three-score versions for the original leads, only after I approve the write. A clearer line between a flag and a reject. None of that is in the product today.

## Close

I wanted to stop guessing. The desk can research a company and then refuse to pitch it. Switch is the room where that argument is visible. Telegram is how the report leaves. The email still waits for me.

## Glossary

| Term | Meaning |
| --- | --- |
| Business signal | How notable the stored event is. Not a hiring score |
| Technical evidence | Whether a requirement is written down |
| Freelance fit | Whether an outsider is a fair reading of the text |
| Research candidate | Not a qualified freelance opportunity |
| QA reject | The service claim is unsupported. The company row remains |
| Historical score | The old composite, kept on purpose |

## Fact check

Every count in this article is in [INVENTORY.md](../fact-check/INVENTORY.md). If the database has moved, trust the database.

## Where to put pictures

After the architecture section, use the diagram. After the product section, use `screenshots/overview-desktop.png`. In the Switch section, use `goip/docs/final-sprint/gui-roundtrip.png` and say it is an earlier recorded exchange. Do not invent a Telegram screenshot.
