from datetime import datetime, timezone

from app.scoring.evidence import decode_text, quote_supported
from app.scoring.v2 import evaluate


def _source(**overrides):
    base = {
        "source_id": "s1",
        "source_url": "https://news.example.com/post",
        "source_name": "Example",
        "raw_text": "Show HN: Acme launched an all-in-one workspace with an AI assistant.",
        "published_at": "2026-11-06T00:00:00+00:00",
        "retrieved_at": "2026-11-08T00:00:00+00:00",
        "fetch_status": "not_refetched",
        "signal_type": "product",
    }
    base.update(overrides)
    return base


def test_product_launch_without_technical_requirement_is_not_a_freelance_opportunity():
    result = evaluate([_source()])
    assert result["qualification"] == "research_candidate"
    assert result["technical_evidence_score"] <= 25
    assert result["freelance_fit_score"] <= 20
    assert result["business_signal_score"] > result["freelance_fit_score"]
    assert result["services"][0]["proposed_service"] is None
    assert "not a probability" in " ".join(result["explanation"])


def test_explicit_integration_requirement_raises_technical_evidence_only():
    text = "Acme launched a product and published an integration requirement: customers must integrate with the public API."
    result = evaluate([_source(raw_text=text, signal_type="product")])
    assert result["technical_kind"] in {"explicit_requirement", "api_requirement"}
    assert result["technical_evidence_score"] >= 80
    assert result["freelance_kind"] == "explicit_requirement_no_contract"
    assert result["freelance_fit_score"] < result["technical_evidence_score"]
    assert result["qualification"] == "technical_opportunity"


def test_engineering_vacancy_is_not_automatic_freelance_work():
    text = "We are hiring a backend engineer. The open role builds the billing service."
    result = evaluate([_source(raw_text=text, signal_type="hiring")])
    assert result["technical_kind"] == "engineering_vacancy"
    assert result["freelance_kind"] == "vacancy_no_outsourcing"
    assert result["freelance_fit_score"] < 50
    assert result["qualification"] == "technical_opportunity"


def test_repository_without_hiring_stays_a_weak_freelance_fit():
    text = "Released the Acme CLI on GitHub."
    result = evaluate([_source(raw_text=text, signal_type="open_source", source_url="https://github.com/acme/cli")])
    assert result["technical_kind"] == "repository_only"
    assert result["freelance_fit_score"] <= 15
    assert result["services"][0]["proposed_service"] is None


def test_explicit_freelance_contract_is_the_strong_fit():
    text = "Acme is looking for a freelance consultant to integrate with our public API."
    result = evaluate([_source(raw_text=text, signal_type="hiring")])
    assert result["freelance_kind"] == "explicit_contract"
    assert result["freelance_fit_score"] >= 80
    assert result["qualification"] == "freelance_evidence"
    assert result["services"][0]["proposed_service"] == "Backend and API development"
    assert result["services"][0]["evidence_classification"] == "observed_fact"


def test_single_source_cannot_be_high_confidence():
    result = evaluate([_source()])
    assert result["independent_sources"] == 1
    assert result["confidence"] == "medium"
    assert result["qa"]["verdict"] in {"flag", "reject"}


def test_two_independent_dated_sources_can_be_high_confidence():
    first = _source(source_id="a", source_url="https://news.example.com/one", raw_text="Acme raises a seed round.")
    second = _source(
        source_id="b",
        source_url="https://blog.other.org/acme",
        source_name="Other",
        signal_type="funding",
        raw_text="Acme raised a seed round to expand the product.",
    )
    result = evaluate([first, second])
    assert result["independent_sources"] == 2
    assert result["confidence"] == "high"


def test_duplicate_url_is_not_a_second_source():
    raw = "Acme launched a workspace."
    result = evaluate(
        [
            _source(source_id="a", raw_text=raw),
            _source(source_id="b", source_url="https://news.example.com/post/", raw_text=raw),
        ]
    )
    assert result["independent_sources"] == 1
    assert any(item["claim"].startswith("This URL repeats") for item in result["findings"])


def test_html_escaped_quotation_is_decoded_and_must_match():
    raw = "We&#x27;ve launched Stitch as one workspace."
    assert "We've" in decode_text(raw)
    result = evaluate([_source(raw_text=raw)])
    observed = [item for item in result["findings"] if item["classification"] == "observed_fact"]
    assert observed
    assert "We've" in observed[0]["quotation"]
    assert quote_supported("We've launched Stitch", raw)
    rejected = evaluate([_source(raw_text=raw, quotation="This sentence was never in the source.")])
    assert any(item["verification_status"].startswith("quote_not_in_source") for item in rejected["findings"])


def test_unsupported_service_does_not_increase_freelance_fit():
    plain = evaluate([_source()], historical_service=None)
    forced = evaluate([_source()], historical_service="LLM integration and RAG")
    assert forced["freelance_fit_score"] == plain["freelance_fit_score"]
    assert forced["qa"]["verdict"] == "reject"
    assert any(check["name"] == "service_relevance" and check["result"] == "reject" for check in forced["qa"]["checks"])


def test_missing_publication_date_is_unknown_and_blocks_high_confidence():
    result = evaluate([_source(published_at=None), _source(source_id="b", source_url="https://blog.other.org/a", published_at=None, raw_text="Acme launched a workspace.")])
    assert any(item["classification"] == "unknown" and "publication date" in item["claim"] for item in result["findings"])
    assert result["confidence"] != "high"


def test_inaccessible_page_is_not_treated_as_empty_evidence():
    result = evaluate([_source(raw_text="", fetch_status="inaccessible")])
    assert result["business_signal_score"] <= 10
    assert result["freelance_fit_score"] == 0
    assert any("could not be fetched" in item["claim"] for item in result["findings"])


def test_assistant_mention_does_not_recommend_rag():
    text = "We launched Stitch.ai, a workspace with Stitchy the AI assistant for freelancers."
    result = evaluate([_source(raw_text=text)], historical_service="LLM integration and RAG")
    assert result["services"][0]["proposed_service"] is None
    assert result["technical_evidence_score"] <= 25
    names = [item["classification"] for item in result["findings"]]
    assert "hypothesis" in names
    assert "observed_fact" in names
