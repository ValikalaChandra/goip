from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import httpx

from app.discovery.extract import RawItem, _plausible_company_name, is_publisher, parse_datetime, registrable_domain
from app.discovery.focus import SECTOR_KEYWORDS, matches_focus  # noqa: F401  (re-exported)
from app.guardrails import redact_pii
from app.security.url_safety import UnsafeURL, acheck_url, check_url, pinned_request

MAX_RESPONSE_BYTES = 3_000_000


async def get_capped(client: httpx.AsyncClient, url: str, *, timeout: float = 25, max_bytes: int = MAX_RESPONSE_BYTES, resolve=None, **kwargs) -> httpx.Response:
    """GET that (1) validates the URL, (2) connects to the validated IP so DNS cannot change between check and
    connect, and (3) refuses to buffer more than max_bytes of decoded body."""
    import socket

    checked = await acheck_url(url, resolve=resolve or socket.getaddrinfo)
    caller_headers = kwargs.pop("headers", None) or {}
    last_error: Exception | None = None
    for ip in checked.ips[:3]:
        pinned, host_header, extensions = pinned_request(checked, ip)
        try:
            async with client.stream("GET", pinned, headers={**caller_headers, **host_header}, extensions=extensions, timeout=timeout, **kwargs) as response:
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ValueError("response_too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError("response_too_large")
                # aiter_bytes() already decoded the body, so the encoding/length headers no longer describe it.
                kept = {k: v for k, v in response.headers.items() if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}}
                return httpx.Response(status_code=response.status_code, headers=kept, content=bytes(body), request=httpx.Request("GET", url))
        except httpx.ConnectError as exc:  # try the next validated address
            last_error = exc
    raise last_error or httpx.ConnectError("no address")


HN_QUERIES = ("raises", "series A", "launches AI", "Show HN")
RSS_FEEDS = (
    {
        "name": "Hacker News front page",
        "url": "https://news.ycombinator.com/rss",
        "category": "community",
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "category": "news",
    },
)


async def fetch_hacker_news(client: httpx.AsyncClient, hits: int) -> tuple[list[RawItem], str | None]:
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=21)).timestamp())
    items: list[RawItem] = []
    errors: list[str] = []
    per_query = max(5, hits // len(HN_QUERIES))
    for query in HN_QUERIES:
        url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            f"?query={quote_plus(query)}&tags=story&hitsPerPage={per_query}"
            f"&numericFilters=created_at_i>{cutoff}"
        )
        try:
            response = await get_capped(client, url, timeout=25)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - source errors are recorded, not fatal
            errors.append(f"{query}: {exc.__class__.__name__}")
            continue
        for hit in payload.get("hits") or []:
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            try:
                await acheck_url(story_url)
            except UnsafeURL:
                continue
            items.append(
                RawItem(
                    source_name="Hacker News",
                    source_url=story_url,
                    title=hit.get("title") or "",
                    excerpt=(hit.get("story_text") or "")[:1500],
                    category="community",
                    access_method="hn_algolia_api",
                    published_at=parse_datetime(hit.get("created_at")),
                    extra={"points": hit.get("points"), "hn_url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}"},
                ).prepare()
            )
    return items, "; ".join(errors) or None


async def fetch_rss(client: httpx.AsyncClient, per_feed: int, feeds=None) -> tuple[list[RawItem], list[dict]]:
    import feedparser

    items: list[RawItem] = []
    health: list[dict] = []
    for feed in (feeds if feeds is not None else RSS_FEEDS):
        try:
            response = await get_capped(client, feed["url"], timeout=25, follow_redirects=False)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURL("redirect without location")
                await acheck_url(location)
                response = await get_capped(client, location, timeout=25, follow_redirects=False)
            response.raise_for_status()
            parsed = feedparser.parse(response.text)
            count = 0
            for entry in (parsed.entries or [])[:per_feed]:
                link = getattr(entry, "link", "") or ""
                try:
                    await acheck_url(link)
                except UnsafeURL:
                    continue
                published = parse_datetime(getattr(entry, "published", None) or getattr(entry, "updated", None))
                summary = getattr(entry, "summary", "") or ""
                items.append(
                    RawItem(
                        source_name=feed["name"],
                        source_url=link,
                        title=getattr(entry, "title", "") or "",
                        excerpt=summary[:1500],
                        category=feed["category"],
                        access_method="rss",
                        published_at=published,
                    ).prepare()
                )
                count += 1
            health.append(
                {
                    "name": feed["name"],
                    "parent_domain": registrable_domain(feed["url"]) or "",
                    "category": feed["category"],
                    "access_method": "rss",
                    "status": "ok",
                    "records": count,
                    "error": None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            health.append(
                {
                    "name": feed["name"],
                    "parent_domain": registrable_domain(feed["url"]) or "",
                    "category": feed["category"],
                    "access_method": "rss",
                    "status": "failed",
                    "records": 0,
                    "error": exc.__class__.__name__,
                }
            )
    return items, health


async def fetch_github(client: httpx.AsyncClient, hits: int) -> tuple[list[dict], str | None]:
    query = quote_plus("LLM agent OR RAG stars:>20 pushed:>2026-09-01")
    url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page={hits}"
    try:
        response = await get_capped(client, 
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "GOIP-research"},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return [], exc.__class__.__name__
    repos = []
    for item in payload.get("items") or []:
        license_info = item.get("license") or {}
        repos.append(
            {
                "name": item.get("full_name"),
                "url": item.get("html_url"),
                "description": item.get("description") or "",
                "license": license_info.get("spdx_id") or license_info.get("name"),
                "updated_at": item.get("pushed_at"),
                "stars": item.get("stargazers_count"),
                "topics": item.get("topics") or [],
            }
        )
    return repos, None


async def crawl4ai_search(client: httpx.AsyncClient, base_url: str, api_key: str, query: str) -> tuple[list[dict], str | None]:
    if not api_key:
        return [], "missing_api_key"
    url = f"{base_url.rstrip('/')}/search?q={quote_plus(query)}"
    try:
        response = await get_capped(client, 
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=40,
        )
        if response.status_code >= 400:
            return [], f"http_{response.status_code}"
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return [], exc.__class__.__name__
    results = payload.get("results") or payload.get("data") or payload.get("items") or []
    if isinstance(payload, list):
        results = payload
    cleaned = []
    for item in results:
        if not isinstance(item, dict):
            continue
        link = item.get("url") or item.get("link")
        if not link:
            continue
        try:
            await acheck_url(link)
        except UnsafeURL:
            continue
        cleaned.append(
            {
                "title": item.get("title") or "",
                "url": link,
                "snippet": item.get("snippet") or item.get("description") or "",
            }
        )
    return cleaned, None


async def crawl4ai_scrape(client: httpx.AsyncClient, base_url: str, api_key: str, url: str) -> tuple[str, str | None]:
    await acheck_url(url)
    response = await client.post(
        f"{base_url.rstrip('/')}/scrape",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        content=json.dumps({"url": url, "format": "md"}),
        timeout=90,
    )
    if response.status_code >= 400:
        return "", f"http_{response.status_code}"
    payload = response.json()
    if payload.get("ok") is False:
        return "", str(payload.get("error") or "not_ok")
    return (payload.get("markdown") or "")[:8000], None


# ----------------------------------------------------------------------------- sector focus

FOCUS_FEEDS: dict[str, tuple[dict, ...]] = {
    "fintech": (
        {"name": "TechCrunch Fintech", "url": "https://techcrunch.com/category/fintech/feed/", "category": "sector:fintech"},
        {"name": "Finextra", "url": "https://www.finextra.com/rss/headlines.aspx", "category": "sector:fintech"},
    ),
    "ai": ({"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "sector:ai"},),
    "cybersecurity": (
        {"name": "TechCrunch Security", "url": "https://techcrunch.com/category/security/feed/", "category": "sector:cybersecurity"},
        {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "category": "sector:cybersecurity"},
    ),
    "healthtech": ({"name": "Fierce Healthcare", "url": "https://www.fiercehealthcare.com/rss/xml", "category": "sector:healthtech"},),
    "edtech": ({"name": "EdSurge", "url": "https://www.edsurge.com/articles_rss", "category": "sector:edtech"},),
    "logistics": ({"name": "FreightWaves", "url": "https://www.freightwaves.com/news/feed", "category": "sector:logistics"},),
    "climate": ({"name": "Canary Media", "url": "https://www.canarymedia.com/rss.rss", "category": "sector:climate"},),
    "ecommerce": ({"name": "Modern Retail", "url": "https://www.modernretail.co/feed/", "category": "sector:ecommerce"},),
    "saas": (),
}

# ------------------------------------------------------------- Hacker News hiring threads

HN_HIRING_MAX_AGE_DAYS = 45
_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r'href="(https?://[^"]+)"')
_NEG = re.compile(
    r"\b(?:no|not|never|without|don'?t|do not|doesn'?t|does not|won'?t|will not|isn'?t|aren'?t|cannot|can'?t)\b"
    r"(?:\s+\w+){0,4}?\s+(?:freelanc\w*|contractors?|consultants?|outsourc\w*)",
    re.I,
)
_CONTRACT = re.compile(
    r"(\bfreelanc\w*|\bcontractors?\b|\bcontract (?:role|basis|position|work|engineer|developer|to hire)\b|"
    r"\|\s*contract\b|\bcontract\s*\||\bfixed[- ]term contract\b)",
    re.I,
)
# The "who wants to be hired" template: a person offering their own work, not a company asking for a contractor.
_SEEKER = re.compile(r"^\W*location\s*:|willing to relocate|\bseeking work\b|\bavailable for (hire|work)\b|who wants to be hired", re.I)
_LABELS = re.compile(r"^(seeking|hiring|looking for|remote|onsite|full[- ]?time|contract|freelance)\b", re.I)
_PAREN = re.compile(r"\s*\(([^)]*)\)")


def _plain(raw_html: str) -> str:
    text = re.sub(r"</p>|<p>|<br\s*/?>", "\n", raw_html or "", flags=re.I)
    return html_lib.unescape(_TAG.sub("", text)).strip()


def _hn_company(first_line: str) -> str | None:
    """HN convention: 'Company | Role | Location | ...'."""
    head = first_line.split("|")[0].strip(" -–:*_")
    head = _PAREN.sub("", head).strip()  # "(YC W23)", "(https://x.co)"
    if not head or len(head) > 60 or ":" in head or _LABELS.match(head) or not _plausible_company_name(head) or not head[0].isalnum():
        return None
    return head


def parse_hn_hiring_comments(children: list[dict], *, thread_id: str, now: datetime, limit: int) -> list[RawItem]:
    """Top-level comments that state a freelance/contract need. Pure function: easy to test."""
    cutoff = now - timedelta(days=HN_HIRING_MAX_AGE_DAYS)
    items: list[RawItem] = []
    for child in children or []:
        raw = child.get("text")
        if not raw or child.get("author") is None:
            continue
        created = parse_datetime(child.get("created_at"))
        if created is None or created < cutoff:
            continue
        text = _plain(raw)
        if not text or not _CONTRACT.search(text) or _NEG.search(text) or _SEEKER.search(text[:600]):
            continue
        first = text.splitlines()[0].strip()
        company = _hn_company(first)
        if not company:
            continue
        unescaped = html_lib.unescape(raw)
        website = next((u for u in _HREF.findall(unescaped) if not is_publisher(registrable_domain(u))), None)
        permalink = f"https://news.ycombinator.com/item?id={child.get('id')}"
        items.append(
            RawItem(
                source_name="Hacker News: Who is hiring",
                source_url=permalink,
                title=first[:200],
                excerpt=redact_pii(text[:1800]),
                category="hiring",
                access_method="hn_algolia_api",
                published_at=created,
                company_name=company,
                website=website,
                signal_type="hiring",
                extra={"thread_id": thread_id},
            ).prepare()
        )
        if len(items) >= limit:
            break
    return items


async def fetch_hn_hiring(client: httpx.AsyncClient, limit: int, sector: str | None = None) -> tuple[list[RawItem], str | None]:
    """Freelance/contract requests in the latest 'Who is hiring?' thread, optionally filtered to a sector."""
    base = "https://hn.algolia.com/api/v1"
    try:
        found = await get_capped(client, f"{base}/search_by_date?tags=story,author_whoishiring&hitsPerPage=10", timeout=25)
        found.raise_for_status()
        thread = next((h for h in found.json().get("hits", []) if str(h.get("title", "")).startswith("Ask HN: Who is hiring?")), None)
        if thread is None:
            return [], "no_hiring_thread"
        created = parse_datetime(thread.get("created_at"))
        if created is None or created < datetime.now(timezone.utc) - timedelta(days=HN_HIRING_MAX_AGE_DAYS + 30):
            return [], "hiring_thread_too_old"
        response = await get_capped(client, f"{base}/items/{thread['objectID']}", timeout=60, max_bytes=12_000_000)
        response.raise_for_status()
        children = response.json().get("children") or []
    except Exception as exc:  # noqa: BLE001
        return [], exc.__class__.__name__
    items = parse_hn_hiring_comments(children, thread_id=str(thread["objectID"]), now=datetime.now(timezone.utc), limit=limit * 4 if sector else limit)
    if sector:
        items = [i for i in items if matches_focus(sector, i.title, i.excerpt)][:limit]
    return items, None


# ------------------------------------------------------------------- job boards (explicit contract roles)

JOB_MAX_AGE_DAYS = 45
JOB_CACHE_SECONDS = 6 * 3600  # Remotive asks clients not to poll often
_job_cache: dict[str, tuple[float, list]] = {}
_ENGINEERING = re.compile(
    r"\b(developer|devops|sre|architect)\b|"
    r"\b(software|backend|front[- ]?end|full[- ]?stack|data|machine learning|ml|ai|cloud|security|platform|python|golang|rust|mobile)\s+(engineer|developer|architect|scientist)\b",
    re.I,
)
_NOT_ENGINEERING = re.compile(r"annotat|label+ing|\btrainer\b|customer (service|support)|support (rep|agent)|data entry|transcri", re.I)
_CONTRACT_TYPES = {"contract": "contract role", "freelance": "freelance engagement"}


def _job_item(*, source: str, company: str, title: str, url: str, published, engagement: str, body: str) -> RawItem | None:
    company = _PAREN.sub("", " ".join((company or "").split())).strip()
    if not company or len(company) > 60 or ":" in company or not _plausible_company_name(company):
        return None
    text = _plain(body)
    return RawItem(
        source_name=source,
        source_url=url,
        title=f"{company} | {' '.join((title or '').split())[:120]} | {engagement}",
        excerpt=redact_pii(f"Engagement type: {engagement}. {text}"[:1800]),
        category="hiring",
        access_method="job_board",
        published_at=published,
        company_name=company,
        signal_type="hiring",
    ).prepare()


def parse_remotive(payload: dict, *, now: datetime, limit: int) -> list[RawItem]:
    cutoff = now - timedelta(days=JOB_MAX_AGE_DAYS)
    out: list[RawItem] = []
    for job in (payload or {}).get("jobs") or []:
        engagement = _CONTRACT_TYPES.get(str(job.get("job_type") or "").lower())
        published = parse_datetime(job.get("publication_date"))
        url = str(job.get("url") or "")
        if not engagement or not url.startswith("https://") or published is None or published < cutoff:
            continue
        heading = f"{job.get('title', '')} {job.get('category', '')}"
        if not _ENGINEERING.search(heading) or _NOT_ENGINEERING.search(heading):
            continue
        item = _job_item(source="Remotive", company=job.get("company_name"), title=job.get("title"), url=url, published=published,
                         engagement=engagement, body=job.get("description") or "")
        if item and not _NEG.search(item.excerpt):
            out.append(item)
        if len(out) >= limit:
            break
    return out


def parse_wwr(entries: list, *, now: datetime, limit: int) -> list[RawItem]:
    """We Work Remotely titles read 'Company: Role'. Keep engineering roles whose text states a contract or freelance engagement."""
    cutoff = now - timedelta(days=JOB_MAX_AGE_DAYS)
    out: list[RawItem] = []
    for entry in entries or []:
        title = getattr(entry, "title", "") or ""
        company, _, role = title.partition(":")
        body = getattr(entry, "summary", "") or ""
        plain = _plain(body)
        published = parse_datetime(getattr(entry, "published", None))
        url = getattr(entry, "link", "") or ""
        if not role or not url.startswith("https://") or (published and published < cutoff):
            continue
        if not _CONTRACT.search(plain) or _NEG.search(plain) or not _ENGINEERING.search(role) or _NOT_ENGINEERING.search(role):
            continue
        item = _job_item(source="We Work Remotely", company=company, title=role, url=url, published=published,
                         engagement="contract role", body=body)
        if item:
            out.append(item)
        if len(out) >= limit:
            break
    return out


async def fetch_job_boards(client: httpx.AsyncClient, limit: int, sector: str | None = None, *, resolve=None) -> tuple[list[RawItem], list[dict]]:
    """Explicit contract and freelance engineering roles from public job boards. Returns items and per-source health."""
    import time

    import feedparser

    now = datetime.now(timezone.utc)
    items: list[RawItem] = []
    health: list[dict] = []
    sources = (
        ("Remotive", "remotive.com", "https://remotive.com/api/remote-jobs?category=software-dev&limit=100", "json"),
        ("We Work Remotely", "weworkremotely.com", "https://weworkremotely.com/categories/remote-programming-jobs.rss", "rss"),
    )
    for name, domain, url, kind in sources:
        cached = _job_cache.get(url)
        try:
            if cached and time.monotonic() - cached[0] < JOB_CACHE_SECONDS:
                found = cached[1]
            else:
                response = await get_capped(client, url, timeout=25, resolve=resolve)
                response.raise_for_status()
                if kind == "json":
                    found = parse_remotive(response.json(), now=now, limit=limit)
                else:
                    found = parse_wwr(feedparser.parse(response.text).entries, now=now, limit=limit)
                _job_cache[url] = (time.monotonic(), found)
            kept = [i for i in found if matches_focus(sector, i.title, i.excerpt)] if sector else list(found)
            items.extend(kept[:limit])
            health.append({"name": name, "parent_domain": domain, "category": "hiring", "access_method": "job_board", "status": "ok", "records": len(kept), "error": None})
        except Exception as exc:  # noqa: BLE001 - a board being down is recorded, not fatal
            health.append({"name": name, "parent_domain": domain, "category": "hiring", "access_method": "job_board", "status": "failed", "records": 0, "error": exc.__class__.__name__})
    return items, health
