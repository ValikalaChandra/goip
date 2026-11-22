# Scoring v2 test report

Run on 8 November 2026.

## Backend

`cd goip/backend && PYTHONPATH=. uv run python -m pytest tests -q`

Result: **26 passed** in 0.32s.

The new cases in `tests/test_scoring_v2.py` cover:

- a product launch with no technical requirement
- a product launch that states an integration requirement
- an engineering vacancy
- a public repository with no hiring note
- an explicit freelance contracting request
- a single source
- two independent dated sources
- a duplicate URL
- an HTML-escaped quotation, including a quotation that is not in the source
- an unsupported service recommendation, which does not change freelance fit
- missing publication dates
- an inaccessible page
- an AI assistant mention, which does not produce an LLM or RAG recommendation

The original 13 tests still pass. They use an in-memory database or pure functions. They do not call Switch, Telegram, or OpenRouter.

## Frontend

There is no frontend package build. The checks that exist were run with the Cursor helper Node binary:

- `node --check frontend/app.js`
- `node frontend/evidence-format.test.js` printed `frontend evidence format tests passed`

The opportunity page renders the three scores, the classification of each finding, and the QA checks. That rendering was not exercised in a browser session for this change, because the page requires the operator token and this report does not claim a click-through.

## Live regression

Stitch.ai `G900BE3A9` was re-evaluated in the existing Postgres database. The opportunity score remained 76, the status remained `needs_review`, and the outreach-draft count remained 0. Version 2 stored business 70, technical 25, freelance 0, confidence medium, qualification `research_candidate`, and QA `reject`. Details are in `STITCH_AI_REEVALUATION.md`.

No Docker volume, Switch room, or agent registration was deleted.
