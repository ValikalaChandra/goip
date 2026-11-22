# Evidence model

Every finding uses one classification:

| Classification | Meaning |
|---|---|
| `observed_fact` | The quotation occurs in the stored source, or in that text after HTML decoding. |
| `derived_fact` | Calculated from observed records, such as a count of independent domains. |
| `inference` | A reading that goes beyond the sentence but is still tied to it. |
| `hypothesis` | A possibility that needs more evidence. An AI assistant is not an LLM requirement. |
| `unknown` | The record does not support a claim. A failed page fetch is unknown, not “no evidence on the page.” |

A finding stores the claim, classification, source id, source URL, quotation, publication time when the source has one, retrieval time, confidence, and verification status.

Quotations are checked with `quote_supported`. A sentence that is not in the raw text and not in the decoded text is not stored as an observed fact.

HTML entities such as `&#x27;` are decoded for display. The original `signals.evidence` value is left as stored and is returned as `raw_evidence`.

Duplicate URLs collapse to one source after a canonical form that drops the fragment and a trailing slash. Two pages on different registrable domains can count as independent. Two copies of one URL cannot.

Fetch states:

- `fetched`: a public page was read for this evaluation.
- `partial`: a response was cut short.
- `not_fetched`: this scoring call did not request the page.
- `not_refetched`: the evaluation used the stored text and did not request the page again.
- `inaccessible`: the request failed or returned an error. That is not the same as a page that was read and had nothing relevant in it.

If a re-fetched page does not contain the stored quotation, the live page is not treated as a second source. The limitation is written onto the evaluation.
