"""Sources as individually callable steps.

A discovery agent chooses which of these to call and in what order. The fixed pipeline calls all of them. Each step
fetches, records its own health row, and returns items; none of them writes companies or signals.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, load_runtime
from app.db import PipelineRun, SourceHealth, utcnow
from app.discovery.extract import RawItem
from app.discovery.sources import (
    FOCUS_FEEDS,
    crawl4ai_scrape,
    crawl4ai_search,
    fetch_hacker_news,
    fetch_hn_hiring,
    fetch_job_boards,
    fetch_rss,
    matches_focus,
)
from app.discovery.focus import feed_sector_for

import uuid

SOURCES: dict[str, str] = {
    "hn_hiring": "Companies asking for contractors or freelancers in the latest Hacker News 'Who is hiring?' thread. Explicit demand.",
    "job_boards": "Engineering roles on Remotive and We Work Remotely that state a contract or freelance engagement. Explicit demand.",
    "hn_search": "Recent Hacker News stories about funding, launches and products. Business signals, not demand.",
    "news_feeds": "Hacker News front page and TechCrunch feeds. Business signals, not demand.",
    "sector_feeds": "Trade-press feeds for the focus sector (needs a focus). Business signals, not demand.",
    "web_search": "One Crawl4AI web search and page read. Broad, slow, rarely yields companies.",
}
DEMAND_SOURCES = ("hn_hiring", "job_boards")  # sources whose items can state a freelance need
ALL_SOURCES = tuple(SOURCES)


def record_health(session: Session, run_id: str, **kwargs) -> None:
    session.add(SourceHealth(id=str(uuid.uuid4()), run_id=run_id, fetched_at=utcnow(), **kwargs))


class Gatherer:
    def __init__(self, session: Session, http: httpx.AsyncClient, settings: Settings, run: PipelineRun, sector: str | None = None):
        self.session, self.http, self.settings, self.run = session, http, settings, run
        runtime = load_runtime()
        self.caps = runtime["fetch_caps"]
        # A plan can focus this one run without changing the saved focus. The focus is the operator's own words.
        saved = runtime.get("focus") or {}
        self.sector = sector or saved.get("term") or saved.get("sector") or None
        self.feed_sector = feed_sector_for(self.sector)  # a related trade feed to read as an extra source

    def available(self) -> dict[str, str]:
        out = dict(SOURCES)
        if not self.feed_sector:
            out.pop("sector_feeds")
        return out

    def _focus(self, items: list[RawItem]) -> list[RawItem]:
        return [i for i in items if matches_focus(self.sector, i.title, i.excerpt)] if self.sector else items

    async def run_source(self, name: str) -> list[RawItem]:
        if name not in SOURCES:
            raise KeyError(name)
        return await getattr(self, f"_{name}")()

    async def _hn_search(self) -> list[RawItem]:
        items, error = await fetch_hacker_news(self.http, int(self.caps["hn_hits"]))
        record_health(self.session, self.run.id, name="Hacker News", parent_domain="news.ycombinator.com", category="community",
                      access_method="hn_algolia_api", status="degraded" if error else "ok", records=len(items), error=error)
        return self._focus(items)

    async def _news_feeds(self) -> list[RawItem]:
        items, health = await fetch_rss(self.http, int(self.caps["rss_per_feed"]))
        for row in health:
            record_health(self.session, self.run.id, **row)
        return self._focus(items)

    async def _sector_feeds(self) -> list[RawItem]:
        feeds = FOCUS_FEEDS.get(self.feed_sector, ()) if self.feed_sector else ()
        if not feeds:
            return []
        items, health = await fetch_rss(self.http, int(self.caps.get("focus_feed_items", 15)), feeds=feeds)
        for row in health:
            record_health(self.session, self.run.id, **row)
        return self._focus(items)  # the trade feed is an extra source; only items about the operator's term are kept

    async def _hn_hiring(self) -> list[RawItem]:
        items, error = await fetch_hn_hiring(self.http, int(self.caps.get("hn_hiring_comments", 40)), self.sector)
        record_health(self.session, self.run.id, name="Hacker News: Who is hiring", parent_domain="news.ycombinator.com", category="hiring",
                      access_method="hn_algolia_api", status="degraded" if error else "ok", records=len(items), error=error)
        return items

    async def _job_boards(self) -> list[RawItem]:
        items, health = await fetch_job_boards(self.http, int(self.caps.get("job_board_items", 30)), self.sector)
        for row in health:
            record_health(self.session, self.run.id, **row)
        return items

    async def _web_search(self) -> list[RawItem]:
        items: list[RawItem] = []
        results, error = await crawl4ai_search(self.http, self.settings.crawl4ai_base_url, self.settings.crawl4ai_api_key,
                                               "startup raises funding AI product launch")
        pages = 0
        for result in results[: int(self.caps["crawl_pages"])]:
            markdown, scrape_error = await crawl4ai_scrape(self.http, self.settings.crawl4ai_base_url, self.settings.crawl4ai_api_key, result["url"])
            if scrape_error:
                error = scrape_error
                continue
            pages += 1
            items.append(RawItem(source_name="Crawl4AI search", source_url=result["url"], title=result["title"],
                                 excerpt=(markdown or result["snippet"])[:2000], category="news", access_method="crawl4ai").prepare())
        record_health(self.session, self.run.id, name="Crawl4AI", parent_domain="api.crawl4ai.com", category="extraction",
                      access_method="crawl4ai_cloud", status="unconfigured" if error == "missing_api_key" else ("ok" if pages else "failed"),
                      records=len(items), error=None if pages else error)
        return items

    async def gather(self, names: list[str] | tuple[str, ...]) -> tuple[list[RawItem], list[str]]:
        pool: list[RawItem] = []
        used: list[str] = []
        for name in names:
            if name in self.available() and name not in used:
                pool.extend(await self.run_source(name))
                used.append(name)
        return pool, used
