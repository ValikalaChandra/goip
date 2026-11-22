# Security audit: GOIP

Method: Cloudflare's `security-audit` skill, run in a **condensed** form. Three independent read-only hunters covered (1) API, auth, dashboard and
Telegram, (2) LLM, agents and Switch, (3) outbound fetching, secrets and deployment. Each candidate was then checked by someone other than
its finder, against the code or at runtime. Source ref: commit `1af2b06` plus the uncommitted work that followed.

**What was shortened.** No coverage ledger, no coverage critics, no separate record-verification phase, and no schema-validated
`findings.json`. This report is the output. Dependency scan (`pip-audit` on 190 locked packages): **no known vulnerabilities**.

## Confirmed and fixed

| # | Finding | Severity | Evidence | Fix |
|---|---|---|---|---|
| 1 | **LangSmith traces uploaded real secrets** (OpenRouter, Telegram, Crawl4AI, LangSmith, API token): the `goip-run` span captured the whole `Settings` object | High | Queried LangSmith: 2 traces held the real values | Per-span scrubbing (`process_inputs`), non-primitive objects reduced to a type name, scrubbing client for LangGraph's own trace, env no longer exports the tracing flag. Re-checked on 3 post-fix runs: none found |
| 2 | Room `approve`/`reject` hit the wrong lead: any word starting with `G` was taken as the id, fallback to the top lead; `do not approve` approved | Medium | Original `_human` code | Command must start the message, explicit `G` + 8 hex id required, no fallback |
| 3 | `apply_review` and draft paths wrote statuses without the transition guard | Low-Medium | `review.py`, `api.py`, Telegram | All status writes go through `check_status_transition`; API returns 409 |
| 4 | Room accepted `GOIP-TASK`/`GOIP-RESULT` from anyone, and an empty `sender_name` failed open | Low-Medium | `_handle_message` | Graph mode ignores protocol messages; legacy mode requires the orchestrator; empty sender dropped; a user-kind sender claiming an agent name is treated as a human |
| 5 | Session cookie equalled the permanent API token; logout could not invalidate it | Low-Medium | `api.py` login | Random server-side session ids, `SameSite=Strict`, real logout |
| 6 | No CSRF/Origin/Host defence; DNS rebinding could reach the API | Low-Medium | no middleware | Host allowlist, Origin check, JSON-only writes |
| 7 | No login rate limit | Low | `api.py` | 5 failures lock a client for 5 minutes, doubling on repeat |
| 8 | `PUT /api/settings` unvalidated: an invalid time zone could stop the app starting, huge caps drove cost | Low-Medium | `save_runtime` | Typed, bounded validation; atomic write under a lock |
| 9 | Prompt-fence breakout; model JSON shape not enforced; output guardrail defined but never called | Low-Medium | `openrouter.py`, `pipeline.py` | Fence markers stripped; five string fields only, capped; `check_grounded_output` wired in |
| 10 | Unbounded message handling and DB writes per room message | Low-Medium | `_on_message` | Throttle before the DB write, bounded concurrency, single-flight run/review |
| 11 | `freelance` matched even when negated ("we do not hire freelancers") | Low | `v2.py` | Negation-aware match |
| 12 | Scraped text and PII in room messages not scrubbed | Low | `_broadcast` | Every room post is scrubbed |
| 13 | Empty values in `.env.example` crashed startup | Availability | pydantic bool parsing | `env_ignore_empty` |
| 14 | Telegram loop died silently on one bad update | Availability | `main.py` | Per-update error handling |
| 15 | CSP blocked inline styles, breaking the status bar | Functional | `app.js` | Widths set through the CSSOM |
| 16 | SSRF blocklist missed NAT64, 6to4, Teredo; no response size caps | Low | `url_safety.py`, `sources.py` | Prefixes added, mapped addresses unwrapped, 3 MB streaming cap on decoded size |
| 17 | Compose default password, no container hardening, world-readable backups/exports | Low | compose, `ls -l` | Password required, `no-new-privileges`, `cap_drop: ALL`, modes 700/600 |
| 18 | Blank quotation counted as supported evidence; multi-line sources failed their own quote check | Correctness | `evidence.py`, `v2.py` | Whitespace-tolerant match, blank rejected, scoring logic version bumped so leads are re-read |
| 19 | DNS rebinding: a URL was validated, then resolved again at connect time; lookups blocked the event loop | Low | `url_safety.py`, `sources.py` | Connect to the validated IP with the real hostname as Host and TLS SNI; lookups run in a worker thread. Tests prove one resolution and a pinned connection |
| 20 | Telegram authorised by chat id only: in a group every member shares it | Low-Medium | `telegram_api.py` | A private chat must be the owner; a group member must be in `TELEGRAM_ALLOWED_USER_IDS` |
| 21 | `/api/opportunities` unpaginated with per-row queries | Low | `api.py` | Filters and counts in SQL; limit 1..500 (default 100) and offset; dashboard "Show more" |
| 22 | Rate limiting keyed on a changeable display name | Low-Medium | `switch_runtime.py` | Keyed on a stable sender id when Switch sends one (it logs the field names once; unverified until a real message arrives) |
| 23 | A job-seeker's own post became a high-priority lead and stored their contact details | Low | `sources.py` | "Who wants to be hired" template excluded; emails and phones redacted at ingestion; the stored lead was rejected through the audited review path and its evidence scrubbed |
| 24 | Model failures (HTTP 402) degraded features silently | Informational | `openrouter.py` | Health recorded, startup probe, dashboard banner, room status line |

## Open (not fixed)

- **Any member of the Switch room can approve or reject** unless `GOIP_ROOM_APPROVERS` is set. The room is a public channel. Set it.
- `GOIP_USE_SYSTEM_CERTS` (host runs) trusts every CA in the OS store for the whole process, including the corporate proxy's. It is off by default and off in the container, which trusts one explicit certificate instead.
- Whether Switch sends a stable user id on messages is unverified (fix 22 falls back to the display name until it does).
- Two LangSmith traces from before fix 1 still contain the secrets. Delete them and rotate all five credentials.
- Not exercised against a live Switch room by a person typing: only through the handler entry point in tests.
