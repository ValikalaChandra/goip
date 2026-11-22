# Claim verification

Read on 9 November 2026. Status is about the claim as it appears after this pass, not about the retired draft.

| Claim | Evidence | Status | Where it appears |
| --- | --- | --- | --- |
| 27 companies, 92 signals, 65 unlinked | PostgreSQL counts this pass | Verified | Film, article, root README |
| 14 high priority, 7 qualified, 6 needs review | Same query | Verified | Film overview, article |
| Those 21 labels were not rewritten with the three scores | No migration was run. Article and limits card say so | Verified | Film, article |
| Stitch.ai is historical 76, then 70 / 25 / 0, QA reject | Lead page in the existing recording, and the stored version described in the inventory | Verified | Film, article |
| 12 evaluation versions across 6 opportunities | `evaluation_versions` count and distinct opportunity ids | Verified | Article, audit |
| 118 agent messages, screen shows latest 80 | Row count. The UI caps the table at 80 in code | Verified as a count. The film does not quote 118 | Article |
| 34 backend tests passed | `pytest tests -q` this pass, 34 passed in 0.93s, in-memory SQLite | Verified | Limits card, article, root README |
| Switch health ok, Mattermost ping 200 | curl this pass | Verified | Audit, article |
| GOIP API was not listening on 8001 | curl connection refused | Verified | Audit, article. The film uses earlier footage whose cards still match |
| Seven agents and the room id | `AGENT_SPECS`, room file documented as `8b33bb27-9fb9-4b9a-8b47-592b0df0a956` | Verified in code and prior room file. The secret file was not printed | Article, root README |
| Switch is not the model provider | `complete_json` calls OpenRouter. Switch client posts room messages | Verified | Film, article, diagrams |
| GOIP does not call Mattermost | No Mattermost client under `goip/backend/app` | Verified | Film, article |
| A local path exists when Switch is down | `POST /api/runs` returns `local_switch_offline` | Verified | Film, article, execution-flow diagram |
| Human console round trip | `docs/final-sprint/gui-roundtrip.png` | Verified as an earlier recording. Not retyped this pass | Film still, article |
| Strategy replied because "send outreach" is a substring | `TeamRuntime._human` and the words in the screenshot | Verified | Article |
| Gateway Tencent exchange was not a keyboard session | `docs/final-sprint/SWITCH-LIVE-PROOF.md` | Partially verified. The doc says so. I did not re-fetch the room | Article |
| Connected sources are four, and three are not connected | `app/discovery/connectors.py` | Verified | Film, article |
| Telegram chat was not opened | No chat capture in this pass | Verified as an absence | Article. Not in the film |
| Product is production-ready | Not claimed | — | — |
| All signals are linked | 65 unlinked | Incorrect if anyone still says it. Removed from the new copy | — |
| 26 / 84 / 58 is current | Superseded by the live query | Incorrect as a current figure. Kept only as the earlier inventory table | `INVENTORY.md` table, labeled as the earlier audit |
