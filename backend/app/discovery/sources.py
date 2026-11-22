from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import httpx

from app.discovery.extract import RawItem, parse_datetime, registrable_domain
from app.security.url_safety import UnsafeURL, check_url

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
            check_url(url)
            response = await client.get(url, timeout=25)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - source errors are recorded, not fatal
            errors.append(f"{query}: {exc.__class__.__name__}")
            continue
        for hit in payload.get("hits") or []:
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            try:
                check_url(story_url)
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


async def fetch_rss(client: httpx.AsyncClient, per_feed: int) -> tuple[list[RawItem], list[dict]]:
    import feedparser

    items: list[RawItem] = []
    health: list[dict] = []
    for feed in RSS_FEEDS:
        try:
            check_url(feed["url"])
            response = await client.get(feed["url"], timeout=25, follow_redirects=False)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURL("redirect without location")
                check_url(location)
                response = await client.get(location, timeout=25, follow_redirects=False)
            response.raise_for_status()
            parsed = feedparser.parse(response.text)
            count = 0
            for entry in (parsed.entries or [])[:per_feed]:
                link = getattr(entry, "link", "") or ""
                try:
                    check_url(link)
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
        check_url(url)
        response = await client.get(
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
        response = await client.get(
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
            check_url(link)
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
    check_url(url)
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
