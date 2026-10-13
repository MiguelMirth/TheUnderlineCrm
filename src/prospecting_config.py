"""
Shared prospecting constants for Apollo search + QA gates.
Tune via environment variables. The engine passes per-run toggles and does not read these at Start.
"""

# Apollo mixed_people search — company-name flow (broader title net, QA narrows).
DEFAULT_PERSON_TITLES = [
    "Sponsorship",
    "Sponsorships",
    "Partnership",
    "Partnerships",
    "Brand Marketing",
    "Brand",
    "Corporate Communications",
    "Marketing",
    "Experiential Marketing",
    "Community Relations",
    "Director",
    "VP",
    "Vice President",
    "Chief Marketing Officer",
    "CMO",
    "Head of Marketing",
]

# Apollo people search — sponsorship-facing roles only (no CEO/President/Founder).
SPONSORSHIP_APOLLO_SEARCH_TITLES = [
    "Sponsorship",
    "Sponsorships",
    "Director of Sponsorships",
    "Partnership",
    "Partnerships",
    "Director of Partnerships",
    "Brand Partnerships",
    "Brand Marketing",
    "Community Relations",
    "Experiential Marketing",
    "Events",
    "Corporate Social Responsibility",
    "VP Sponsorship",
    "VP Marketing",
    "Vice President Marketing",
    "Vice President Brand",
    "Head of Sponsorship",
    "Head of Brand",
    "Head of Marketing",
    "Chief Marketing Officer",
    "CMO",
    "Marketing Director",
    "Director of Marketing",
    "Director of Community Relations",
]

# Person must be US-based for Underline outreach (org HQ may be anywhere in US).
APOLLO_US_PERSON_LOCATIONS = [
    "United States",
]

# Person search when PROSPECT_REQUIRE_FLORIDA=true — no national US fallback.
APOLLO_FL_PERSON_LOCATIONS = [
    "Miami, Florida, United States",
    "Fort Lauderdale, Florida, United States",
    "West Palm Beach, Florida, United States",
    "Tampa, Florida, United States",
    "Orlando, Florida, United States",
    "Jacksonville, Florida, United States",
    "Florida, United States",
]

# Secondary pool when FL contacts are scarce — major southern US metros (not FL-required).
APOLLO_SOUTH_US_PERSON_LOCATIONS = [
    "Atlanta, Georgia, United States",
    "Dallas, Texas, United States",
    "Houston, Texas, United States",
    "Austin, Texas, United States",
    "Nashville, Tennessee, United States",
    "Charlotte, North Carolina, United States",
    "Raleigh, North Carolina, United States",
    "New Orleans, Louisiana, United States",
    "Birmingham, Alabama, United States",
    "Georgia, United States",
    "Texas, United States",
    "Tennessee, United States",
    "North Carolina, United States",
]

# Apollo mixed_people/api_search — sponsorship-facing keyword signal (used with person_titles).
APOLLO_SPONSORSHIP_Q_KEYWORDS = (
    "sponsorship partnerships brand marketing experiential events community relations"
)

# Apollo location filters (person + org). Tighten/loosen with PROSPECT_* env vars.
DEFAULT_PERSON_LOCATIONS = [
    "Miami, Florida, United States",
    "Fort Lauderdale, Florida, United States",
    "West Palm Beach, Florida, United States",
    "Tampa, Florida, United States",
    "Orlando, Florida, United States",
    "Jacksonville, Florida, United States",
    "Florida, United States",
    "United States",
]

DEFAULT_ORGANIZATION_LOCATIONS = [
    "Florida, United States",
    "United States",
]

# Apollo people-search seniorities — skip c_suite/owner/founder (too often CEO/chairman).
DEFAULT_PERSON_SENIORITIES = [
    "director",
    "vp",
    "head",
    "manager",
]

# Monday board "Vertical" dropdown — LLM must pick exactly one of these strings.
MONDAY_VERTICAL_LABELS = [
    "Finance + Banking",
    "Healthcare + Wellness",
    "Technology",
    "Telecom",
    "Fitness + Performance Beverages",
    "Retail CPG + QSR",
    "Lifestyle + Premium Beverage + Entertainment",
    "Venue Rental",
    "Concert Series",
]
