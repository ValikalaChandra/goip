"""Discovery connectors that are actually wired, and categories that are not."""

from __future__ import annotations

CONNECTORS = (
    {
        "name": "Hacker News",
        "category": "product_launches",
        "status": "connected",
        "access": "Algolia public API and the front-page RSS feed",
    },
    {
        "name": "TechCrunch RSS",
        "category": "funding_and_product",
        "status": "connected",
        "access": "Public RSS",
    },
    {
        "name": "GitHub search",
        "category": "developer_activity",
        "status": "connected",
        "access": "Public API, name match only",
    },
    {
        "name": "Crawl4AI search",
        "category": "web_search",
        "status": "connected",
        "access": "Configured Crawl4AI endpoint, one query cap",
    },
    {
        "name": "Product Hunt",
        "category": "product_launches",
        "status": "not_connected",
        "access": "No connector is implemented",
    },
    {
        "name": "Careers pages",
        "category": "hiring",
        "status": "not_connected",
        "access": "No connector is implemented",
    },
    {
        "name": "Procurement and RFP portals",
        "category": "commercial_intent",
        "status": "not_connected",
        "access": "No connector is implemented",
    },
)


def connector_report() -> dict:
    connected = [row["name"] for row in CONNECTORS if row["status"] == "connected"]
    pending = [row["name"] for row in CONNECTORS if row["status"] != "connected"]
    return {"connected": connected, "not_connected": pending, "connectors": list(CONNECTORS)}
