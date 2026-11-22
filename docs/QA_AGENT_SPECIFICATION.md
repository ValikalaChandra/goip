# Quality assurance specification

Quality assurance reads the finished evaluation. Completing the earlier stages is not approval.

It checks:

1. Source validity: observed findings exist, and independent domains are counted.
2. Quote accuracy: an observed quotation has to occur in the source. A mismatch is a reject.
3. Claim traceability: an observed finding carries a source id.
4. Fact and inference separation: hypotheses are not stored as observed facts.
5. Score consistency: freelance fit cannot match a high business score unless an external contract is stated.
6. Service relevance: a named service must match an observed requirement. “LLM integration and RAG” needs retrieval, embedding, knowledge-base, or LLM-integration language. An assistant is not enough. An unsupported service is a reject.
7. Missing information: a single source, or confidence below high, is flagged.
8. Unsupported claims: hypotheses are flagged and excluded from the freelance score.

The verdict is the strongest result among the checks: `pass`, `flag`, or `reject`.

A reject does not delete the company and does not send a message to it. It refuses the recommendation and leaves the opportunity for a person.
