# Frontend architecture

GOIP serves a static page from `frontend/`. There is no `package.json`, no Vite config, no TypeScript project, and no ESLint config. A production bundler build does not exist, so none was claimed.

The page is `index.html`, `app.js`, `evidence-format.js`, and `styles.css`. FastAPI mounts that directory at `/`. Checks that the repository can actually run:

- `node --check` on `app.js` and `evidence-format.js`
- `node evidence-format.test.js`

Those checks pass. They are syntax and helper tests, not a production build.

## Why it stays this way

The working dashboard already talks to the live API, keeps the operator token in an HttpOnly cookie, and renders the three scores. Replacing it with React, Vite, and TypeScript would rewrite the only UI without adding a capability the API does not already expose. The cost is a second toolchain, a build step, and a risk of breaking the session cookie and the lead page during the rewrite.

A component framework becomes worth it when the page grows past one file or needs a real build, routing, and typecheck. Until then the static page is the product UI.

## What the page shows

The opportunity list separates the historical composite score from business signal, technical evidence, and freelance fit. The lead page labels the current evaluation and keeps every older version on the page. Findings use `observed_fact`, `derived_fact`, `inference`, `hypothesis`, or `unknown`. QA warnings are listed on the version that produced them. Review actions are approve, reject, and request additional research. Outreach stays a separate draft and is refused until the lead is approved.
