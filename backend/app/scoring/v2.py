"""Three ranking scores. The numbers are configurable heuristics, not a hiring model."""

from __future__ import annotations

import re

from app.scoring.evidence import canonical_url, decode_text, finding, quote_supported, registrable_domain

# Chosen so a product launch cannot look like a purchase order.
# These are ranking defaults. They are not fitted to outcomes.
DEFAULT_SCORING_V2 = {
    "business_signal": {
        "funding": 85,
        "product": 70,
        "hiring": 75,
        "partnership": 60,
        "expansion": 62,
        "acquisition": 58,
        "technology": 64,
        "open_source": 55,
        "other": 20,
        "multi_signal_bonus": 8,
        "no_quote": 10,
    },
    "technical_evidence": {
        "explicit_requirement": 85,
        "engineering_vacancy": 78,
        "architecture_disclosure": 70,
        "api_requirement": 80,
        "stated_ai_requirement": 75,
        "repository_only": 40,
        "ai_product_mention": 25,
        "none": 0,
    },
    "freelance_fit": {
        "explicit_contract": 85,
        "explicit_requirement_no_contract": 45,
        "vacancy_no_outsourcing": 40,
        "repository_only": 15,
        "hypothesis_cap": 20,
        "unsupported_service_delta": 0,
        "none": 0,
    },
}

_EXPLICIT_REQUIREMENT = re.compile(
    r"\b(technical challenge|integration requirement|must integrate|need(?:s|ed)? to integrate|"
    r"public api|build(?:ing)? an api|api integration)\b",
    re.I,
)
_API = re.compile(r"\bapis?\b", re.I)
_STATED_AI = re.compile(
    r"\b(?:need|require|required|looking for|build|integrate)(?:\s+\w+){0,6}\s+"
    r"(?:llm|rag|retrieval|embedding|vector store|knowledge base)\b",
    re.I,
)
_AI_PRODUCT = re.compile(r"\b(ai assistant|artificial intelligence|powered by ai)\b", re.I)
_HIRING = re.compile(r"\b(hiring|job opening|open role|engineer role|we(?:'re| are) hiring)\b", re.I)
_FREELANCE = re.compile(
    r"\b(freelance|freelancer|contractor|consulting engagement|external consultant|"
    r"looking for a consultant|outsourc\w*)\b",
    re.I,
)
_LAUNCH = re.compile(r"\b(launch(?:es|ed|ing)?|announces|introduces|unveils|show hn)\b", re.I)
_FUNDING = re.compile(r"\b(raises?|raised|series [a-e]|seed round|funding)\b", re.I)
_PARTNER = re.compile(r"\b(partner(?:s|ship|ed)?)\b", re.I)
_EXPANSION = re.compile(r"\b(expands?|expansion|new market|opens an office)\b", re.I)

_SERVICE_TERMS = {
    "LLM integration and RAG": ("rag", "retrieval", "embedding", "vector store", "knowledge base", "llm integration"),
    "Backend and API development": ("api", "backend"),
    "AI and machine learning development": ("machine learning", "model training", "ml pipeline"),
    "Data engineering and analytics": ("data pipeline", "warehouse", "analytics platform"),
    "Cloud infrastructure and deployment": ("kubernetes", "cloud migration", "infrastructure"),
    "Agentic workflow automation": ("agent workflow", "automation pipeline"),
    "Web application development": ("web application", "frontend"),
    "Software engineering consulting": ("software engineering", "engineering team"),
}

_TECHNICAL_RANK = {
    "none": 0,
    "ai_product_mention": 1,
    "repository_only": 2,
    "architecture_disclosure": 3,
    "engineering_vacancy": 4,
    "api_requirement": 5,
    "stated_ai_requirement": 6,
    "explicit_requirement": 7,
}


def scoring_config_version(runtime: dict | None = None) -> str:
    """Identity of the ranking configuration. A change here means a new reading, not a new science."""
    import hashlib
    import json

    payload = json.dumps(scoring_config(runtime), sort_keys=True, separators=(",", ":"))
    return "scoring_v2-" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def scoring_config(runtime: dict | None = None) -> dict:
    merged = {
        "business_signal": dict(DEFAULT_SCORING_V2["business_signal"]),
        "technical_evidence": dict(DEFAULT_SCORING_V2["technical_evidence"]),
        "freelance_fit": dict(DEFAULT_SCORING_V2["freelance_fit"]),
    }
    custom = (runtime or {}).get("scoring_v2") or {}
    for group, values in custom.items():
        if group in merged and isinstance(values, dict):
            merged[group].update(values)
    return merged


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _verified_sources(sources: list[dict]) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for source in sources:
        url = canonical_url(source.get("source_url") or "")
        if url and url in seen:
            source = {**source, "duplicate": True}
        elif url:
            seen.add(url)
            source = {**source, "duplicate": False}
        else:
            source = {**source, "duplicate": False}
        raw = source.get("raw_text") or ""
        source = {**source, "decoded_text": decode_text(raw), "canonical_url": url}
        kept.append(source)
    return kept


def _technical_kind(text: str, signal_type: str) -> str:
    if _STATED_AI.search(text):
        return "stated_ai_requirement"
    if _EXPLICIT_REQUIREMENT.search(text):
        return "explicit_requirement"
    if _API.search(text) and re.search(r"\b(need|require|build|integrat|public)\b", text, re.I):
        return "api_requirement"
    if signal_type == "hiring" or _HIRING.search(text):
        return "engineering_vacancy"
    if signal_type == "open_source":
        return "repository_only"
    if signal_type == "product" or _LAUNCH.search(text) or _AI_PRODUCT.search(text):
        return "ai_product_mention"
    return "none"


def _service_supported(name: str, texts: list[str]) -> bool:
    terms = _SERVICE_TERMS.get(name) or ()
    blob = "\n".join(texts).lower()
    return any(term in blob for term in terms)


def evaluate(sources: list[dict], *, runtime: dict | None = None, historical_service: str | None = None) -> dict:
    """Score one company from source records. Unsupported claims do not raise freelance fit."""
    config = scoring_config(runtime)
    prepared = _verified_sources(sources)
    findings = []
    observed_types: list[str] = []
    technical_kinds: list[str] = []
    freelance_kind = "none"
    requirement_texts: list[str] = []
    domains: set[str] = set()
    dated = 0
    quote_verified = 0

    for source in prepared:
        raw = source.get("raw_text") or ""
        text = source.get("decoded_text") or ""
        fetch_status = source.get("fetch_status") or "not_fetched"
        published = _iso(source.get("published_at"))
        retrieved = _iso(source.get("retrieved_at"))
        if source.get("duplicate"):
            findings.append(
                finding(
                    claim="This URL repeats a source already counted.",
                    classification="derived_fact",
                    source_id=str(source.get("source_id") or ""),
                    source_url=source.get("source_url") or "",
                    published_at=published,
                    retrieved_at=retrieved,
                    confidence="medium",
                    fetch_status=fetch_status,
                    raw_text=raw,
                )
            )
            continue
        if fetch_status == "inaccessible":
            findings.append(
                finding(
                    claim="The page could not be fetched. That is an access failure, not evidence that the page has no relevant text.",
                    classification="unknown",
                    source_id=str(source.get("source_id") or ""),
                    source_url=source.get("source_url") or "",
                    published_at=published,
                    retrieved_at=retrieved,
                    confidence="low",
                    fetch_status=fetch_status,
                    raw_text=raw,
                )
            )
            continue
        signal_type = source.get("signal_type") or "other"
        quotation = (source.get("quotation") or text).strip()
        if quotation and not quote_supported(quotation, raw):
            findings.append(
                finding(
                    claim=quotation,
                    classification="observed_fact",
                    source_id=str(source.get("source_id") or ""),
                    source_url=source.get("source_url") or "",
                    quotation=quotation,
                    raw_text=raw,
                    published_at=published,
                    retrieved_at=retrieved,
                    fetch_status=fetch_status,
                )
            )
            continue
        if not text.strip():
            findings.append(
                finding(
                    claim="The stored source has no text, so it contributes no evidence.",
                    classification="unknown",
                    source_id=str(source.get("source_id") or ""),
                    source_url=source.get("source_url") or "",
                    published_at=published,
                    retrieved_at=retrieved,
                    confidence="low",
                    fetch_status=fetch_status,
                    raw_text=raw,
                )
            )
            continue
        excerpt = text.strip().replace("\n", " ")[:400]
        findings.append(
            finding(
                claim=f"Stored {signal_type} source: {excerpt[:220]}",
                classification="observed_fact",
                source_id=str(source.get("source_id") or ""),
                source_url=source.get("source_url") or "",
                quotation=excerpt,
                raw_text=raw,
                published_at=published,
                retrieved_at=retrieved,
                confidence="medium" if published else "low",
                fetch_status=fetch_status,
            )
        )
        quote_verified += 1
        observed_types.append(signal_type)
        domain = registrable_domain(source.get("source_url") or "")
        if domain:
            domains.add(domain)
        if published:
            dated += 1
        kind = _technical_kind(text, signal_type)
        technical_kinds.append(kind)
        if kind in {"explicit_requirement", "api_requirement", "stated_ai_requirement", "engineering_vacancy"}:
            requirement_texts.append(text)
        if _FREELANCE.search(text):
            freelance_kind = "explicit_contract"
        if kind == "ai_product_mention":
            findings.append(
                finding(
                    claim="An assistant or AI-enabled product is mentioned. That does not state an LLM, retrieval, or integration requirement.",
                    classification="hypothesis",
                    source_id=str(source.get("source_id") or ""),
                    source_url=source.get("source_url") or "",
                    quotation="",
                    published_at=published,
                    retrieved_at=retrieved,
                    confidence="low",
                    fetch_status=fetch_status,
                    raw_text=raw,
                )
            )

    business_points = config["business_signal"]
    if not observed_types:
        business = business_points["no_quote"] if sources else 0
    else:
        business = max(int(business_points.get(item, business_points["other"])) for item in observed_types)
        if len(set(observed_types)) > 1:
            business = min(100, business + int(business_points["multi_signal_bonus"]))
    business = max(0, min(100, business))

    technical_points = config["technical_evidence"]
    best_kind = "none"
    for kind in technical_kinds:
        if _TECHNICAL_RANK.get(kind, 0) > _TECHNICAL_RANK.get(best_kind, 0):
            best_kind = kind
    technical = int(technical_points.get(best_kind, 0))

    fit_points = config["freelance_fit"]
    if freelance_kind != "explicit_contract":
        if best_kind in {"explicit_requirement", "api_requirement", "stated_ai_requirement"}:
            freelance_kind = "explicit_requirement_no_contract"
        elif best_kind == "engineering_vacancy":
            freelance_kind = "vacancy_no_outsourcing"
        elif best_kind == "repository_only":
            freelance_kind = "repository_only"
        elif best_kind in {"ai_product_mention", "none"}:
            freelance_kind = "none"
    freelance = int(fit_points.get(freelance_kind, 0))
    if best_kind in {"ai_product_mention", "none"} and freelance_kind != "explicit_contract":
        freelance = min(freelance, int(fit_points["hypothesis_cap"]))
    freelance += int(fit_points["unsupported_service_delta"])
    freelance = max(0, min(100, freelance))

    services = []
    for name, _terms in _SERVICE_TERMS.items():
        if _service_supported(name, requirement_texts):
            services.append(
                {
                    "proposed_service": name,
                    "supporting_requirement": best_kind,
                    "evidence_classification": "observed_fact",
                    "why": "The stored text states a requirement that matches this service. It does not show a contract.",
                    "confidence": "medium" if len(domains) == 1 else "high",
                    "missing": "Whether the company will hire an external specialist is not stated."
                    if freelance_kind != "explicit_contract"
                    else "Commercial terms are not stated.",
                    "source_urls": [source.get("source_url") for source in prepared if not source.get("duplicate")],
                }
            )
    if not services:
        services.append(
            {
                "proposed_service": None,
                "supporting_requirement": None,
                "evidence_classification": "unknown",
                "why": "Further research. No observed requirement supports a service recommendation.",
                "confidence": "low",
                "missing": "A stated technical task, a vacancy, or an external-contracting note.",
                "source_urls": [],
            }
        )

    independent = len(domains)
    if independent >= 2 and quote_verified >= 2 and dated >= 2:
        confidence = "high"
    elif quote_verified >= 1:
        confidence = "medium"
    else:
        confidence = "low"
    if independent < 2 and confidence == "high":
        confidence = "medium"

    if freelance_kind == "explicit_contract" and best_kind != "none":
        qualification = "freelance_evidence"
    elif best_kind in {"explicit_requirement", "api_requirement", "stated_ai_requirement", "engineering_vacancy"}:
        qualification = "technical_opportunity"
    elif best_kind == "ai_product_mention":
        qualification = "research_candidate"
    elif observed_types:
        qualification = "research_candidate"
    else:
        qualification = "unknown"

    findings.append(
        finding(
            claim=(
                f"{independent} independent source domain(s) and {quote_verified} quotation(s) verified against stored text. "
                "One source is not corroboration."
                if independent < 2
                else f"{independent} independent source domains contain verified quotations."
            ),
            classification="derived_fact",
            confidence=confidence,
            fetch_status="not_fetched",
        )
    )
    if dated < quote_verified:
        findings.append(
            finding(
                claim="At least one verified source has no publication date.",
                classification="unknown",
                confidence="low",
                fetch_status="not_fetched",
            )
        )

    qa = _qa(
        findings=findings,
        business=business,
        technical=technical,
        freelance=freelance,
        confidence=confidence,
        independent=independent,
        qualification=qualification,
        services=services,
        historical_service=historical_service,
        requirement_texts=requirement_texts,
    )
    if qa["verdict"] == "reject" and historical_service and not services[0].get("proposed_service"):
        qualification = qualification if qualification != "unknown" else "research_candidate"

    limitations = [
        "These scores are ranking heuristics from the scoring_v2 configuration. They are not a probability of hiring.",
        "Service relevance is scored only from language in the stored sources.",
    ]
    if independent < 2:
        limitations.append("Only one independent source domain is recorded, so the sources do not corroborate each other.")
    if any(source.get("fetch_status") == "not_refetched" for source in prepared):
        limitations.append("At least one source was not re-fetched for this evaluation. The quotation was checked against the stored text only.")
    if any(source.get("fetch_status") == "inaccessible" for source in prepared):
        limitations.append("At least one page was inaccessible. That is different from a page that was read and contained no relevant evidence.")

    return {
        "business_signal_score": business,
        "technical_evidence_score": technical,
        "freelance_fit_score": freelance,
        "confidence": confidence,
        "qualification": qualification,
        "technical_kind": best_kind,
        "freelance_kind": freelance_kind,
        "independent_sources": independent,
        "findings": findings,
        "services": services,
        "qa": qa,
        "limitations": " ".join(limitations),
        "explanation": [
            f"Business signal strength is {business}/100 from observed signal types {sorted(set(observed_types)) or ['none']}.",
            f"Technical opportunity evidence is {technical}/100 ({best_kind}). An AI product mention is capped and is not a requirement.",
            f"Freelance opportunity fit is {freelance}/100 ({freelance_kind}). A high business signal does not raise this score.",
            "The score is not a probability that the company will hire anyone.",
        ],
    }


def _qa(
    *,
    findings: list[dict],
    business: int,
    technical: int,
    freelance: int,
    confidence: str,
    independent: int,
    qualification: str,
    services: list[dict],
    historical_service: str | None,
    requirement_texts: list[str],
) -> dict:
    checks = []

    def add(name: str, result: str, detail: str) -> None:
        checks.append({"name": name, "result": result, "detail": detail})

    observed = [item for item in findings if item["classification"] == "observed_fact"]
    add(
        "source_validity",
        "pass" if observed else "flag",
        f"{len(observed)} observed finding(s) from {independent} independent domain(s).",
    )
    bad_quotes = [item for item in findings if "quote_not_in_source" in item.get("verification_status", "")]
    add(
        "quote_accuracy",
        "reject" if bad_quotes else "pass",
        "Every observed quotation was found in the stored source." if not bad_quotes else "A quotation was not in its source and was not kept as a fact.",
    )
    add(
        "claim_traceability",
        "pass" if all(item.get("source_id") or item["classification"] != "observed_fact" for item in findings) else "flag",
        "Observed findings carry a source id.",
    )
    mixed = [item for item in findings if item["classification"] == "observed_fact" and "does not state" in item["claim"].lower()]
    add(
        "fact_inference_separation",
        "flag" if mixed else "pass",
        "Hypothesis findings are stored separately from observed facts.",
    )
    inflated = business >= 70 and freelance >= 70 and qualification != "freelance_evidence"
    add(
        "score_consistency",
        "reject" if inflated else "pass",
        "Freelance fit stays below the business signal unless an external contract is stated."
        if not inflated
        else "Freelance fit was as high as the business signal without contract evidence.",
    )
    proposed = [item for item in services if item.get("proposed_service")]
    if historical_service and not _service_supported(historical_service, requirement_texts):
        add(
            "service_relevance",
            "reject",
            f"The earlier recommendation '{historical_service}' has no observed requirement in the stored sources.",
        )
    elif proposed and any(item["evidence_classification"] != "observed_fact" for item in proposed):
        add("service_relevance", "reject", "A service was recommended without an observed requirement.")
    elif proposed:
        add("service_relevance", "pass", "Each recommended service matches language in an observed requirement.")
    else:
        add("service_relevance", "pass", "No service was recommended. Further research is the result.")
    missing = []
    if independent < 2:
        missing.append("a second independent source")
    if confidence != "high":
        missing.append("enough dated sources for high confidence")
    add(
        "missing_information",
        "flag" if missing else "pass",
        ", ".join(missing) if missing else "No extra gap was recorded by this check.",
    )
    unsupported = [item for item in findings if item["classification"] == "hypothesis"]
    add(
        "unsupported_claims",
        "flag" if unsupported else "pass",
        "Hypothesis claims are present and are excluded from the freelance score." if unsupported else "No hypothesis claim was added.",
    )
    order = {"pass": 0, "flag": 1, "reject": 2}
    verdict = max(checks, key=lambda item: order[item["result"]])["result"] if checks else "flag"
    if confidence == "high" and independent < 2:
        verdict = "reject"
        add("false_corroboration", "reject", "High confidence requires more than one independent source.")
    return {"verdict": verdict, "checks": checks, "technical_score": technical, "freelance_score": freelance}
