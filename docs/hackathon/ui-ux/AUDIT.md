# UI audit

The app stayed a static page. It was not rewritten in React.

## What changed

- A dark sidebar on wide screens, and a scrolling nav on narrow ones.
- A status bar drawn from stored counts: 14 high priority, 7 qualified, 5 needs review.
- The latest-run table scrolls instead of breaking the page.
- The lead page shows the current three-score reading once, and older versions under history.
- Settings lists integration state without printing secrets. Runtime config sits behind a disclosure.
- The Switch screen names the seven agents and says a stored message is not proof that every agent finished the latest run.

Files: `goip/frontend/index.html`, `styles.css`, `app.js`, and `goip/backend/app/api.py` for the status counts.

## What I checked in the browser

- Overview showed 26 companies, 21 qualified including priority, 14 high priority, Switch connected, 58 unlinked, 5 needs review.
- The latest run on screen was `a3c388a5-0e42-487b-b558-1392373ea987`, Switch delivered, Telegram delivered, with the target shortfalls visible.
- Opportunities filter for `needs_review` returned five leads, including Stitch.ai.
- Stitch.ai showed score 76, business 70, technical 25, freelance fit 0, QA reject, and the note that approval does not send outreach. Version 2 appeared once. The older version appeared once.
- Switch listed the seven agents and a table of stored messages.
- Settings showed OpenRouter, Telegram, Crawl4AI, and Switch registration as configured.
- At a phone width the nav remains on one scrolling row. I did not press Run research, Confirm, Approve, Reject, or Draft outreach.

Screenshots: `screenshots/overview-desktop.png` and `screenshots/overview-mobile.png`.

## What is still one page, not eight products

Company profile, technical evidence, scores, commercial intent, QA, and human review all live on the lead. There is no separate Telegram screen. Delivery is on the latest run and in the `reports` table. There is no chart that is not a count of stored rows. Industry labels include Unknown, and country labels include Unknown and Not specified. Those strings were not cleaned.

## Tests

34 backend tests passed. The frontend syntax check passed, and `evidence-format.test.js` passed. There is no frontend production build.
