# Database and API design

Schema 004 adds `signal_reconciliations` and `reconciliation_events`. It does not alter opportunity scores or statuses. `create_all` creates the new tables. Existing evaluation versions stay insert-only.

`signal_reconciliations` has one current row per signal. Repeating the inspection does not insert a second row. Human actions update that current row and append an event. Signal evidence text is not rewritten. A confirmed match sets `signals.company_id` and leaves the original URL and text in place.

Evaluation history remains `evaluation_versions`, with `previous_evaluation_id` and `config_version`. Human decisions point at an evaluation id. Research tasks point at an opportunity.

## API

| Method | Path | Effect |
|---|---|---|
| GET | `/api/reconciliation` | Current classifications |
| POST | `/api/reconciliation/{signal_id}` | Confirm, reject, duplicate, unassigned, or request research |
| GET | `/api/opportunities` | Adds `service_supported` and `commercial_intent` computed from stored text |
| POST | `/api/opportunities/{id}/decision` | Review action, no outreach |
| GET | `/api/overview` | Adds unlinked-signal and needs-review counts |

Authentication is the existing operator token. The new routes do not run qualification.
