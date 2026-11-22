# Human review

A review is a new decision. It does not rewrite an evaluation and it does not send outreach.

| Action | Status afterwards | What else is stored |
|---|---|---|
| Approve for further consideration | `approved` | A decision tied to the current evaluation, plus a status event |
| Reject | `rejected` | The same audit rows. Evaluation rows stay. |
| Request additional research | `research_requested` | An open `research_tasks` row naming goip-company-research, goip-technical-intelligence, and goip-discovery |
| Return to review | `needs_review` | A decision and a status event |

The reviewer note is stored with the decision. The dashboard, Telegram `/approve` and `/reject`, and an explicit Switch request all use this path. A Switch message that asks for more research opens a task. A draft is still a separate action, and the API returns 409 until the lead is approved. The draft record has `sent` false.

Rejecting a lead leaves its score, findings, and earlier decisions in place.
