"""
Guess official brand website domains for Apollo org lookup (any shelf brand).
"""
from __future__ import annotations

import re
import unicodedata

from prospecting_qa import normalize_company_key

_DOMAIN_STOP = frozenset({"usa", "us", "the", "inc", "llc", "co", "company", "group"})


def _fold_accents(text: str) -> str:
    """BACARDÍ → bacardi (not bacard when í is stripped)."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _domain_key(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    return d.split("/")[0].removeprefix("www.")


def guess_brand_domains(company_name: str) -> list[str]:
    """
    Return likely brand-owned .com domains to try in Apollo domain search.
    Examples: Maker's Mark → makersmark.com; BACARDÍ → bacardi.com; MINI USA → miniusa.com
    """
    key = normalize_company_key(_fold_accents(company_name))
    if not key:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def add(host: str) -> None:
        host = _domain_key(host)
        if not host or "." not in host:
            return
        if host in seen:
            return
        seen.add(host)
        out.append(host)

    compact = re.sub(r"[^a-z0-9]", "", key)
    if len(compact) >= 4:
        add(f"{compact}.com")

    words = [w for w in key.split() if w and w not in _DOMAIN_STOP]
    if len(words) >= 2:
        add(f"{''.join(words)}.com")
        add(f"{words[0]}.com")

    if "usa" in key.split():
        usa_slug = re.sub(r"[^a-z0-9]", "", key.replace(" ", ""))
        if len(usa_slug) >= 4:
            add(f"{usa_slug}.com")

    return out


def shelf_domain_trusted(company_name: str, domain: str) -> bool:
    """True when domain looks like the brand's site (not an event/partner host)."""
    host = _domain_key(domain)
    if not host:
        return False
    guessed = set(guess_brand_domains(company_name))
    if host in guessed:
        return True
    brand_key = normalize_company_key(_fold_accents(company_name))
    stem = host.split(".")[0]
    tokens = [t for t in brand_key.split() if len(t) >= 4]
    return bool(tokens and any(t in stem for t in tokens))
