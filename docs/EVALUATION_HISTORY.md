# Evaluation history

Each scored reading is a row in `evaluation_versions`. A new reading inserts a row. The application cannot update or delete a row after insert. Schema changes that filled linkage on rows written before this field existed used a one-time database statement, and that statement did not change scores.

A version stores:

- its id and version number
- the opportunity id
- `previous_evaluation_id`, empty only on the first version
- the three scores when the method is `v2_dimensions`
- confidence, qualification, and the QA verdict
- findings and services, including source ids
- `config_version`, either `v1_composite` or `scoring_v2-` plus a hash of `config/runtime.json`
- agent contributions copied from stored room messages that name the lead
- the timestamp

The opportunity row still holds the current status and the historical composite score. Those can change when a person reviews the lead. The version rows do not.

A human decision points at the evaluation id it reviewed. The decision is not written back into the evaluation.

`record_if_changed` appends a version only when the source text or the scoring configuration changed. Calling it again with the same inputs returns the current version. That is the path a later rollout should use. `record_evaluation` always appends, and it is the explicit new-version path.

Stitch.ai `G900BE3A9` keeps version 1 (`v1_composite`, score 76) and version 2 (business 70, technical 25, freelance 0). Version 2 points at version 1. Two stored agent messages that name this lead were copied onto both versions when the history columns were added, because those columns did not exist when the versions were first written.
