# Implementation roadmap

## Done in this pass

- Record-level qualification preview for all 22 leads, without writing statuses.
- Reconciliation classifier, audit events, API, and a Reconciliation screen.
- The 41 unlinked signals classified. None auto-linked.
- Commercial intent computed at read time, separate from the three scores.
- Historical service labels labeled as not validated when the source does not support them.
- Future qualification uses `record_if_changed` and does not repeat an identical status event. That function was not executed on the live leads.
- Connector list that separates the four connected sources from Product Hunt, careers pages, and RFP portals.

## Waiting for approval

The status migration in `QUALIFICATION_MIGRATION_PREVIEW.md`. Do not run `qualify()` on the live run until that approval. It would move 21 leads to `needs_review` and also rewrite narrative fields.

## Not built yet

- Careers, Product Hunt, and procurement connectors.
- A second-source fetch for each of the 22 companies.
- Stored commercial-intent versions. The current value is computed on read.
- Industry, country, and date filters beyond the status and company filters.
- A bulk write of evaluation versions for the 21 leads that have none.
