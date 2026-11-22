import os

os.environ.setdefault("GOIP_DATABASE_URL", "sqlite+pysqlite:///:memory:")

from datetime import datetime, timedelta, timezone

from app.discovery.sources import _hn_company, matches_focus, parse_hn_hiring_comments
from app.config import FOCUS_SECTORS
from app.discovery.sources import FOCUS_FEEDS, SECTOR_KEYWORDS

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def c(i, text, days=10, author="a"):
    return {"id": i, "author": author, "text": text, "created_at": (NOW - timedelta(days=days)).isoformat()}


def parse(children):
    return parse_hn_hiring_comments(children, thread_id="t", now=NOW, limit=50)


def test_contract_posts_are_kept_with_company_site_and_comment_permalink():
    items = parse([c(1, 'Blackbird | Dev Shop | Remote | Contract<p>Apply: <a href="https:&#x2F;&#x2F;blackbird.dev&#x2F;jobs">jobs</a>')])
    assert len(items) == 1
    item = items[0]
    assert item.company_name == "Blackbird" and item.signal_type == "hiring"
    assert item.website == "https://blackbird.dev/jobs"
    assert item.source_url == "https://news.ycombinator.com/item?id=1"
    assert "Contract" in item.excerpt


def test_stale_negated_and_non_contract_posts_are_dropped():
    items = parse(
        [
            c(1, "OldCo | Engineer | Contract", days=90),
            c(2, "NoFree | Engineer | Remote. We do not hire freelancers or contractors."),
            c(3, "FullTimeCo | Engineer | Remote | Full-time only"),
            c(4, "ConsultCo | We are a consulting firm hiring engineers | Full-time"),
        ]
    )
    assert items == []


def test_label_and_parenthetical_names_are_cleaned():
    assert _hn_company("SEEKING FREELANCER | Devops Engineer | Remote") is None
    assert _hn_company("Sendery (https://sendery.co) | iOS | Tokyo") == "Sendery"
    assert _hn_company("Clad (YC W23) | Software Engineer") == "Clad"
    assert _hn_company("a very long company name that is not plausible at all | x") is None


def test_deleted_comments_and_limit():
    kids = [{"id": 1, "author": None, "text": None}] + [c(i, f"Co{i} | Dev | Contract") for i in range(2, 9)]
    assert len(parse_hn_hiring_comments(kids, thread_id="t", now=NOW, limit=3)) == 3


def test_sector_focus_filter():
    assert matches_focus(None, "anything")
    assert matches_focus("fintech", "Neobank raises Series A")
    assert not matches_focus("fintech", "Gaming studio launches console")


def test_every_sector_has_keywords_and_feed_entries_are_https_dicts():
    assert FOCUS_SECTORS == set(SECTOR_KEYWORDS) == set(FOCUS_FEEDS)
    for feeds in FOCUS_FEEDS.values():
        for f in feeds:
            assert f["url"].startswith("https://") and f["name"] and f["category"].startswith("sector:")


# ---- regression: multi-line sources used to fail their own quote check and be rejected by QA
def test_quote_check_ignores_line_breaks_but_not_words():
    from app.scoring.evidence import quote_supported

    raw = "Blackbird | Dev Shop | Contract\nBlackbird builds web, mobile and IoT products."
    assert quote_supported("Blackbird | Dev Shop | Contract Blackbird builds web, mobile and IoT products.", raw)
    assert not quote_supported("Blackbird | Dev Shop | Full-time Blackbird builds web", raw)  # a changed word still fails
    assert not quote_supported("   \n  ", raw)
    assert not quote_supported("Contract Blackbird builds", "Contract and then Blackbird builds")  # order and adjacency matter


def test_real_shaped_hiring_post_is_qualified_end_to_end():
    from app.scoring.v2 import evaluate

    children = [c(1, 'Blackbird | Dev Shop | Remote (US only) | Contract<p>Blackbird builds web, mobile and IoT products for startups.<p>We need a <i>contractor</i> for an API integration.')]
    item = parse(children)[0]
    ev = evaluate(
        [
            {
                "source_id": "s1", "source_url": item.source_url, "source_name": item.source_name, "raw_text": item.excerpt,
                "quotation": item.excerpt[:400], "published_at": item.published_at.isoformat(), "retrieved_at": item.published_at.isoformat(),
                "fetch_status": "not_refetched", "signal_type": item.signal_type, "live_text": "",
            }
        ]
    )
    assert ev["qualification"] == "freelance_evidence"
    assert ev["qa"]["verdict"] != "reject", ev["qa"]["checks"]


def test_label_like_names_are_rejected():
    assert _hn_company("Location: Estonia Remote:Yes | Backend") is None
    assert _hn_company("Remote | Backend Engineer | Contract") is None


# ---- a person offering their own work is not a company asking for a contractor
def test_job_seeker_posts_are_not_leads():
    seeker = "Location: Estonia Remote:Yes Willing to relocate: No Technologies: React.js, Vue.js Part-time/Freelance: Yes Linkedin: https://www.linkedin.com/in/someone"
    other = "SEEKING WORK | Backend dev | Remote | Freelance, open to contracts"
    third = "Available for hire. Freelance full-stack engineer, 10 years experience"
    company = "Blackbird | Dev Shop | Remote | Contract\nSend your resume to jobs. Willing to sponsor visas."
    items = parse([c(1, seeker), c(2, other), c(3, third), c(4, company)])
    assert [i.company_name for i in items] == ["Blackbird"]  # "resume" and "willing to" alone do not make a seeker


def test_contact_details_are_redacted_from_stored_post_text():
    item = parse([c(1, "Acme | Backend | Contract. Email jane.doe@acme.io or call +91 98765 43210 to apply")])[0]
    assert "@" not in item.excerpt and "98765" not in item.excerpt and "Acme" in item.excerpt


# ------------------------------------------------------------------ job boards
from types import SimpleNamespace as NS

import httpx

import app.discovery.sources as src


def job(i, **kw):
    base = {"id": i, "company_name": f"Acme{i}", "title": "Senior Backend Engineer", "category": "Software Development", "job_type": "contract",
            "publication_date": (NOW - timedelta(days=5)).isoformat(), "url": f"https://remotive.com/remote-jobs/x/{i}", "description": "<p>Build APIs. Python.</p>"}
    base.update(kw)
    return base


def test_remotive_keeps_only_fresh_engineering_contract_and_freelance_roles():
    payload = {"jobs": [
        job(1),
        job(2, job_type="freelance"),
        job(3, job_type="full_time"),
        job(4, publication_date=(NOW - timedelta(days=90)).isoformat()),
        job(5, title="Customer Service Representative", category="Customer Service"),
        job(9, title="Quality and Reliability Engineer", category="Engineering"),        # an engineer, but not software
        job(10, title="AI Trainer - Video Annotation", category="Software Development"),  # annotation gig, not engineering
        job(6, description="We do not hire contractors or freelancers for this."),
        job(7, url="http://insecure.example/job"),
        job(8, company_name="Remote | Company: Inc"),
    ]}
    items = src.parse_remotive(payload, now=NOW, limit=50)
    assert [i.company_name for i in items] == ["Acme1", "Acme2"]
    first = items[0]
    assert first.source_name == "Remotive" and first.signal_type == "hiring" and first.source_url.endswith("/1")
    assert "Engagement type: contract role" in first.excerpt and "Acme1 | Senior Backend Engineer | contract role" == first.title
    assert "freelance engagement" in items[1].title


def test_wwr_keeps_engineering_roles_that_state_a_contract():
    entries = [
        NS(title="Acme: Backend Engineer", link="https://weworkremotely.com/jobs/1", summary="<p>This is a contract role building APIs in Python.</p>", published=(NOW - timedelta(days=3)).isoformat()),
        NS(title="Beta: Backend Engineer", link="https://weworkremotely.com/jobs/2", summary="<p>Full-time position, great benefits.</p>", published=(NOW - timedelta(days=3)).isoformat()),
        NS(title="Gamma: Office Manager", link="https://weworkremotely.com/jobs/3", summary="<p>Contract role managing an office.</p>", published=(NOW - timedelta(days=3)).isoformat()),
        NS(title="Delta: Backend Engineer", link="https://weworkremotely.com/jobs/4", summary="<p>Contract role, python.</p>", published=(NOW - timedelta(days=200)).isoformat()),
        NS(title="no colon in title", link="https://weworkremotely.com/jobs/5", summary="contract role engineer", published=None),
    ]
    items = src.parse_wwr(entries, now=NOW, limit=50)
    assert [i.company_name for i in items] == ["Acme"] and items[0].source_name == "We Work Remotely"


def test_a_job_board_contract_role_is_qualified_end_to_end():
    from app.scoring.v2 import evaluate

    item = src.parse_remotive({"jobs": [job(1)]}, now=NOW, limit=5)[0]
    ev = evaluate([{"source_id": "s1", "source_url": item.source_url, "source_name": item.source_name, "raw_text": item.excerpt,
                    "quotation": item.excerpt[:400], "published_at": item.published_at.isoformat(), "retrieved_at": item.published_at.isoformat(),
                    "fetch_status": "not_refetched", "signal_type": item.signal_type, "live_text": ""}])
    assert ev["qualification"] == "freelance_evidence" and ev["qa"]["verdict"] != "reject"


async def test_fetch_job_boards_uses_pinned_fetches_filters_by_sector_and_caches():
    calls = []
    remotive = {"jobs": [job(1, description="<p>Payments API for banks. Contract engineer.</p>"), job(2, description="<p>Game engine tools.</p>")]}
    rss = "<rss version='2.0'><channel></channel></rss>"
    PUB = lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]

    def handler(request):
        calls.append(request.headers["host"])
        if "remotive" in request.headers["host"]:
            return httpx.Response(200, json=remotive)
        return httpx.Response(200, text=rss)

    src._job_cache.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        items, health = await src.fetch_job_boards(c, 10, "fintech", resolve=PUB)
        assert [i.company_name for i in items] == ["Acme1"]  # the game-tools role is not fintech
        assert {h["name"]: h["status"] for h in health} == {"Remotive": "ok", "We Work Remotely": "ok"}
        await src.fetch_job_boards(c, 10, None, resolve=PUB)
    assert len(calls) == 2  # the second call came from the cache: the boards are not polled again


async def test_a_board_that_is_down_is_recorded_not_fatal():
    PUB = lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    src._job_cache.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as c:
        items, health = await src.fetch_job_boards(c, 10, None, resolve=PUB)
    assert items == [] and all(h["status"] == "failed" for h in health)
