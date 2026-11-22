# Scoring methodology

Version 2 replaces a single composite score with three rankings. The numbers are configuration in `config/runtime.json` under `scoring_v2`. They are ordering rules chosen for this product. They were not fitted to hiring outcomes, and they are not a probability that a company will hire anyone.

The earlier composite score stays on the opportunity row. A new reading is stored as another row in `evaluation_versions`.

## Business signal strength (0–100)

This asks how notable the observed business event is. A product launch, funding announcement, hiring note, partnership, expansion, acquisition, technology note, or public repository can contribute. The score uses the strongest observed signal type, plus a small bonus when two different types are both quoted.

A launch can score in the 70s and still be a weak freelance lead. The business score does not move the freelance score.

## Technical opportunity evidence (0–100)

This asks whether a specific technical requirement is stated.

Explicit requirements, engineering vacancies, API language tied to a need, and stated retrieval or model requirements score higher. A public repository with no hiring note is only a code reference. Mentioning an AI assistant or launching an AI-enabled product is capped. The cap is there so a product description is not treated as a requirement.

## Freelance opportunity fit (0–100)

This asks whether an external freelancer or consultant is a credible reading of the evidence.

An explicit contracting or freelance request is the strong case. A stated technical requirement with no contracting language is a weaker fit, because the company may do the work itself. A job posting is evidence of hiring, not of outsourcing. A hypothesis, including “an assistant might need a model,” cannot raise this score. Recommending a service that the text does not support adds nothing.

## Confidence

Confidence is stored separately.

- High requires verified quotations from at least two independent domains, both dated.
- Medium is one verified quotation.
- Low means the quotation is missing or the page could not be used.

One source is never called corroboration.

## What the old weights still do

`weights` in the same file still describes the retired composite score. Those weights must sum to 100 because the old settings check expects that. New evaluations do not use that blend.
