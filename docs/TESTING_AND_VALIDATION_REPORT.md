# Testing and validation report

Run on 8 November 2026.

`cd goip/backend && PYTHONPATH=. uv run python -m pytest tests -q`

Result: **34 passed**.

New cases cover a company-domain match, a headline that only mentions a company, a duplicate URL, an unmatched essay, a repeat inspection that inserts nothing, an explicit confirm that links one signal, a launch that is not an external contract, and an explicit freelance sentence. The earlier scoring, review, and evidence tests still pass.

`node --check frontend/app.js` passed. There is no frontend build and no ESLint config.

The live inspection classified 41 signals: 40 unmatched, 1 ambiguous. A second call returned `created 0, skipped 41`. Opportunity statuses and scores were unchanged. Unlinked signals remained 41 because the ambiguous Meta headline was not confirmed.

After the API restart, a logged-in browser session opened Reconciliation and showed 40 unmatched signals and 1 ambiguous Meta headline. Stitch.ai still showed status needs_review, historical score 76, commercial intent indirect, and the RAG label as a historical recommendation. Confirm was not clicked.

Not run: a new discovery crawl, a fetch of careers or documentation pages for the 22 companies, the qualification status write, and a new Switch room round trip. Health after the restart: GOIP ok, Switch connected, Mattermost listening on 50991.
