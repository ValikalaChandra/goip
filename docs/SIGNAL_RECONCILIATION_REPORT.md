# Signal reconciliation report

Inspected on 8 November 2026. The 41 unlinked signals were classified and stored in `signal_reconciliations`. No opportunity status, score, or service text was changed. A second run created 0 rows and skipped 41.

## Why they were unlinked

Discovery stores a signal with `company_id` only when `extract_company_name` accepts the headline. The extractor rejects titles with more than four words or with stopwords such as “the”, “for”, and “with”. Publisher domains are not used as the company. The 41 headlines failed that test, so the signal was kept and the company was left empty. That is an extraction miss, not a missing foreign key. The column is nullable on purpose.

There is no duplicate company row among these 41. Two stored companies, “OpenAI” and “OpenAI reportedly”, are separate leads and were not merged.

## Classification

| Class | Count | Linked |
|---|---|---|
| unmatched | 40 | no |
| ambiguous_match | 1 | no |
| probable_match | 0 | no |
| confirmed_match | 0 | no |
| duplicate_signal | 0 | no |

The ambiguous row is Hacker News signal `e753d5cf`, “Former Meta Security Chief Calls Password Access for AI Agents 'Insane'”, source `https://epyhia.com/meta-launches-muse-ai-spaces-former-security-chief-calls-password`. The word Meta matches the stored company Meta. The article host is not `meta.com`. The headline is about a former security chief. It stays unassigned until a person presses Confirm.

The other 40 have no extracted company and no company-domain host. Examples that must not be forced onto a lead: “Looking for a CTO” has no company name; the Carta page is a fundraising guide; TechCrunch items name Nvidia, Apple, Amazon, Binance, and Google, which are not the 22 stored companies. Exact `source_url` values are unique. An earlier canonical-URL helper dropped query strings and could have treated different Hacker News item ids as one URL. That helper now keeps the query.

Confirmed matches are the only class linked automatically, and only when the source host equals the stored company domain and the host is not a publisher. None of the 41 met that test. A person can confirm, reject, mark a duplicate, leave a signal unassigned, or request research. Each action appends a `reconciliation_events` row. Confirm is the action that sets `signals.company_id`. Duplicate does not delete the signal.

## Reconciliation process from here

Review the one ambiguous Meta headline in the Reconciliation screen. Leave the 40 unmatched rows unassigned. A later discovery run should pass the same classifier before it creates a company from a weak title. Do not attach a signal because a stored company name appears inside a sentence.
