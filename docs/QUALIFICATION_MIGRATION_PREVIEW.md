# Qualification migration preview

This is a preview. The live qualification write has not been run. After the inspection, all 22 opportunity statuses and historical scores were compared and were unchanged: 14 `high_priority`, 7 `qualified`, 1 `needs_review`. Outreach drafts remain 0.

The preview QA result below is computed from the linked source text. Only Stitch.ai has stored evaluation versions. The other 21 have no evaluation version yet. A preview verdict is not a stored QA row.

## Why 21 records would change, and which one would not

Twenty-one leads are `high_priority` or `qualified` because the earlier composite score treated a product or funding headline as a qualified lead. The linked source does not state an external contract, and the stored service label is not supported by that source. The proposed status is `needs_review`.

That status means the lead stays in research. It does not mean the company is rejected, and it does not mean the missing evidence is a negative fact. The missing evidence is unknown: a second source, a stated technical requirement, and any contracting language.

`G900BE3A9` Stitch.ai would not change status. It is already `needs_review`. Its historical score is 76. Version 2 is already stored. Repeating the scorer with `record_if_changed` does not add another version while the source text and the scoring configuration are unchanged.

QA rejection in this preview is a rejection of the service recommendation, not of the company. No lead is proposed for status `rejected`.

## Record comparison

| Lead | Company | Status now | Score | Stored version | Proposed status | Qualification | Preview QA | Service | Supported | Missing evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| G0B4E7591 | Nino | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G338B5107 | ScrivenSpell | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G49282A26 | AIDA | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G49DE7440 | Study Scout, a novelty search with no NOVEL verdict | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G585D0989 | OpenAI reportedly | qualified | 67 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |
| G5EC28AD1 | Lipwise | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G608C2297 | Fal | qualified | 70 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |
| G63505E14 | OpenAI | qualified | 70 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |
| G682E55AC | Neural Network Formal Verification | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G7262D2B5 | OfflineVault | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G72A9D971 | Goethe | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G73F8F4DC | Site/app blocker and usage tracker specifically for Linux | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G766B1D5B | After decades, I have my almost perfect music player | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| G900BE3A9 | Stitch.ai | needs_review | 76 | 2 | needs_review | research_candidate | reject | LLM integration and RAG | no | One Hacker News source. Assistant mention is a hypothesis. |
| GB22DD4B0 | Tencent | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| GC2B17A4F | Perplexity | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| GCB7AF495 | Meta | qualified | 66 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| GF40F9A70 | Micron | high_priority | 73 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| GF6FBCB54 | FuriosaAI | qualified | 70 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |
| GF9FA5C99 | Shutdown Watch | high_priority | 76 | none | needs_review | research_candidate | reject | LLM integration and RAG | no | One source. No stated requirement. No contract. |
| GFBEB7217 | Anthropic's falling IPO valuation | qualified | 70 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |
| GFC370975 | Humble Robotics | qualified | 70 | none | needs_review | research_candidate | reject | Backend and API development | no | One source. Funding headline is not an API requirement. |

The technical-need sentence stored on each opportunity is an inference from the earlier research pass. It is not an observed requirement, and it was not used to support the service label.

## Service labels

Sixteen rows say “LLM integration and RAG”. Six say “Backend and API development”. None of the linked source texts contain the terms that would support those labels. The strings remain on the opportunity row so the history is not deleted. The lead page now shows them as historical recommendations, not validated ones. Stitch.ai version 1 still records the old RAG label. Version 2 recommends further research.

## Score preservation

The historical composite score is the `opportunities.score` column. The preview does not write it. Stitch.ai remains 76. A future approved write must append evaluation versions and must not update that column. `record_if_changed` appends a version only when the source text or the scoring configuration changed. Calling the current `qualify()` would also rewrite narrative fields such as `why_approach`, so the approved migration should not be an unattended call to `qualify()`.

## Orphan signals

Forty-one signals have no company. Forty are `unmatched`. One is `ambiguous_match`: “Former Meta Security Chief Calls Password Access for AI Agents 'Insane'” mentions the stored company Meta and was not linked. No signal was a confirmed domain match. Details are in `SIGNAL_RECONCILIATION_REPORT.md`.

## Backup

`goip/data/backups/goip-before-schema-003.sql` is 192,145 bytes and predates the history columns. Do not use it as the only rollback for the current database.

`goip/data/backups/goip-before-reconciliation.sql` is 195,787 bytes. It was taken after schema 003 and the Stitch versions, and before the 41 reconciliation rows. It was not restored.

## Rollback

Nothing in the opportunity table needs to be undone. The reconciliation rows can be removed by deleting `reconciliation_events` and `signal_reconciliations` if that inspection should be discarded. Evaluation versions must not be deleted. If a later approved status write is applied, reverse it from `status_events.from_status` with a new audit event. Restoring a dump means loading it into a new database and pointing the app at that database. Do not drop the Docker volume.

## Expected changes if the write is approved later

- Twenty-one status values move to `needs_review`, each with a status event.
- Stitch.ai stays `needs_review`.
- Historical scores stay as they are.
- New evaluation versions are inserted for leads that do not already have a matching version. Stitch.ai does not gain a duplicate version when the source and configuration are unchanged.
- `recommended_service` stays in place and is labeled historical in the interface.
- No outreach is created.

That write has not been executed.
