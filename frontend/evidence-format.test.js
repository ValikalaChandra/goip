const assert = require("node:assert/strict");
const { CLASSIFICATIONS, classificationLabel, scoreLine, viewState } = require("./evidence-format");

assert.deepEqual(CLASSIFICATIONS, ["observed_fact", "derived_fact", "inference", "hypothesis", "unknown"]);
assert.equal(classificationLabel("inference"), "inference");
assert.equal(classificationLabel("made-up"), "unknown");
assert.equal(
  scoreLine({ business_signal_score: 70, technical_evidence_score: 25, freelance_fit_score: 0, confidence: "medium" }),
  "business 70 · technical 25 · freelance 0 · confidence medium"
);
assert.equal(scoreLine(null), "No versioned evaluation.");
assert.match(viewState("loading", "Loading opportunities."), /role="status"/);
assert.match(viewState("empty", "No opportunities match this filter."), /No opportunities/);
assert.match(viewState("error", "The list could not be loaded."), /role="alert"/);
console.log("frontend evidence format tests passed");
