"""
Plausible consumer brand names vs generic words scraped from event page titles.
"""
from __future__ import annotations

import re

from prospecting_qa import normalize_company_key

# Single words / phrases that are NOT sponsor company names
GENERIC_BRAND_BLOCKLIST = frozenset(
    {
        "partner",
        "partners",
        "official",
        "official partner",
        "official partners",
        "presenting partner",
        "media partner",
        "title partner",
        "global platform",
        "platform",
        "swimwear",
        "resort",
        "resort wear",
        "fashion",
        "wellness",
        "music",
        "trade",
        "trade events",
        "events",
        "event",
        "show",
        "shows",
        "runway",
        "miami swim week",
        "miami swim week official",
        "swim week",
        "global",
        "official global platform",
        "paraiso",
        "paraíso",
        "winter music conference",
        "iii points",
        "tech week",
        "conference",
        "festival",
        "official sponsors",
        "our partners",
        "sponsors",
        "sponsorship",
        "learn more",
        "read more",
        "click here",
        "home",
        "about",
        "contact",
        "register",
        "tickets",
        "schedule",
        "lineup",
        "hotels",
        "hotel",
        "official hotel",
        "venue",
        "venues",
        "location",
        "locations",
        "gallery",
        "press",
        "news",
        "blog",
        "faq",
        "menu",
        "search",
        "subscribe",
        "sign up",
        "sign up now",
    }
)

_GENERIC_TOKENS = frozenset(
    {
        "partner",
        "partners",
        "official",
        "global",
        "platform",
        "swimwear",
        "resort",
        "fashion",
        "wellness",
        "music",
        "trade",
        "events",
        "event",
        "show",
        "shows",
        "runway",
        "miami",
        "swim",
        "week",
        "beach",
        "wear",
        "and",
        "the",
        "for",
        "with",
        "your",
        "brand",
        "at",
        "elevate",
        "presenting",
        "media",
        "title",
        "platinum",
        "gold",
        "silver",
        "bronze",
        "supported",
        "powered",
        "presents",
        "paraiso",
        "paraíso",
        "winter",
        "conference",
        "festival",
        "tech",
        "points",
        "iii",
        "our",
        "sponsors",
        "sponsorship",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "january",
        "february",
        "march",
        "april",
    }
)

_PARTNER_URL_HINTS = ("sponsor", "partner", "supporter", "presenting")

_DATE_LINE_RE = re.compile(
    r"^("
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2}(?:\s*[-–—]\s*\d{1,2})?"
    r"|\d{1,2}\s*[-–—]\s*\d{1,2}"
    r"|\d{4}"
    r")$",
    re.I,
)

_CTA_RE = re.compile(
    r"\b(elevate your|your brand|become a (?:partner|sponsor)|sponsor us|book now|"
    r"get tickets|register now|apply now|contact us|learn more)\b",
    re.I,
)

_BENEFIT_PHRASE_RE = re.compile(
    r"\b("
    r"visibility across|thought leadership|community activation|founder education|"
    r"how to use ai|how to use|executive thought|brand visibility|networking opportunities|"
    r"access to attendees|booth space|logo placement|naming rights|media exposure|"
    r"partner benefits|sponsorship benefits|why sponsor|become a partner"
    r")\b",
    re.I,
)

_ABOUT_PREFIX_RE = re.compile(r"^about\s+\w", re.I)

_MARKDOWN_RE = re.compile(r"[*_#`\[\]]")


def is_benefit_phrase(text: str) -> bool:
    """Sponsor-package bullets and article topics — not brand names."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return False
    if _BENEFIT_PHRASE_RE.search(raw):
        return True
    if _ABOUT_PREFIX_RE.match(raw):
        return True
    if raw.endswith(":") and len(raw.split()) <= 4:
        return True
    return False


def is_partner_page_url(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _PARTNER_URL_HINTS)


def _is_nav_token_list(raw: str) -> bool:
    """e.g. 'Runway | Trade | Events' or 'Runway • Trade • Events'."""
    parts = re.split(r"[|•·]", raw)
    if len(parts) < 2:
        return False
    cleaned = [p.strip() for p in parts if p.strip()]
    if len(cleaned) < 2:
        return False
    generic_hits = 0
    for part in cleaned:
        key = normalize_company_key(part)
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9&']+", part)]
        if not tokens or key in GENERIC_BRAND_BLOCKLIST or all(t in _GENERIC_TOKENS for t in tokens):
            generic_hits += 1
    return generic_hits == len(cleaned)


def is_plausible_brand_name(name: str, *, event_name: str | None = None) -> bool:
    """True if this looks like a company/brand, not page title noise."""
    raw = re.sub(r"\s+", " ", (name or "").strip())
    if not raw or len(raw) < 2 or len(raw) > 48:
        return False

    if _MARKDOWN_RE.search(raw):
        return False

    if _DATE_LINE_RE.match(raw.strip()):
        return False

    if _CTA_RE.search(raw):
        return False

    if is_benefit_phrase(raw):
        return False

    if _is_nav_token_list(raw):
        return False

    if event_name and event_name.strip():
        ev = event_name.strip().lower()
        low = raw.lower()
        if ev in low and len(raw.split()) >= 4:
            return False

    key = normalize_company_key(raw)
    if not key or key in GENERIC_BRAND_BLOCKLIST:
        return False

    if re.search(r"\b(partners?|official|sponsors?)\b", raw, re.I) and len(raw.split()) > 2:
        return False

    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9&']+", raw)]
    if not tokens:
        return False

    if all(t in _GENERIC_TOKENS for t in tokens):
        return False

    if len(tokens) == 1:
        t = tokens[0]
        if t in _GENERIC_TOKENS or len(t) < 4:
            return False
        if t.isupper() and len(t) <= 6:
            return False

    if "platform" in key or "official global" in key:
        return False

    # Need at least one token that isn't generic marketing vocabulary
    if not any(t not in _GENERIC_TOKENS and len(t) >= 3 for t in tokens):
        return False

    return True


def clean_brand_name(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip())
    s = re.sub(r"[*_`#]+", "", s)
    s = re.sub(r"^(official|title|presenting|platinum|gold|silver|media)\s+", "", s, flags=re.I)
    s = re.sub(r"^(partners?|sponsors?)[:\s.\-]+", "", s, flags=re.I)
    s = re.sub(r"\s*[-–—]\s*(official|presenting|title|media)\s+partner\s*$", "", s, flags=re.I)
    return s.strip(" .,-|•·")
