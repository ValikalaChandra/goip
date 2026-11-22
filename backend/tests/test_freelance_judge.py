import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest

from app.scoring.v2 import evaluate, valid_verdict

# A real demand signal the keyword rules miss: no "contract" or "freelance" anywhere.
DEMAND = "Acme Payments | Backend | We are looking for an experienced engineer to build our new ledger API over a three month engagement."
SEEKER = "Location: Estonia Willing to relocate: No Technologies: React Part-time/Freelance: Yes I am available for contract work."


def src(text, verdict=None):
    return [{"source_id": "s1", "source_url": "https://news.ycombinator.com/item?id=1", "source_name": "HN", "raw_text": text, "quotation": text[:300],
             "published_at": "2026-11-10T00:00:00+00:00", "retrieved_at": "2026-11-10T00:00:00+00:00", "fetch_status": "not_refetched",
             "signal_type": "hiring", "live_text": "", "model_verdict": verdict}]


def verdict(**kw):
    base = {"is_freelance_opportunity": True, "poster": "company", "engagement": "contract", "work": "engineering", "confidence": "high",
            "quote": "over a three month engagement", "reasoning": "A fixed-length engagement for a named build."}
    base.update(kw)
    return base


def test_the_keyword_rules_alone_miss_this_demand():
    assert evaluate(src(DEMAND))["qualification"] != "freelance_evidence"


def test_a_grounded_company_verdict_finds_demand_the_keywords_missed():
    ev = evaluate(src(DEMAND, verdict()))
    assert ev["qualification"] == "freelance_evidence" and ev["freelance_kind"] == "explicit_contract"
    kinds = {(f["classification"], f["claim"][:30]) for f in ev["findings"]}
    assert any(c == "observed_fact" and "three month engagement" in f["claim"] for f in ev["findings"] for c in [f["classification"]])
    assert any(f["classification"] == "inference" and "reviewer model" in f["claim"] for f in ev["findings"])
    assert ev["qa"]["verdict"] != "reject", ev["qa"]["checks"]


def test_the_verdict_never_sets_a_score_only_the_evidence_kind():
    plain = evaluate(src(DEMAND + " Contractors are welcome to apply."))
    judged = evaluate(src(DEMAND, verdict()))
    assert plain["freelance_kind"] == judged["freelance_kind"] == "explicit_contract"
    assert plain["freelance_fit_score"] == judged["freelance_fit_score"]  # same rule, same number, whoever found the evidence


@pytest.mark.parametrize("bad_quote", ["", "a six month rolling retainer", "OVER A THREE MONTH ENGAGEMENT AND MORE"])
def test_an_invented_or_missing_quote_makes_the_verdict_worthless(bad_quote):
    assert valid_verdict(verdict(quote=bad_quote), DEMAND) is None
    assert evaluate(src(DEMAND, verdict(quote=bad_quote)))["qualification"] != "freelance_evidence"


def test_only_a_company_offering_engineering_work_counts():
    for kw in ({"poster": "individual_seeker"}, {"poster": "recruiter"}, {"poster": "unknown"}, {"work": "other"}, {"is_freelance_opportunity": False}):
        assert evaluate(src(DEMAND, verdict(**kw)))["qualification"] != "freelance_evidence", kw


def test_a_job_seeker_is_vetoed_even_when_the_keywords_match():
    assert evaluate(src(SEEKER))["freelance_kind"] == "explicit_contract"  # the keywords alone are fooled
    vetoed = evaluate(src(SEEKER, verdict(is_freelance_opportunity=False, poster="individual_seeker", engagement="freelance", quote="", reasoning="A person offering their own work.")))
    assert vetoed["freelance_kind"] != "explicit_contract" and vetoed["qualification"] != "freelance_evidence"
    assert any("not a company offering a contract" in f["claim"] for f in vetoed["findings"])


def test_a_low_confidence_veto_is_ignored():
    unsure = verdict(is_freelance_opportunity=False, poster="individual_seeker", engagement="freelance", quote="", confidence="low")
    assert evaluate(src(SEEKER, unsure))["freelance_kind"] == "explicit_contract"


@pytest.mark.parametrize("junk", [None, "yes", [], {}, {"is_freelance_opportunity": True}, verdict(poster="ceo"), verdict(engagement="forever"), verdict(work="art")])
def test_malformed_verdicts_are_ignored(junk):
    assert valid_verdict(junk, DEMAND) is None
    assert evaluate(src(DEMAND, junk))["qualification"] != "freelance_evidence"


def test_a_stored_verdict_is_rechecked_against_the_text_it_is_used_with():
    v = verdict()
    assert valid_verdict(v, DEMAND) is not None
    assert valid_verdict(v, "Acme Payments | Backend | We are hiring a full-time engineer.") is None  # the posting changed: the verdict no longer applies


def test_plural_wording_counts_as_contract_evidence():
    for text in ("We hire freelancers for this.", "Contractors welcome.", "Looking for freelancing engineers.", "We work with contractors on APIs."):
        assert evaluate(src("Acme | " + text))["freelance_kind"] == "explicit_contract", text
