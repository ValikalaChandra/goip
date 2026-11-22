"""What "focus on X" means.

Focus is the operator's own words, taken literally. "banking" keeps items about banking; it is not rewritten to a wider
category. Matching uses the topic's words and their simple variants (bank, banks, banking) but not look-alikes
(bankruptcy). A known sector name such as "fintech" keeps its broader keyword set, because articles about payments rarely
say the word "fintech". A related trade feed may be read as an extra *source*, but only items that match the term are kept.
"""

from __future__ import annotations

import re

SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fintech": ("fintech", "payment", "payments", "bank", "banking", "neobank", "lending", "loan", "credit", "insurance", "insurtech", "trading", "wallet", "remittance", "ledger", "kyc", "aml", "compliance", "card issuing", "wealth", "brokerage"),
    "ai": ("ai ", " ai", "llm", "machine learning", "ml ", "agent", "rag", "model", "genai", "artificial intelligence"),
    "cybersecurity": ("security", "cyber", "vulnerab", "breach", "ransomware", "soc ", "threat", "zero trust", "encryption", "identity"),
    "healthtech": ("health", "clinical", "patient", "medical", "biotech", "telehealth", "hospital", "pharma", "ehr"),
    "edtech": ("education", "edtech", "learning", "student", "school", "tutor", "course", "university"),
    "logistics": ("logistics", "freight", "shipping", "supply chain", "warehouse", "fleet", "delivery", "trucking"),
    "climate": ("climate", "carbon", "solar", "battery", "energy", "emissions", "renewable", "ev ", "grid"),
    "ecommerce": ("ecommerce", "e-commerce", "retail", "shopify", "marketplace", "checkout", "storefront", "merchant"),
    "saas": ("saas", "b2b", "platform", "dashboard", "workflow", "api", "subscription"),
}

# Words that name a trade-press feed to read as an EXTRA source. They never widen what is kept.
SECTOR_ALIASES = {
    "fintech": "fintech", "fin-tech": "fintech", "fin tech": "fintech", "financial": "fintech", "finance": "fintech", "banking": "fintech", "banks": "fintech", "bank": "fintech", "payments": "fintech",
    "healthtech": "healthtech", "health tech": "healthtech", "health": "healthtech", "healthcare": "healthtech",
    "edtech": "edtech", "ed tech": "edtech", "education": "edtech",
    "cybersecurity": "cybersecurity", "cyber security": "cybersecurity", "security": "cybersecurity", "cyber": "cybersecurity",
    "logistics": "logistics", "supply chain": "logistics", "freight": "logistics",
    "climate": "climate", "cleantech": "climate", "energy": "climate",
    "ecommerce": "ecommerce", "e-commerce": "ecommerce", "retail": "ecommerce",
    "saas": "saas", "ai": "ai", "ml": "ai", "machine learning": "ai", "llm": "ai",
}

FOCUS_TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &.,+'#-]{0,59}$")

# Words that are true of every posting GOIP reads, so requiring them would only hide results.
_GENERIC = {"a", "an", "the", "and", "or", "in", "on", "for", "of", "to", "with", "about", "jobs", "job", "work", "roles", "role", "gigs", "gig",
            "leads", "lead", "companies", "company", "freelance", "freelancer", "contract", "contractor", "contracts", "opportunities", "opportunity",
            "startups", "startup", "engineering", "engineer", "developer", "developers", "sector", "industry", "space"}
_NOT_A_TOPIC = {"clear", "reset", "nothing", "none", "all", "everything", "this", "that", "it", "again", "off", "more", "less"}

_VERB = re.compile(
    r"\b(?:focus(?:ing)?|concentrate|special(?:is|iz)e|narrow(?:ed)?(?:\s+down)?|restrict(?:ed)?|limit)\b\s*(?:only\s+)?"
    r"(?:(?:on|to|in|for|around|towards?)\s+)?(?:only\s+)?(?:the\s+)?(?P<term>[^\n.!?]{2,80})",
    re.I,
)
_ONLY = re.compile(r"^\W*(?:@[\w.-]+\s+)*only\s+(?:(?:on|in|for|about)\s+)?(?P<term>[^\n.!?]{2,60})", re.I)
_CLEAR = re.compile(r"\b(clear|remove|reset|drop|no|all)\b.{0,12}\b(focus|sectors?|filter|topics?)\b|\bfocus\b.{0,12}\b(off|none|all)\b", re.I)
_TRAILING = re.compile(r"(?:\s*[,;]\s*|\s+(?:and|then|also)\s+(?:then\s+)?(?:run|start|search|find|go|begin)\b.*|\s+(?:please|now|first|for me|right now|thanks|thank you))$", re.I)


def clean_term(text: str | None) -> str | None:
    """A focus term in the operator's words, or None if it is empty, a command word, or not safe to store."""
    t = " ".join((text or "").replace("“", "").replace("”", "").replace('"', "").split())
    for _ in range(4):
        shorter = _TRAILING.sub("", t).strip(" .,:;!?-'")
        if shorter == t:
            break
        t = shorter
    t = t.strip(" .,:;!?-'")
    if len(t) > 3 and t.isupper():
        t = t.lower()
    if not t or t.lower() in _NOT_A_TOPIC or not FOCUS_TERM_RE.match(t):
        return None
    if not _groups(t):  # only filler or words true of every posting ("on", "jobs"): nothing to focus on
        return None
    return t


def is_clear(body: str) -> bool:
    return bool(_CLEAR.search(body or ""))


def parse_focus_term(body: str, explicit_only: bool = False) -> tuple[str | None, bool]:
    """(term, clear). `explicit_only` accepts only an unmistakable instruction ("focus on X", "only X")."""
    text = body or ""
    if is_clear(text):
        return None, True
    for pattern in (_VERB, _ONLY):
        found = pattern.search(text)
        if found:
            term = clean_term(found.group("term"))
            if term:
                return term, False
    if explicit_only:
        return None, False
    lowered = text.lower()
    for alias in sorted(SECTOR_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered):
            return alias, False  # the operator's own word, not the category it belongs to
    return None, False


def feed_sector_for(term: str | None) -> str | None:
    """A related trade-feed set to read as an extra source, if the term names (or belongs to) one."""
    if not term:
        return None
    lowered = term.lower().strip()
    if lowered in SECTOR_ALIASES:
        return SECTOR_ALIASES[lowered]
    for word in re.findall(r"[a-z][a-z-]+", lowered):
        if word in SECTOR_ALIASES:
            return SECTOR_ALIASES[word]
    return None


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _groups(term: str) -> list[list[str]]:
    """'banking and fintech' means either; 'ai agents' means both words. Generic words are ignored."""
    groups = []
    for part in re.split(r"\s*(?:,|/|\band\b|\bor\b)\s*", term.lower()):
        words = [_stem(w) for w in re.findall(r"[a-z0-9+#.]{2,}", part) if w not in _GENERIC]
        if words:
            groups.append(words)
    return groups


def _has(word: str, hay: str) -> bool:
    # the word, or it with a simple suffix, as a whole word: bank -> banks/banking, but not bankruptcy
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?:s|es|ing|ed|er|ers|ion|ions)?(?![a-z0-9])", hay) is not None


def matches_focus(focus: str | None, *texts: str) -> bool:
    """True when no focus is set, or the text is about the focus."""
    if not focus:
        return True
    hay = " " + " ".join(texts).lower() + " "
    key = focus.lower().strip()
    if key in SECTOR_KEYWORDS:  # a named sector keeps its broader vocabulary
        return any(word in hay for word in SECTOR_KEYWORDS[key])
    groups = _groups(focus)
    if not groups:
        return True
    return any(all(_has(w, hay) for w in words) for words in groups)
