# Qualification rules

A high business-signal score does not qualify a freelance opportunity.

| Evidence | Qualification | What it means |
|---|---|---|
| Product launch, no stated technical need | `research_candidate` | Keep researching. Do not recommend a service. |
| Technical need guessed from a product feature | `hypothesis` | The guess is stored separately and does not raise freelance fit. |
| Explicit engineering requirement or vacancy | `technical_opportunity` | Stronger technical evidence. Still not proof of an external contract. |
| Explicit freelance, contractor, or consulting request | `freelance_evidence` | The strongest fit. A person still approves any contact. |
| QA rejects the reading | verdict `reject` | The recommendation is not accepted. The company stays in review. |

`needs_review` remains the status unless a stored source states an external contract and QA does not reject the evaluation. A future full qualification run uses this gate. It does not copy the freelance score into the historical composite score.

No evaluation creates or sends outreach.
