"""
Venue rental prospecting constants — titles, seniorities, geo tiers, org keywords.

ICP: people who plan / book events and would rent The Underline's spaces
(event planners, wedding planners, corporate event managers, agencies, nonprofits).
"""
from __future__ import annotations

from typing import List, Tuple

# Monday Vertical dropdown label for this vertical.
VENUE_RENTAL_VERTICAL_LABEL = "Venue Rental"

# Apollo people-search titles (volume-first; coordinators included on purpose).
VENUE_RENTAL_PERSON_TITLES: List[str] = [
    "Event Planner",
    "Senior Event Planner",
    "Event Manager",
    "Director of Events",
    "VP of Events",
    "Head of Events",
    "Special Events Manager",
    "Special Events Coordinator",
    "Corporate Events Manager",
    "Meeting Planner",
    "Meeting & Events Manager",
    "Event Producer",
    "Experiential Producer",
    "Wedding Planner",
    "Wedding Coordinator",
    "Director of Catering & Events",
    "Venue Manager",
    "Program Manager Events",
    "Development & Events Manager",
    "Director of Development",
    "Marketing Manager Events",
    "Conference Manager",
    "Association Manager",
    "Events Coordinator",
    "Event Coordinator",
]

# Include entry/coordinator-level — they often book venues.
VENUE_RENTAL_PERSON_SENIORITIES: List[str] = [
    "entry",
    "manager",
    "senior",
    "director",
    "vp",
    "head",
]

# Tier 1: Miami-Dade core (primary).
VENUE_RENTAL_LOCATIONS_TIER1: List[str] = [
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

# Tier 2: Broward / Palm Beach.
VENUE_RENTAL_LOCATIONS_TIER2: List[str] = [
    "Fort Lauderdale, Florida, United States",
    "Hollywood, Florida, United States",
    "Pembroke Pines, Florida, United States",
    "Boca Raton, Florida, United States",
    "West Palm Beach, Florida, United States",
]

# Tier 3: Rest of Florida.
VENUE_RENTAL_LOCATIONS_TIER3: List[str] = [
    "Tampa, Florida, United States",
    "Orlando, Florida, United States",
    "Jacksonville, Florida, United States",
    "Florida, United States",
]

# Tier 4: US-wide fallback (only if still short of target).
VENUE_RENTAL_LOCATIONS_TIER4: List[str] = [
    "United States",
]

# (tier_number, person_locations) — search order for volume fills.
VENUE_RENTAL_LOCATION_TIERS: List[Tuple[int, List[str]]] = [
    (1, VENUE_RENTAL_LOCATIONS_TIER1),
    (2, VENUE_RENTAL_LOCATIONS_TIER2),
    (3, VENUE_RENTAL_LOCATIONS_TIER3),
    (4, VENUE_RENTAL_LOCATIONS_TIER4),
]

# Org keyword tags for org-first path (events / wedding / hospitality / nonprofit).
VENUE_RENTAL_ORG_KEYWORD_TAGS: List[str] = [
    "event planning",
    "wedding planning & services",
    "events services",
    "meeting and event planning",
    "hospitality",
    "non-profit organization management",
]

# Org HQ locations for org-keyword search (Miami-first, then FL).
VENUE_RENTAL_ORG_LOCATIONS: List[str] = [
    "Miami, Florida, United States",
    "Miami Beach, Florida, United States",
    "Fort Lauderdale, Florida, United States",
    "Florida, United States",
]

# Org size floor (very low — small planners OK).
VENUE_RENTAL_ORG_EMPLOYEE_RANGES: List[str] = [
    "1,10",
    "11,20",
    "21,50",
    "51,100",
    "101,200",
    "201,500",
    "501,1000",
    "1001,2000",
    "2001,5000",
]
