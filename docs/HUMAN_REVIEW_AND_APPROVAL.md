# Human review and approval

Human review is the step before any commercial action. GOIP does not email, message, or submit a form to a company.

The opportunity page supports approve for further consideration, reject, request additional research, and a reviewer note. Approval sets `approved` and does not create an outreach draft. A draft is a separate action and returns 409 until the lead is approved. The draft is stored with `sent` false. Reject keeps evaluation versions. Additional research opens a `research_tasks` row for company research, technical intelligence, and discovery.

Each decision stores the actor, channel, note, time, and the evaluation version it reviewed. Status changes are stored in `status_events`. Evaluation rows stay immutable.

The opportunity list is the review queue. It can be filtered by the stored status, including `needs_review`, `research_requested`, `approved`, and `rejected`. Commercial intent and the supported-service flag are shown from the current source text. They are not a new status. The stored statuses of the 22 leads were not rewritten by this work. Fourteen still say `high_priority` even though the preview would move them to `needs_review`. That difference is intentional until the migration is approved.

Reconciliation has its own actions: confirm, reject, mark duplicate, keep unassigned, and request research. Confirm is the only one that links a signal to a company. Those actions are audited in `reconciliation_events`.

Switch messages that say approve, reject, or request more research use the same review function. Telegram `/approve` and `/reject` do too. None of those paths send outreach.
