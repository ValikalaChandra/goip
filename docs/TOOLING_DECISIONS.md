# Tooling decisions

Four third-party repos were proposed as aids. Each was cloned into an isolated folder and **read only**: nothing from
them was installed or run. Findings below come from reading their files.

| Repo | What it is | Licence | Verdict | Why |
|---|---|---|---|---|
| `addyosmani/agent-skills` | 26 engineering-process skills (spec, plan, TDD, review, security) as Markdown | MIT | Maybe, as reading | A process aid, not a runtime part. Useful ideas can be copied by hand. Its hooks run `curl` and were not installed. |
| `headroomlabs-ai/headroom` | Context/prompt compression layer for LLM apps | Apache-2.0 | **Skip** | It compresses tool output, logs and RAG chunks, and saves little on prose. GOIP's research prompt is one block of scraped prose, and the prose path is lossy, so it could break the verbatim-quote check. It also ships default-on telemetry and a heavy dependency tree. |
| `open-gsd/gsd-core` | Spec-driven workflow for coding agents | MIT | **Skip** | Its installer writes about 25 hooks into the agent's own configuration. |
| `bmad-code-org/BMAD-METHOD` | Agile AI-development method with personas | MIT | **Skip** | Process framework installed through `npx`. GOIP already has a working process. |

What actually reduced prompt size and cost instead: the research prompt is capped and fenced, headline naming is one
batched call per run, and a stage that has nothing to do makes no model call.

Used and kept: Cloudflare's `security-audit` skill (see `SECURITY_AUDIT.md`), `ui-ux-pro-max-skill` (design system) and
`taste-skill` (page rules), plus the front-end libraries in `frontend/vendor/VENDOR.md`.
