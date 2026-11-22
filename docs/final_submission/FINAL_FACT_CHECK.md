# Fact check for this pass

| Claim | Evidence | Status |
| --- | --- | --- |
| 27 companies, 92 signals, 65 unlinked, 14 high priority, 7 qualified, 6 needs review | PostgreSQL read this pass | Verified |
| 12 evaluation versions, 118 agent messages | Same read | Verified |
| 34 tests passed | `cd goip/backend && PYTHONPATH=. uv run python -m pytest tests -q` — 34 passed in 0.47s | Verified |
| Switch health ok, Mattermost ping 200 | curl this pass | Verified |
| GOIP API on 8001 was down | connection refused | Verified |
| Stitch.ai is 76, then 70 / 25 / 0, QA reject | Prior recording and stored versions. Not re-fetched from the API, because the API was down | Partially verified. The film still shows the lead page from the recording that matched this database |
| Diagrams only draw implemented paths | `render_diagrams.py` and the code paths in `ARCHITECTURE_EXPLANATION.md` | Verified as a drawing. Re-inspected as PNGs |
| Voice was cloned from Devarabisanahalli Road.m4a | File not found | Not done |
| A new Switch message was sent | No | Not done |
| The site was re-recorded today | No | Not done |
