"""Commercial intent is separate from the three opportunity scores."""

from __future__ import annotations

import re

_EXPLICIT = re.compile(
    r"\b(freelance|freelancer|contractor|consulting engagement|external consultant|"
    r"implementation partner|request for proposal|\brfp\b|outsourc\w*|vendor requirement)\b",
    re.I,
)
_STRONG = re.compile(
    r"\b(contract role|contract engineer|temporary engineering|external technical assistance|"
    r"looking for a consultant)\b",
    re.I,
)
_INDIRECT = re.compile(
    r"\b(launch(?:es|ed|ing)?|raises?|raised|funding|series [a-e]|hiring|job opening|show hn)\b",
    re.I,
)


def assess_commercial_intent(texts: list[str]) -> dict:
    """Read stored text only. This does not claim a vacancy is open."""
    blob = "\n".join(text for text in texts if text).strip()
    if not blob:
        return {
            "classification": "unknown",
            "reason": "No stored source text, so commercial intent is unknown.",
        }
    if _EXPLICIT.search(blob):
        return {
            "classification": "explicit_external",
            "reason": "The stored text uses freelance, contract, consulting, RFP, or vendor language.",
        }
    if _STRONG.search(blob):
        return {
            "classification": "strong_indicator",
            "reason": "The stored text asks for contract or external technical capacity.",
        }
    if _INDIRECT.search(blob):
        return {
            "classification": "indirect_indicator",
            "reason": "The stored text shows business activity. It does not show an external purchase.",
        }
    return {
        "classification": "no_demonstrated_intent",
        "reason": "The stored text has no hiring, launch, funding, or contracting language.",
    }
