# Security release gate

The Cloudflare `security-audit-skill` was not installed and was not executed. This file is a record of controls that were implemented and checked in this repository, plus what remains untested. It is not a claim that the application is safe.

## Secrets

- API keys are read from `goip/.env` and from the Switch Console env file. `.env` is gitignored.
- The Telegram bot token appeared in local process logs because `httpx` logs request URLs at INFO. The `httpx` and `httpcore` loggers are now set to WARNING. Matching lines already written in this session's terminal files were redacted.
- The keys pasted into the original request are in the chat transcript. They should be rotated. They are not repeated here.

## Controls in code

| Control | Where | Check |
|---|---|---|
| Loopback bind and bearer or HttpOnly session | `config.py`, `api.py` | `/api/overview` without a token returns 401 |
| URL destination check before fetch, including redirects | `security/url_safety.py` | Unit tests reject loopback, metadata, and a DNS answer in `10.0.0.0/8` |
| CSV formula neutralization | `security/text.py` | Unit test |
| Untrusted page text fenced before the model call | `openrouter.py` | Injection phrase does not change the deterministic score |
| Telegram chat allow-list | `telegram_api.py` | Unit test |
| No outreach send path | `switch_runtime.py`, drafts table | After the live human exchange, `outreach_drafts` count was 0 |

## Residual risk

- DNS rebinding remains possible if the HTTP client resolves the name again after the check. Egress control would close that. It is not configured.
- `addressing=anyone` lets any member of the room mention an agent. It does not let them send email. A person who can post in the room can still consume model calls.
- The operator token is a shared bearer secret. There is no per-user account.
- Prompt-injection tests cover the scorer and the fence. They do not cover every agent prompt against a live model with a hostile page.
- Dependency versions are not pinned to hashes. No vulnerability scan was run.
- The Crawl4AI key is sent to `api.crawl4ai.com`. Only public URLs are submitted. A bug that passed an internal URL to that service would be a server-side request through their cloud.

## Verdict

Enough for a local demonstration on loopback. Not a finished security audit, and not a basis for exposing the API on a network.
