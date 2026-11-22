from __future__ import annotations

from dataclasses import dataclass


DEFAULT_WEIGHTS = {
    "signal_strength": 25,
    "technical_demand": 25,
    "service_relevance": 20,
    "timing": 15,
    "accessibility": 10,
    "evidence_quality": 5,
}

SIGNAL_STRENGTH = {
    "funding": 90,
    "product": 78,
    "hiring": 70,
    "partnership": 64,
    "expansion": 66,
    "acquisition": 60,
    "technology": 58,
    "other": 30,
}

SERVICE_BY_SIGNAL = {
    "funding": "Backend and API development",
    "product": "LLM integration and RAG",
    "hiring": "Software engineering consulting",
    "partnership": "Agentic workflow automation",
    "expansion": "Cloud infrastructure and deployment",
    "acquisition": "Data engineering and analytics",
    "technology": "AI and machine learning development",
    "other": "Software engineering consulting",
}


@dataclass
class ScoreResult:
    total: int
    confidence: str
    components: dict
    explanation: list[str]
    recommended_service: str


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


def score_opportunity(
    *,
    signal_types: list[str],
    evidence_count: int,
    has_source_url: bool,
    has_quote: bool,
    days_old: int | None,
    has_website: bool,
    service_match: bool,
    github_support: bool,
    weights: dict | None = None,
) -> ScoreResult:
    weights = weights or DEFAULT_WEIGHTS
    distinct = [item for item in dict.fromkeys(signal_types) if item]
    primary = distinct[0] if distinct else "other"
    strength = SIGNAL_STRENGTH.get(primary, 30)
    if len(distinct) > 1:
        strength = min(100, strength + 8)

    technical = 35
    if "hiring" in distinct or "technology" in distinct:
        technical = 75
    if "product" in distinct:
        technical = max(technical, 70)
    if github_support:
        technical = min(100, technical + 10)

    relevance = 72 if service_match else 40
    if days_old is None:
        timing = 45
    elif days_old <= 14:
        timing = 90
    elif days_old <= 45:
        timing = 70
    elif days_old <= 120:
        timing = 45
    else:
        timing = 20

    accessibility = 70 if has_website else 35
    evidence = 20
    if has_source_url:
        evidence += 40
    if has_quote:
        evidence += 25
    if evidence_count > 1:
        evidence += 15
    evidence = _clamp(evidence)

    parts = {
        "signal_strength": _clamp(strength),
        "technical_demand": _clamp(technical),
        "service_relevance": _clamp(relevance),
        "timing": _clamp(timing),
        "accessibility": _clamp(accessibility),
        "evidence_quality": evidence,
    }
    total = 0
    for key, weight in weights.items():
        total += parts.get(key, 0) * int(weight)
    total = int(round(total / 100))
    independent = evidence_count >= 2 and has_source_url and has_quote
    if independent and total >= 60:
        confidence = "high"
    elif has_source_url and has_quote:
        confidence = "medium"
    else:
        confidence = "low"
    explanation = [
        f"Primary signal '{primary}' scored {parts['signal_strength']}/100 for signal strength.",
        f"Technical-demand component is {parts['technical_demand']}/100"
        + (" with a related public repository." if github_support else "."),
        f"Timing component is {parts['timing']}/100"
        + (f" from a signal about {days_old} days old." if days_old is not None else " because no publication date was parsed."),
        f"Evidence quality is {parts['evidence_quality']}/100 across {evidence_count} source record(s).",
        "This score ranks research priority. It is not a probability that the company will hire anyone.",
    ]
    return ScoreResult(
        total=total,
        confidence=confidence,
        components=parts,
        explanation=explanation,
        recommended_service=SERVICE_BY_SIGNAL.get(primary, SERVICE_BY_SIGNAL["other"]),
    )
