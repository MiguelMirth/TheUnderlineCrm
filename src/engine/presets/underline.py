"""
The Underline preset (Miami, 2026). Data only: no I/O at import time.

Values mirror the code defaults the old CLIs used. Where the brief and the code
disagreed, the code wins and the README names the change.
"""
from __future__ import annotations

from concert_series_config import (
    CONCERT_SERIES_LOCATION_TIERS,
    CONCERT_SERIES_ORG_KEYWORD_TAGS,
    CONCERT_SERIES_ORG_LOCATIONS,
    CONCERT_SERIES_PERSON_SENIORITIES,
    CONCERT_SERIES_PERSON_TITLES,
    CONCERT_SERIES_VERTICAL_LABEL,
)
from engine.models import Caps, CrmContract, Preset, SourceSpec, ToggleSpec, VerticalSpec
from prospecting_config import (
    APOLLO_FL_PERSON_LOCATIONS,
    APOLLO_US_PERSON_LOCATIONS,
    SPONSORSHIP_APOLLO_SEARCH_TITLES,
)
from venue_rental_config import (
    VENUE_RENTAL_LOCATION_TIERS,
    VENUE_RENTAL_ORG_KEYWORD_TAGS,
    VENUE_RENTAL_ORG_LOCATIONS,
    VENUE_RENTAL_PERSON_SENIORITIES,
    VENUE_RENTAL_PERSON_TITLES,
    VENUE_RENTAL_VERTICAL_LABEL,
)

_SPONSOR_SENIORITIES = ["c_suite", "vp", "head", "director", "manager"]


def _tier_params(tiers: list[tuple[int, list[str]]]) -> list[dict[str, object]]:
    return [{"tier": int(tier), "locations": list(locations)} for tier, locations in tiers]

UNDERLINE_CRM = CrmContract(
    board_id_env="MASTER_BOARD_ID",
    board_id_default="18401545002",
    new_leads_group_env="NEW_LEADS_GROUP_ID",
    new_leads_group_default="group_mm0xbmrj",
    columns={
        "first_name": "text_mm0xjngp",
        "last_name": "text_mm0xg7qz",
        "email": "email_mm0xb00t",
        "title": "text_mm0xg2xb",
        "contact_type": "dropdown_mm0x5x0q",
        "seniority": "text_mm0x49y",
        "departments": "text_mm0xcyag",
        "website": "text_mm0xt1wm",
        "linkedin": "text_mm0xyyzh",
        "annual_revenue": "numeric_mm0x7xfb",
        "city": "text_mm0xkdyw",
        "state": "text_mm0xrszg",
        "country": "text_mm0x4tb7",
        "vertical": "dropdown_mm0xx10b",
        "status": "status",
        "notes": "text_mm0xz0w2",
    },
    # Engaged / Replied, Meeting / Pipeline, Closed Won
    protected_group_ids=["group_mm0xj5rd", "group_mm0xj1qw", "group_mm0xnfca"],
    protected_status_labels=["replied", "meeting set", "proposal sent"],
)

_RESEARCH_TOGGLES = [
    ToggleSpec(id="florida_person_only", label="Florida person only", kind="bool", default=True, relaxed_when="off"),
    ToggleSpec(id="require_us", label="US person required", kind="bool", default=True, relaxed_when="off"),
    ToggleSpec(id="allow_global_org", label="Allow global org HQ", kind="bool", default=True, relaxed_when="on"),
    ToggleSpec(id="min_confidence", label="Min brand confidence", kind="int", default=80, relaxed_when="lower"),
    ToggleSpec(id="min_brand_revenue", label="Min brand revenue (USD)", kind="int", default=10_000_000, relaxed_when="lower"),
    ToggleSpec(id="min_employees", label="Min employees", kind="int", default=0, relaxed_when="lower"),
    ToggleSpec(id="max_per_company", label="Max contacts per company", kind="int", default=2, relaxed_when="higher"),
    ToggleSpec(id="min_contact_score", label="Min contact score", kind="int", default=55, relaxed_when="lower"),
]

_SPONSOR_TOGGLES = [
    *_RESEARCH_TOGGLES,
    ToggleSpec(id="discover_new_events", label="Discover new events (paid)", kind="bool", default=False),
]

_CONCERT_TOGGLES = [
    ToggleSpec(id="florida_person_only", label="Florida person only", kind="bool", default=True, relaxed_when="off"),
    ToggleSpec(id="max_tier", label="Location tier (3 = Florida, 4 = US)", kind="int", default=3, relaxed_when="higher"),
    ToggleSpec(id="require_spend_evidence", label="Paid-spend evidence", kind="bool", default=True, relaxed_when="off"),
    ToggleSpec(id="min_revenue", label="Min org revenue (USD)", kind="int", default=10_000_000, relaxed_when="lower"),
    ToggleSpec(id="min_employees", label="Min org employees", kind="int", default=51, relaxed_when="lower"),
    ToggleSpec(id="org_path", label="Org-keyword path (credits per page)", kind="bool", default=True),
    ToggleSpec(id="max_per_company", label="Max contacts per company", kind="int", default=3, relaxed_when="higher"),
]

_VENUE_TOGGLES = [
    ToggleSpec(id="florida_person_only", label="Florida person only", kind="bool", default=True, relaxed_when="off"),
    ToggleSpec(id="us_fallback", label="US fallback (drops Florida)", kind="bool", default=False, relaxed_when="on"),
    ToggleSpec(id="org_path", label="Org-keyword path (credits per page)", kind="bool", default=True),
    # 0 means unlimited, as today. Any positive cap is tighter.
    ToggleSpec(id="max_per_company", label="Max contacts per company (0 = no cap)", kind="int", default=0, relaxed_when="lower"),
]

UNDERLINE_VERTICALS: list[VerticalSpec] = [
    VerticalSpec(
        id="sponsor_brands",
        label="Sponsor brands",
        icp=(
            "Shelf consumer brands with sponsorship budget. Contacts who can buy sponsorship or brand "
            "marketing. Florida or Miami preferred; global HQ is fine when the person is in market."
        ),
        monday_vertical="from_research",
        source=SourceSpec(
            kind="research_events",
            params={
                "seed_path": "data/inputs/miami_events_seed.json",
                "brands_per_event": 12,
                "tavily_search_depth": "basic",
                "tavily_max_results": 8,
                "titles": list(SPONSORSHIP_APOLLO_SEARCH_TITLES),
                "seniorities": list(_SPONSOR_SENIORITIES),
                "florida_person_locations": list(APOLLO_FL_PERSON_LOCATIONS),
                "us_person_locations": list(APOLLO_US_PERSON_LOCATIONS),
            },
        ),
        gate_chain="sponsor",
        llm_qa="cursor_score",
        toggles=_SPONSOR_TOGGLES,
        caps=Caps(events=4, brands=8, queries_per_source=2),
    ),
    VerticalSpec(
        id="concert_series",
        label=CONCERT_SERIES_VERTICAL_LABEL,
        icp=(
            "Cash-sponsorship brands for the Miami Music Series. Official, title, or presenting spend, "
            "not community, collab, or in-kind partners. Paid-buyer titles only."
        ),
        monday_vertical=CONCERT_SERIES_VERTICAL_LABEL,
        source=SourceSpec(
            kind="apollo_people",
            params={
                "titles": list(CONCERT_SERIES_PERSON_TITLES),
                "seniorities": list(CONCERT_SERIES_PERSON_SENIORITIES),
                "org_keyword_tags": list(CONCERT_SERIES_ORG_KEYWORD_TAGS),
                "org_locations": list(CONCERT_SERIES_ORG_LOCATIONS),
                "person_location_tiers": _tier_params(CONCERT_SERIES_LOCATION_TIERS),
            },
        ),
        gate_chain="concert",
        llm_qa="gemini",
        toggles=_CONCERT_TOGGLES,
        caps=Caps(target=500, max_pages=15, title_chunk=5, org_pages=3, tavily_batch=8, gemini_batch=20),
    ),
    VerticalSpec(
        id="venue_rental",
        label=VENUE_RENTAL_VERTICAL_LABEL,
        icp=(
            "People who plan and book events: event and wedding planners, agencies, and nonprofit event "
            "staff. Florida person by default; the US fallback is a visible toggle."
        ),
        monday_vertical=VENUE_RENTAL_VERTICAL_LABEL,
        source=SourceSpec(
            kind="apollo_people",
            params={
                "titles": list(VENUE_RENTAL_PERSON_TITLES),
                "seniorities": list(VENUE_RENTAL_PERSON_SENIORITIES),
                "org_keyword_tags": list(VENUE_RENTAL_ORG_KEYWORD_TAGS),
                "org_locations": list(VENUE_RENTAL_ORG_LOCATIONS),
                "person_location_tiers": _tier_params(VENUE_RENTAL_LOCATION_TIERS),
            },
        ),
        gate_chain="venue",
        llm_qa="gemini",
        toggles=_VENUE_TOGGLES,
        caps=Caps(target=750, max_pages=15, title_chunk=5, org_pages=3, gemini_batch=20),
    ),
]

UNDERLINE_PRESET = Preset(
    id="underline",
    name="The Underline",
    place="Miami",
    year=2026,
    crm=UNDERLINE_CRM,
    blacklist_path="data/inputs/blacklist.txt",
    verticals=UNDERLINE_VERTICALS,
)
