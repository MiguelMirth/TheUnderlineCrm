"""
Heuristic prospect scoring for Underline outreach (Lia criteria: geography, alignment, role).
Used for logging, dry-run visibility, and a minimum-quality gate before Monday push.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from prospecting_qa import person_geo_tier

CONSUMER_VERTICALS = frozenset(
    {
        "Retail CPG + QSR",
        "Lifestyle + Premium Beverage + Entertainment",
        "Fitness + Performance Beverages",
    }
)

BAD_TITLE_MARKERS = (
    "store manager",
    "assistant store",
    "staffing",
    "privacy",
    "data security",
    "internal audit",
)

SPONSOR_TITLE_MARKERS = (
    "sponsorship",
    "partnership",
    "brand",
    "experiential",
    "events",
    "community",
    "marketing",
)


def score_prospect(
    *,
    person: Dict[str, Any],
    org: Dict[str, Any],
    title: str,
    shelf_brand: str,
    category: str,
) -> Tuple[int, str]:
    """Return (score 0-100, short label)."""
    score = 0
    parts: list[str] = []

    geo_t, geo_l = person_geo_tier(person)
    geo_points = {3: 35, 2: 22, 1: 12, 0: 0}.get(geo_t, 0)
    score += geo_points
    parts.append(f"geo={geo_l}({geo_points})")

    t = (title or "").lower()
    if any(b in t for b in BAD_TITLE_MARKERS):
        score -= 50
        parts.append("bad_title_penalty")

    if any(m in t for m in SPONSOR_TITLE_MARKERS):
        score += 25
        parts.append("relevant_title")
    else:
        parts.append("weak_title")

    if shelf_brand and shelf_brand.lower() in t:
        score += 15
        parts.append("brand_in_title")

    if category in CONSUMER_VERTICALS:
        score += 12
        parts.append("consumer_vertical")

    industry = (org.get("industry") or "").lower()
    if any(k in industry for k in ("food", "beverage", "retail", "consumer", "entertainment", "sport")):
        score += 8
        parts.append("consumer_industry")

    seniority = (person.get("seniority") or "").lower()
    if seniority in ("vp", "director", "head", "c_suite") or "vice president" in t or "director" in t:
        score += 10
        parts.append("senior_role")

    score = max(0, min(score, 100))
    label = "; ".join(parts)
    return score, label


def build_prospect_rationale(
    *,
    person: Dict[str, Any],
    org: Dict[str, Any],
    title: str,
    shelf_brand: str,
    category: str,
    geo_score: int,
    fit_score: int,
) -> str:
    p_city = (person.get("city") or "").strip()
    p_state = (person.get("state") or "").strip()
    org_name = (org.get("name") or "").strip()
    brand = shelf_brand or org_name
    return (
        f"A) Contact in {p_city or '?'}, {p_state or '?'} (geo tier {geo_score}/3). "
        f"B) {brand} — {category or 'general'} brand alignment for Miami park/concert activations. "
        f"C) {title or 'unknown title'} — score {fit_score}/100."
    )
