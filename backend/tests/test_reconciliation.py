import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.commercial import assess_commercial_intent
from app.db import Company, Opportunity, PipelineRun, Signal, make_engine, make_session_factory, upgrade, utcnow
from app.reconciliation import apply_human_action, classify_signal, record_inspection
from app.scoring.evidence import canonical_url


def _session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    upgrade(engine)
    return make_session_factory(engine)()


def test_canonical_url_keeps_hacker_news_item_ids():
    first = canonical_url("https://news.ycombinator.com/item?id=1")
    second = canonical_url("https://news.ycombinator.com/item?id=2")
    assert first != second
    assert canonical_url("https://Example.com/a/#frag") == "https://example.com/a"


def test_domain_match_is_confirmed_and_headline_mention_is_not():
    companies = [
        {"id": "meta", "name": "Meta", "normalized_name": "meta", "domain": "meta.com"},
        {"id": "other", "name": "Other", "normalized_name": "other", "domain": None},
    ]
    confirmed = classify_signal(
        title="Meta platform notes",
        identity_hint="meta",
        source_url="https://meta.com/news",
        companies=companies,
        linked_urls=set(),
    )
    assert confirmed["classification"] == "confirmed_match"
    mention = classify_signal(
        title="Former Meta Security Chief Calls Password Access Insane",
        identity_hint="former meta security chief",
        source_url="https://epyhia.com/story",
        companies=companies,
        linked_urls=set(),
    )
    assert mention["classification"] == "ambiguous_match"
    assert mention["candidate_company_id"] == "meta"
    duplicate = classify_signal(
        title="Again",
        identity_hint="again",
        source_url="https://example.com/a",
        companies=companies,
        linked_urls={"https://example.com/a"},
    )
    assert duplicate["classification"] == "duplicate_signal"
    unknown = classify_signal(
        title="Writing as a Thinking Tool",
        identity_hint="writing as a thinking tool",
        source_url="http://muratbuffalo.blogspot.com/post",
        companies=companies,
        linked_urls=set(),
    )
    assert unknown["classification"] == "unmatched"


def test_inspection_is_repeatable_and_confirm_is_explicit():
    session = _session()
    company = Company(
        id=str(uuid.uuid4()),
        identity_key="meta",
        name="Meta",
        normalized_name="meta",
        domain="meta.com",
        created_at=utcnow(),
    )
    run = PipelineRun(id=str(uuid.uuid4()), status="completed", trigger="test", targets={}, counts={}, started_at=utcnow())
    orphan = Signal(
        id=str(uuid.uuid4()),
        company_id=None,
        run_id=run.id,
        identity_hint="former meta security",
        source_name="Hacker News",
        source_url="https://epyhia.com/story",
        category="news",
        title="Former Meta Security Chief Calls Password Access Insane",
        evidence="A headline mentions Meta.",
        signal_type="other",
        published_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        discovered_at=utcnow(),
    )
    owned = Signal(
        id=str(uuid.uuid4()),
        company_id=None,
        run_id=run.id,
        identity_hint="meta",
        source_name="Company site",
        source_url="https://meta.com/blog",
        category="product",
        title="Meta platform notes",
        evidence="Posted on the company host.",
        signal_type="product",
        published_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        discovered_at=utcnow(),
    )
    plain = Signal(
        id=str(uuid.uuid4()),
        company_id=None,
        run_id=run.id,
        identity_hint="writing",
        source_name="Hacker News",
        source_url="http://example.com/writing",
        category="news",
        title="Writing as a Thinking Tool",
        evidence="An essay.",
        signal_type="other",
        published_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        discovered_at=utcnow(),
    )
    session.add_all([company, run, orphan, owned, plain])
    session.commit()
    first = record_inspection(session)
    second = record_inspection(session)
    assert first["created"] == 3
    assert second["created"] == 0
    assert second["skipped"] == 2
    session.refresh(orphan)
    session.refresh(owned)
    assert orphan.company_id is None
    assert owned.company_id == company.id
    apply_human_action(session, orphan.id, "confirm", company_id=company.id, note="Checked the host.", actor="operator")
    session.refresh(orphan)
    assert orphan.company_id == company.id
    opportunity = Opportunity(
        id=str(uuid.uuid4()),
        public_id="GTEST9999",
        run_id=run.id,
        company_id=company.id,
        status="needs_review",
        score=70,
        facts=[],
        inferences=[],
        recommendations=[],
    )
    session.add(opportunity)
    session.commit()
    before = session.scalar(select(func.count()).select_from(Opportunity))
    record_inspection(session)
    assert session.scalar(select(func.count()).select_from(Opportunity)) == before


def test_commercial_intent_stays_separate_from_a_launch():
    launch = assess_commercial_intent(["Our team is excited to launch Example this week."])
    assert launch["classification"] == "indirect_indicator"
    explicit = assess_commercial_intent(["We are hiring a freelance contractor for the API."])
    assert explicit["classification"] == "explicit_external"
    empty = assess_commercial_intent([""])
    assert empty["classification"] == "unknown"


def _co(i, name, domain=None):
    from app.discovery.extract import normalize_name

    return {"id": i, "name": name, "normalized_name": normalize_name(name), "domain": domain}


def _classify(title, url, companies, linked=()):
    return classify_signal(title=title, identity_hint="", source_url=url, companies=companies, linked_urls=set(linked))


def test_every_class_explains_itself_with_checks_candidate_and_next_step():
    cos = [_co("c1", "Acme", "acme.io"), _co("c2", "Acme Labs", None)]
    cases = {
        "confirmed_match": _classify("Acme launches x", "https://acme.io/blog/x", cos),
        "probable_match": _classify("Acme raises $20M Series A", "https://techcrunch.com/a", [_co("c1", "Acme")]),
        "ambiguous_match": _classify("Investors back Acme in a crowded market", "https://techcrunch.com/b", [_co("c1", "Acme")]),
        "unmatched": _classify("Markets move on rate news", "https://techcrunch.com/c", cos),
        "duplicate_signal": _classify("Acme raises", "https://techcrunch.com/a", cos, linked={"https://techcrunch.com/a"}),
    }
    for expected, result in cases.items():
        assert result["classification"] == expected
        r = result["reasoning"]
        assert r["headline"] and r["class_meaning"] and r["to_confirm"] and len(r["checks"]) >= 1
        assert all(c["status"] in {"pass", "fail", "info", "warn"} and c["detail"] for c in r["checks"])
    assert cases["confirmed_match"]["reasoning"]["candidate"]["basis"] == "domain"
    prob = cases["probable_match"]["reasoning"]
    assert prob["candidate"]["name"] == "Acme" and prob["candidate"]["basis"] == "name"
    assert "publisher" in prob["why_not_higher"] and prob["host_is_publisher"] is True
    assert "identity" in prob["why_not_higher"] or "name match" in prob["why_not_higher"].lower()
    assert cases["unmatched"]["reasoning"]["candidate"] is None and cases["unmatched"]["reasoning"]["why_not_higher"]


def test_ambiguous_domain_lists_the_alternatives():
    cos = [_co("c1", "Foo", "shared.io"), _co("c2", "Bar", "shared.io")]
    result = _classify("Something happened", "https://shared.io/news", cos)
    assert result["classification"] == "ambiguous_match" and result["candidate_company_id"] is None
    assert {a["name"] for a in result["reasoning"]["alternatives"]} == {"Foo", "Bar"}
