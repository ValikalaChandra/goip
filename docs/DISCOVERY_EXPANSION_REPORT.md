# Discovery expansion report

No new discovery crawl was run. The stored set is still 22 companies, 63 signals, and 41 unlinked signals.

## Connectors that exist

| Connector | Category | Access |
|---|---|---|
| Hacker News | product launches | Algolia API and front-page RSS |
| TechCrunch RSS | funding and product headlines | Public RSS |
| GitHub search | developer activity | Public API, attached only on a name match |
| Crawl4AI search | web search | Configured endpoint, capped at one query |

Product Hunt, careers pages, and procurement or RFP portals are listed as not connected. They were not fetched.

## Quality of the current store

Every linked lead has one company-linked source. Forty-one signals have a source URL and still have no company. Exact source URLs among the unlinked rows are unique, so they are not duplicate copies of the linked signals. A repeated headline on two sites would still be one announcement; the scorer counts registrable domains, not raw row counts.

Runs already record a run id, source health, and duplicate skips inside one discovery pass. Keyword, industry, country, and date-range discovery are not separate controls yet. The scheduler remains the existing 18:00 Asia/Kolkata job.

The useful expansion is a second independent source per company, not a larger list of headline fragments. Several stored names are still headline fragments, including “OpenAI reportedly” and “After decades, I have my almost perfect music player”.
