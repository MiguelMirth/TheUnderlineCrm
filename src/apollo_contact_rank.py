"""
Rank Apollo people by sponsorship-title fit (title is the primary signal for Underline outreach).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from prospecting_qa import normalize_company_key, person_geo_tier, title_gate

_US_COUNTRY = frozenset({"united states", "usa", "us", "u.s.", "u.s.a."})

SHARED_EMPLOYER_GENERIC_TITLE_MARKERS = (
    "brand manager",
    "brand marketing",
    "marketing manager",
    "marketing director",
    "director of marketing",
    "head of marketing",
    "vp marketing",
    "vice president marketing",
    "chief marketing",
    "cmo",
    "global marketing",
    "trade marketing",
    "experiential",
    "sponsorship",
    "partnership",
    "brand partnerships",
    "field marketing",
    "brand director",
    "brand experience",
    "integrated marketing",
    "consumer marketing",
    "activation",
    "events manager",
    "event marketing",
    "community relations",
    "corporate communications",
)


def title_mentions_brand(title: str, brand_name: str) -> bool:
    t = normalize_company_key(title)
    b = normalize_company_key(brand_name)
    if not b:
        return True
    if b in t:
        return True
    for token in b.split():
        if len(token) >= 4 and token in t:
            return True
    return False


def shared_employer_brand_title_ok(title: str, brand_name: str) -> bool:
    """
    At shared employers (PepsiCo for Gatorade), accept brand-in-title OR
    generic brand/sponsorship marketing titles. FL/geo still enforced post-enrich.
    """
    if title_mentions_brand(title, brand_name):
        return True
    t = (title or "").lower()
    return any(m in t for m in SHARED_EMPLOYER_GENERIC_TITLE_MARKERS)

# Higher = better sponsorship decision-maker titles
_TITLE_SCORE_RULES: list[tuple[int, tuple[str, ...]]] = [
    (
        100,
        (
            "director of sponsorship",
            "head of sponsorship",
            "vp sponsorship",
            "vice president sponsorship",
            "svp sponsorship",
        ),
    ),
    (
        95,
        (
            "director of partnerships",
            "head of partnerships",
            "vp partnerships",
            "vice president partnerships",
            "director of brand partnerships",
            "head of brand partnerships",
        ),
    ),
    (
        88,
        (
            "sponsorship manager",
            "partnerships manager",
            "brand partnerships",
            "sponsorship marketing",
            "partnership marketing",
        ),
    ),
    (
        82,
        (
            "experiential marketing",
            "event marketing",
            "field marketing",
            "activation manager",
            "brand experience",
        ),
    ),
    (
        75,
        (
            "brand marketing",
            "director of marketing",
            "head of marketing",
            "marketing director",
            "vp marketing",
            "vice president marketing",
            "chief marketing officer",
            "chief marketing",
            "cmo",
            "global marketing director",
            "global marketing",
        ),
    ),
    (
        68,
        (
            "community relations",
            "corporate communications",
            "corporate social responsibility",
            "csr",
        ),
    ),
    (
        55,
        (
            "marketing manager",
            "brand manager",
            "integrated marketing",
            "consumer marketing",
        ),
    ),
]


def sponsorship_title_score(title: str, *, shelf_brand: str = "") -> int:
    t = (title or "").strip().lower()
    if not t:
        return 0

    ok, _ = title_gate(title)
    if not ok:
        return 0

    best = 0
    for points, phrases in _TITLE_SCORE_RULES:
        if any(p in t for p in phrases):
            best = max(best, points)

    if any(k in t for k in ("sponsor", "partnership", "brand", "experiential", "activation")):
        best = max(best, 50)

    if shelf_brand and title_mentions_brand(title, shelf_brand):
        best += 12

    seniority_boost = 0
    if any(x in t for x in ("chief marketing", "cmo", "chief brand")):
        seniority_boost = 8
    elif any(x in t for x in ("vp ", "vice president", "svp", "head of", "director")):
        seniority_boost = 5

    return min(100, best + seniority_boost)


def rank_contacts_for_sponsorship(
    people: List[Dict[str, Any]],
    *,
    shelf_brand: str = "",
    shared_employer: bool = False,
) -> List[Dict[str, Any]]:
    """Sort Apollo people: best sponsorship titles first, then geography tier, then has_email."""

    def _us_rank(p: Dict[str, Any]) -> int:
        country = (p.get("country") or "").strip().lower()
        if not country:
            return 1
        return 1 if country in _US_COUNTRY or "united states" in country else 0

    def sort_key(p: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
        title = (p.get("title") or "").strip()
        if shared_employer and shelf_brand:
            if not shared_employer_brand_title_ok(title, shelf_brand):
                title_pts = 0
            else:
                title_pts = sponsorship_title_score(title, shelf_brand=shelf_brand)
        else:
            title_pts = sponsorship_title_score(title, shelf_brand=shelf_brand)

        geo_pts, _ = person_geo_tier(p)
        has_email = 1 if p.get("has_email") else 0
        seniority_pts = 0
        sen = (p.get("seniority") or "").lower()
        if sen in ("vp", "director", "head"):
            seniority_pts = 2
        elif sen == "manager":
            seniority_pts = 1

        return (title_pts, _us_rank(p), geo_pts, has_email, seniority_pts)

    return sorted(people, key=sort_key, reverse=True)


def person_tagged_non_us(person: Dict[str, Any]) -> bool:
    country = (person.get("country") or "").strip().lower()
    if not country:
        return False
    if country in _US_COUNTRY or "united states" in country:
        return False
    return True


def prefer_us_candidates(
    people: List[Dict[str, Any]],
    *,
    require_us: bool = True,
) -> List[Dict[str, Any]]:
    """
    Drop Apollo rows explicitly tagged non-US before enrich (saves credits).
    Keep unknown-country rows — location often appears only after enrich.
    """
    if not require_us or not people:
        return people
    us_tagged = [p for p in people if not person_tagged_non_us(p)]
    return us_tagged if us_tagged else people


def should_enrich_person(
    person: Dict[str, Any],
    *,
    shelf_brand: str = "",
    shared_employer: bool = False,
    research_mode: bool = False,
    min_title_score: int | None = None,
) -> Tuple[bool, str, int]:
    """
    Cheap pre-enrich gates using search-result fields only.

    Returns (ok, reason, title_score). When ok is False, skip Apollo enrich.
    """
    import os

    title = (person.get("title") or "").strip()
    title_pts = sponsorship_title_score(title, shelf_brand=shelf_brand)

    if person_tagged_non_us(person):
        country = (person.get("country") or "").strip()
        return False, f"geo QA: person_country_not_us:{country}", title_pts

    ok_title, tr = title_gate(title)
    if not ok_title:
        return False, f"title QA: {tr} — {title!r}", title_pts

    if shared_employer and shelf_brand:
        if not shared_employer_brand_title_ok(title, shelf_brand):
            return False, f"title not brand/sponsorship-relevant for {shelf_brand!r}", title_pts

    if research_mode:
        floor = (
            min_title_score
            if min_title_score is not None
            else int(os.getenv("PROSPECT_MIN_TITLE_SCORE", "45"))
        )
        if title_pts < floor:
            return False, f"title fit too weak ({title_pts}/100) — {title!r}", title_pts

    return True, "", title_pts
