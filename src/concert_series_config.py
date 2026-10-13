"""
Concert Series prospecting constants — Miami Music Series sponsorship ICP.

Offer: The Underline's Miami Music Series (Levitt BLOC 2026). Buyers are
paid-sponsorship / brand / experiential people at cash-sponsor brands, not
community / collab / in-kind desks.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

CONCERT_SERIES_VERTICAL_LABEL = "Concert Series"

# Paid-buyer titles only. Do not import SPONSORSHIP_APOLLO_SEARCH_TITLES —
# that list includes Community Relations, CSR, generic Partnerships, Events.
CONCERT_SERIES_PERSON_TITLES: List[str] = [
    "Sponsorship",
    "Sponsorships",
    "Director of Sponsorships",
    "Head of Sponsorship",
    "VP Sponsorship",
    "Sponsorship Marketing",
    "Brand Marketing",
    "Brand Partnerships",
    "VP Brand Partnerships",
    "Director of Brand Marketing",
    "Experiential Marketing",
    "Entertainment Marketing",
    "Festival Marketing",
    "Head of Experiential",
    "Director of Experiential",
    "Trade Marketing",
    "VP Marketing",
    "Vice President Marketing",
    "Vice President Brand",
    "Head of Brand",
    "Head of Marketing",
    "Chief Marketing Officer",
    "CMO",
    "Marketing Director",
    "Director of Marketing",
]

# Volume, but skip intern/entry coordinators.
CONCERT_SERIES_PERSON_SENIORITIES: List[str] = [
    "manager",
    "senior",
    "director",
    "vp",
    "head",
    "c_suite",
]

CONCERT_SERIES_LOCATIONS_TIER1: List[str] = [
    "Miami, Florida, United States",
    "Miami Beach, Florida, United States",
    "Coral Gables, Florida, United States",
    "Brickell, Florida, United States",
    "Doral, Florida, United States",
    "Aventura, Florida, United States",
    "Coconut Grove, Florida, United States",
    "Kendall, Florida, United States",
    "Homestead, Florida, United States",
    "Hialeah, Florida, United States",
]

CONCERT_SERIES_LOCATIONS_TIER2: List[str] = [
    "Fort Lauderdale, Florida, United States",
    "Hollywood, Florida, United States",
    "Pembroke Pines, Florida, United States",
    "Boca Raton, Florida, United States",
    "West Palm Beach, Florida, United States",
]

CONCERT_SERIES_LOCATIONS_TIER3: List[str] = [
    "Tampa, Florida, United States",
    "Orlando, Florida, United States",
    "Jacksonville, Florida, United States",
    "Florida, United States",
]

CONCERT_SERIES_LOCATIONS_TIER4: List[str] = [
    "United States",
]

CONCERT_SERIES_LOCATION_TIERS: List[Tuple[int, List[str]]] = [
    (1, CONCERT_SERIES_LOCATIONS_TIER1),
    (2, CONCERT_SERIES_LOCATIONS_TIER2),
    (3, CONCERT_SERIES_LOCATIONS_TIER3),
    (4, CONCERT_SERIES_LOCATIONS_TIER4),
]

# Brands that buy concert inventory. Drop restaurants / generic entertainment
# (venues + nonprofits). Keep alcohol, CPG, apparel, cosmetics, banking, telecom, auto, F&B, insurance.
CONCERT_SERIES_ORG_KEYWORD_TAGS: List[str] = [
    "food and beverages",
    "alcoholic beverages",
    "wine and spirits",
    "consumer goods",
    "consumer packaged goods",
    "retail",
    "apparel & fashion",
    "cosmetics",
    "banking",
    "telecommunications",
    "automotive",
    "insurance",
]

CONCERT_SERIES_ORG_LOCATIONS: List[str] = [
    "Miami, Florida, United States",
    "Miami Beach, Florida, United States",
    "Fort Lauderdale, Florida, United States",
    "Florida, United States",
]

# Apollo people/org headcount buckets. Concert search starts at 51+ by default.
_APOLLO_HEADCOUNT_RANGES: List[Tuple[int, Optional[int], str]] = [
    (1, 10, "1,10"),
    (11, 20, "11,20"),
    (21, 50, "21,50"),
    (51, 100, "51,100"),
    (101, 200, "101,200"),
    (201, 500, "201,500"),
    (501, 1000, "501,1000"),
    (1001, 2000, "1001,2000"),
    (2001, 5000, "2001,5000"),
    (5001, 10000, "5001,10000"),
    (10001, None, "10001+"),
]

DEFAULT_MIN_ORG_REVENUE = 10_000_000
DEFAULT_MIN_ORG_EMPLOYEES = 51
DEFAULT_MAX_PER_COMPANY = 3
DEFAULT_TARGET = 500
DEFAULT_MAX_TIER = 3
DEFAULT_SPEND_BATCH_SIZE = 8
DEFAULT_SPEND_CONCURRENCY = 3


def concert_min_org_revenue() -> int:
    raw = os.getenv("CONCERT_MIN_ORG_REVENUE", str(DEFAULT_MIN_ORG_REVENUE)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MIN_ORG_REVENUE


def concert_min_org_employees() -> int:
    raw = os.getenv("CONCERT_MIN_ORG_EMPLOYEES", str(DEFAULT_MIN_ORG_EMPLOYEES)).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_MIN_ORG_EMPLOYEES


def concert_require_spend_evidence() -> bool:
    return os.getenv("CONCERT_REQUIRE_SPEND_EVIDENCE", "true").lower() == "true"


def concert_spend_batch_size() -> int:
    raw = os.getenv("CONCERT_SPEND_BATCH_SIZE", str(DEFAULT_SPEND_BATCH_SIZE)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SPEND_BATCH_SIZE


def concert_spend_concurrency() -> int:
    raw = os.getenv("CONCERT_SPEND_CONCURRENCY", str(DEFAULT_SPEND_CONCURRENCY)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_SPEND_CONCURRENCY


def concert_spend_tavily_depth() -> str:
    depth = os.getenv("CONCERT_SPEND_TAVILY_DEPTH", "fast").strip().lower()
    if depth not in {"ultra-fast", "fast", "basic", "advanced"}:
        return "fast"
    return depth


def concert_spend_cache_path() -> str:
    override = os.getenv("CONCERT_SPEND_CACHE_FILE", "").strip()
    if override:
        return override
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "outputs", "concert_spend_cache.json")


def concert_employee_ranges(min_employees: Optional[int] = None) -> List[str]:
    """Apollo organization_num_employees_ranges at or above the concert floor."""
    floor = concert_min_org_employees() if min_employees is None else int(min_employees)
    out: List[str] = []
    for lo, hi, label in _APOLLO_HEADCOUNT_RANGES:
        if hi is None:
            if lo >= floor:
                out.append(label)
        elif hi >= floor:
            out.append(label)
    return out
