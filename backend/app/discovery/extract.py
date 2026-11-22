from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

PUBLISHER_DOMAINS = {
    "techcrunch.com",
    "venturebeat.com",
    "reuters.com",
    "bloomberg.com",
    "forbes.com",
    "theverge.com",
    "businesswire.com",
    "prnewswire.com",
    "siliconangle.com",
    "tech.eu",
    "news.ycombinator.com",
    "ycombinator.com",
    "github.com",
    "medium.com",
    "substack.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "reddit.com",
    "producthunt.com",
    "crunchbase.com",
    "wellfound.com",
    "indeed.com",
    "wikipedia.org",
}

SIGNAL_PATTERNS = [
    ("funding", re.compile(r"\b(raises?|raised|funding|series [a-e]|seed round|venture)\b", re.I)),
    ("hiring", re.compile(r"\b(hiring|is hiring|job opening|recruit|engineer role)\b", re.I)),
    ("product", re.compile(r"\b(launch(?:es|ed)?|announces|introduces|unveils|show hn)\b", re.I)),
    ("partnership", re.compile(r"\b(partner(?:s|ship|ed)?|collaborat)\b", re.I)),
    ("expansion", re.compile(r"\b(expands?|expansion|opens office|enters market)\b", re.I)),
    ("acquisition", re.compile(r"\b(acqui(?:res|red|sition)|merger)\b", re.I)),
    ("technology", re.compile(r"\b(open[- ]source|github|api|llm|rag|machine learning|artificial intelligence)\b", re.I)),
]

COMPANY_PATTERNS = [
    re.compile(r"^(?:show hn:\s*)?(?P<name>[A-Z][\w.&'’+-]{1,40}(?:\s+[A-Z][\w.&'’+-]{1,40}){0,3})\s+(?:raises|raised|secures|lands|gets)\b", re.I),
    re.compile(r"^(?:show hn:\s*)(?P<name>[^:\-–|]{2,60}?)(?:\s+[\-–|:]\s+|\s*$)", re.I),
    re.compile(r"^(?P<name>[A-Z][\w.&'’+-]{1,40}(?:\s+[A-Z][\w.&'’+-]{1,40}){0,3})\s+(?:launches|announces|unveils|introduces|expands|partners)\b"),
]


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").lower()
    text = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|gmbh|plc|co)\b\.?", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def registrable_domain(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    return host


def is_publisher(domain: str | None) -> bool:
    if not domain:
        return False
    return any(domain == item or domain.endswith("." + item) for item in PUBLISHER_DOMAINS)


def classify_signal(text: str) -> str:
    for name, pattern in SIGNAL_PATTERNS:
        if pattern.search(text or ""):
            return name
    return "other"


_NAME_STOPWORDS = {
    "a",
    "after",
    "almost",
    "an",
    "and",
    "falling",
    "for",
    "have",
    "i",
    "my",
    "of",
    "reportedly",
    "the",
    "to",
    "with",
}


def _plausible_company_name(name: str) -> bool:
    words = [word.strip(".,'’") for word in name.split() if word.strip(".,'’")]
    if not words or len(words) > 4:
        return False
    lowered = [word.lower() for word in words]
    if any(word in _NAME_STOPWORDS for word in lowered):
        return False
    return True


def extract_company_name(title: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", (title or "")).strip()
    for pattern in COMPANY_PATTERNS:
        match = pattern.search(cleaned)
        if not match:
            continue
        name = match.group("name").strip(" -–|:.")
        if len(name) < 2 or not _plausible_company_name(name):
            continue
        if is_publisher(registrable_domain("https://" + name) if "." in name else None):
            continue
        return name[:180]
    return None


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return parse_datetime(int(text))
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class RawItem:
    source_name: str
    source_url: str
    title: str
    excerpt: str = ""
    parent_domain: str = ""
    category: str = ""
    access_method: str = ""
    published_at: datetime | None = None
    company_name: str | None = None
    website: str | None = None
    signal_type: str = "other"
    extra: dict = field(default_factory=dict)

    def prepare(self) -> "RawItem":
        self.parent_domain = self.parent_domain or (registrable_domain(self.source_url) or "")
        text = f"{self.title}\n{self.excerpt}"
        self.signal_type = self.signal_type if self.signal_type != "other" else classify_signal(text)
        if not self.company_name:
            self.company_name = extract_company_name(self.title)
        site_domain = registrable_domain(self.website)
        if site_domain and is_publisher(site_domain):
            self.website = None
        source_domain = registrable_domain(self.source_url)
        if self.website is None and source_domain and not is_publisher(source_domain):
            self.website = self.source_url
        return self
