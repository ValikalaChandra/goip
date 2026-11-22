const CLASSIFICATIONS = ["observed_fact", "derived_fact", "inference", "hypothesis", "unknown"];

function classificationLabel(value) {
  return CLASSIFICATIONS.includes(value) ? value : "unknown";
}

function scoreLine(evaluation) {
  if (!evaluation) return "No versioned evaluation.";
  return [
    `business ${evaluation.business_signal_score}`,
    `technical ${evaluation.technical_evidence_score}`,
    `freelance ${evaluation.freelance_fit_score}`,
    `confidence ${evaluation.confidence}`,
  ].join(" · ");
}

function viewState(kind, message) {
  if (kind === "loading") return `<p class="state" role="status">${message}</p>`;
  if (kind === "empty") return `<p class="state">${message}</p>`;
  return `<p class="state bad" role="alert">${message}</p>`;
}

const GOIPFormat = { CLASSIFICATIONS, classificationLabel, scoreLine, viewState };
if (typeof module !== "undefined" && module.exports) module.exports = GOIPFormat;
if (typeof window !== "undefined") window.GOIPFormat = GOIPFormat;
