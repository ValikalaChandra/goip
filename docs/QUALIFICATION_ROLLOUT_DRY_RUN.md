# Qualification rollout dry-run

Run on 8 November 2026 against the existing GOIP database. No evaluation rows were written for the 21 leads that did not already have one. Status and the historical composite scores were compared before and after the preview and were unchanged.

## Database before the preview

Backup: `goip/data/backups/goip-before-schema-003.sql` (192,145 bytes), taken with `pg_dump` before schema 003. The dump is a restore file. It was not loaded back, because nothing was deleted.

| Table | Rows |
|---|---|
| Companies | 22 |
| Opportunities | 22 |
| Signals | 63, of which 22 are linked to a company and 41 are not |
| Evaluation versions | 2, both for Stitch.ai |
| Outreach drafts | 0 |

Status at the time of the preview: 14 `high_priority`, 7 `qualified`, 1 `needs_review` (Stitch.ai).

## Preview of all 22 leads

The preview scored stored sources in memory.

| Result | Count |
|---|---|
| Qualification `research_candidate` | 22 |
| Freelance fit 0 | 22 |
| QA `reject` | 22 |
| Confidence medium | 22 |
| A new service proposed | 0 |
| `high_priority` without an external contracting statement | 14 |

Business signal was 70 on the product-launch leads and 85 on the funding headlines. Technical evidence was 25 where the text only mentioned an AI product, and 0 where it did not. Every lead has one linked source, so none reached high confidence.

Sixteen stored recommendations say “LLM integration and RAG” and six say “Backend and API development.” QA rejects those labels because the stored text does not state the matching requirement. That is why every preview verdict is `reject`.

Stitch.ai stayed at historical score 76, status `needs_review`, business 70, technical 25, freelance 0.

## What a full write would do

`qualify()` would keep the historical scores and append versions through `record_evaluation`. It would also move a lead to `needs_review` unless the source states an external contract and QA does not reject it. On this database that would change 21 statuses and leave Stitch.ai in `needs_review`. No lead would become `high_priority` under the new gate.

That write was not run. `record_if_changed` is ready for a later batch: it appends a version only when the sources or the scoring configuration differ, and it does not by itself change status. Running `qualify()` is a separate decision because it changes status.
