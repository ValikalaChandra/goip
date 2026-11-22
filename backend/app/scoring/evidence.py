"""Source text helpers. Quotations have to occur in the stored or decoded text."""

from __future__ import annotations

import html
from urllib.parse import urlparse

CLASSIFICATIONS = ("observed_fact", "derived_fact", "inference", "hypothesis", "unknown")


def decode_text(raw: str) -> str:
    return html.unescape(raw or "")


def canonical_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    base = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
    return f"{base}?{query}" if query else base


def registrable_domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def quote_supported(quote: str, raw: str) -> bool:
    """True when the quotation is copied from the raw source or its decoded form."""
    if not quote or not raw:
        return False
    decoded_quote = decode_text(quote).strip()
    decoded_raw = decode_text(raw)
    return quote in raw or decoded_quote in decoded_raw


def finding(
    *,
    claim: str,
    classification: str,
    source_id: str = "",
    source_url: str = "",
    quotation: str = "",
    raw_text: str = "",
    published_at: str | None = None,
    retrieved_at: str | None = None,
    confidence: str = "low",
    fetch_status: str = "not_fetched",
) -> dict:
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"Unknown classification: {classification}")
    if classification == "observed_fact" and not quote_supported(quotation, raw_text):
        classification = "unknown"
        claim = "The proposed quotation is not in the stored source, so it is not recorded as an observed fact."
        quotation = ""
        confidence = "low"
    verification = "unverified"
    if classification == "observed_fact":
        verification = "quote_matches_stored_text"
    elif classification == "unknown" and raw_text and quotation == "":
        verification = "quote_not_in_source"
    if fetch_status == "not_refetched":
        verification = f"{verification};not_refetched"
    elif fetch_status == "inaccessible":
        verification = f"{verification};page_inaccessible"
    elif fetch_status == "fetched" and classification == "observed_fact":
        verification = "quote_matches_stored_text;page_fetched"
    return {
        "claim": claim,
        "classification": classification,
        "source_id": source_id,
        "source_url": source_url,
        "quotation": decode_text(quotation).strip() if classification == "observed_fact" else quotation,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "confidence": confidence,
        "verification_status": verification,
        "fetch_status": fetch_status,
    }
