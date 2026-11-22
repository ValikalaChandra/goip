# Blog fact check

Article: `ARTICLE.md`. Previous draft: `ARTICLE-v1.md`.

| Article claim | Check |
| --- | --- |
| Personal desk, not a sold product | The app is local. No customer claim is made |
| Three scores are separate from commercial intent | Scoring v2 and the read-time commercial label. Stitch is `indirect_indicator` |
| Switch is not OpenRouter and not Mattermost | Code paths cited in `ARCHITECTURE_EXPLANATION.md` |
| Local run survives Switch being down | `api.py` `local_switch_offline` |
| Room id and seven names | `AGENT_SPECS` and the documented room id |
| Setup commands | Taken from `goip/docker-compose.yml`, `goip/.env.example`, and the root README. No extra Switch CLI was invented |
| Console sentence and strategy reply | Read from `gui-roundtrip.png` |
| Substring bug | `switch_runtime.py` checks `"send outreach" in lowered` |
| Stitch 76 then 70 / 25 / 0, QA reject, company kept | Recording and stored versions |
| 65 unlinked, migration not run | Database count. `qualify()` was not called |
| 34 tests, Switch ok, Mattermost 200, API down | This pass |
| Telegram chat not inspected | Stated as a limit. No screenshot |

The retired draft's 26 / 84 / 58 figures and its "three stored runs" are not repeated as current.
